from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
import tempfile
from collections import defaultdict
import json
import re
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import and_, func, select

from app.api.deps import RequestContext, require_permission
from app.config import get_settings
from app.db.models import ContractDocument
from app.schemas.contracts import (
    IngestDocumentRequest,
    IngestDocumentResponse,
    LearnedCounterpartyItem,
    LearnedCounterpartyListResponse,
    RedlineApplyDecision,
    RedlineApplyResult,
    NegotiationFlowItem,
    NegotiationFlowSuggestUploadResponse,
    NegotiationOutcomeCreateRequest,
    NegotiationOutcomeCreateResponse,
    StrategicSuggestionRequest,
    StrategicSuggestionResponse,
    StrategySuggestUploadResponse,
    UploadedClauseSuggestion,
)
from app.services.audit_service import AuditService
from app.services.clause_intelligence import build_clause_intelligence_service
from app.services.corpus_parser import CorpusParserService
from app.services.document_service import DocumentIngestionService, OutcomeService
from app.services.llm_provider import build_llm_provider
from app.services.profile_service import ProfileService
from app.services.redline_editor import DocxRedlineEditorService, RedlineDecision
from app.services.retrieval import SmartRetrievalService
from app.services.strategy_engine import StrategySuggestionService
from app.services.vector_store import VectorStore

router = APIRouter(prefix="/v1", tags=["contracts"])
logger = logging.getLogger(__name__)

settings = get_settings()
clause_service = build_clause_intelligence_service(settings)
vector_store = VectorStore(settings, embedding_dim=clause_service.embedding_dim)
ingestion_service = DocumentIngestionService(clause_service, vector_store)
outcome_service = OutcomeService()
retrieval_service = SmartRetrievalService(clause_service, vector_store)
parser_service = CorpusParserService()
profile_service = ProfileService()
llm_provider = build_llm_provider(settings)
audit_service = AuditService()
strategy_service = StrategySuggestionService(
    retrieval_service=retrieval_service,
    profile_service=profile_service,
    llm_provider=llm_provider,
)
redline_editor_service = DocxRedlineEditorService()
MIN_EVIDENCE_SCORE = 0.15
STRONG_EVIDENCE_SCORE = 0.35
MIN_STRONG_CITATIONS = 2
CLAUSE_ANCHOR_MIN_SCORE = 0.2
CLAUSE_TYPE_MIN_SCORE = 0.3
NO_SUGGESTION_TEXT = "NO_SUGGESTION_INSUFFICIENT_EVIDENCE"


def _best_doc_type(examples: list[dict]) -> tuple[str | None, float]:
    if not examples:
        return None, 0.0
    weights: dict[str, float] = defaultdict(float)
    total = 0.0
    contributors = 0
    for row in examples:
        doc_type = row.get("doc_type")
        if not doc_type:
            continue
        score = float(row.get("score", 0.0))
        weight = max(0.0, min(1.0, score))
        if weight == 0:
            continue
        contributors += 1
        weights[str(doc_type)] += weight
        total += weight
    if not weights or total <= 0:
        return None, 0.0
    best_type, best_weight = max(weights.items(), key=lambda item: item[1])
    base_conf = best_weight / total
    # Confidence calibration: one supporting example should not imply certainty.
    sample_factor = min(1.0, contributors / 3.0)
    distinct_doc_types = len(weights)
    calibrated = base_conf * sample_factor
    if distinct_doc_types == 1 and contributors < 5:
        calibrated = min(calibrated, 0.6)
    return best_type, round(calibrated, 4)


def _is_substantive_clause(text: str) -> bool:
    clean = " ".join(text.split()).strip()
    if not clean:
        return False
    words = clean.split(" ")
    if len(words) <= 4 and len(clean) < 40:
        return False
    alpha_words = [w for w in words if any(ch.isalpha() for ch in w)]
    if len(alpha_words) < 4:
        return False
    return True


def _normalize_doc_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip().lower()
    return collapsed


def _infer_upload_doc_type(file_name: str, raw_text: str) -> str:
    joined = f"{file_name} {raw_text[:1500]}".lower()
    if any(token in joined for token in ["non-disclosure", " nda ", "_nda", "-nda", "mutual nda", "confidentiality agreement"]):
        return "NDA"
    if any(token in joined for token in ["master service agreement", " msa ", "_msa", "-msa"]):
        return "MSA"
    if any(token in joined for token in ["statement of work", " sow ", "_sow", "-sow"]):
        return "SOW"
    if any(token in joined for token in ["data processing agreement", " dpa ", "_dpa", "-dpa"]):
        return "DPA"
    if any(token in joined for token in ["service level agreement", " sla ", "_sla", "-sla"]):
        return "SLA"
    if any(token in joined for token in ["order form", "purchase order", " po ", "_po", "-po"]):
        return "ORDER_FORM"
    if any(token in joined for token in ["license agreement", "eula", "software license"]):
        return "LICENSE"
    if any(token in joined for token in ["amendment", "addendum"]):
        return "AMENDMENT"
    return "GENERAL"


def _doc_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return max(0.0, min(1.0, SequenceMatcher(None, a, b).ratio()))


def _is_same_text(a: str, b: str) -> bool:
    return _doc_similarity(_normalize_doc_text(a), _normalize_doc_text(b)) >= 0.985


def _select_resolution_example(examples: list[dict]) -> dict | None:
    if not examples:
        return None

    def _rank(item: dict) -> tuple[int, float]:
        outcome = str(item.get("outcome") or "")
        outcome_rank = 2 if outcome == "accepted" else (1 if outcome == "partially_accepted" else 0)
        rounds = _safe_rounds(item)
        score = float(item.get("score") or 0.0)
        return outcome_rank, rounds, score

    ranked = sorted(examples, key=_rank, reverse=True)
    return ranked[0] if ranked else None


def _safe_rounds(item: dict) -> int:
    try:
        rounds = int(item.get("negotiation_rounds") or 0)
    except Exception:
        rounds = 0
    return max(0, rounds)


def _precedent_quality_score(examples: list[dict]) -> float:
    if not examples:
        return 0.0
    weighted: list[float] = []
    for item in examples:
        base_score = max(0.0, min(1.0, float(item.get("score") or 0.0)))
        rounds = _safe_rounds(item)
        # Multi-round chains are treated as stronger precedent than single-step snippets.
        round_factor = min(1.35, 0.85 + (min(rounds, 10) * 0.05))
        outcome = str(item.get("outcome") or "").strip().lower()
        outcome_factor = 1.0 if outcome == "accepted" else (0.9 if outcome == "partially_accepted" else 0.8)
        weighted.append(base_score * round_factor * outcome_factor)

    best = max(weighted)
    avg = sum(weighted) / len(weighted)
    # Favor strongest final precedent while still requiring consistency across examples.
    blended = (best * 0.7) + (avg * 0.3)
    return max(0.0, min(1.0, blended))


def _raw_max_similarity_score(examples: list[dict]) -> float:
    if not examples:
        return 0.0
    return max(0.0, min(1.0, max((float(item.get("score") or 0.0) for item in examples), default=0.0)))


def _effective_precedent_score(examples: list[dict]) -> tuple[float, str]:
    has_multi_round = any(_safe_rounds(item) >= 2 for item in examples)
    if has_multi_round:
        return _precedent_quality_score(examples), "round_aware"
    return _raw_max_similarity_score(examples), "raw_max_similarity"


def _preferred_resolution_text(incoming_text: str, example: dict | None) -> str | None:
    if not example:
        return None
    incoming_words = len([w for w in str(incoming_text or "").split() if w.strip()])

    def _is_reasonable(candidate: str) -> bool:
        words = [w for w in str(candidate or "").split() if w.strip()]
        if not words:
            return False
        if len(words) > max(80, incoming_words * 3):
            return False
        if _token_overlap_ratio(candidate, incoming_text) < 0.15:
            return False
        return True

    candidates = [
        str(example.get("client_response") or "").strip(),
        str(example.get("counterparty_edit") or "").strip(),
        str(example.get("linked_redline_text") or "").strip(),
        str(example.get("source_text") or "").strip(),
        str(example.get("clause_text") or "").strip(),
        # Keep final_text last; it may contain full-document text in synthetic outcomes.
        str(example.get("final_text") or "").strip(),
    ]
    for candidate in candidates:
        if (
            candidate
            and not _is_same_text(candidate, incoming_text)
            and _is_reasonable(candidate)
            and not _is_synthetic_summary_comment(candidate)
            and not _is_system_noise_text(candidate)
        ):
            return candidate
    return None


def _build_contextual_comment(*, suggested_redline: str, example: dict | None) -> str:
    if example:
        prior_comment = str(example.get("client_response") or "").strip()
        if (
            prior_comment
            and not _is_same_text(prior_comment, suggested_redline)
            and not _is_synthetic_summary_comment(prior_comment)
        ):
            return prior_comment
        return "No direct precedent client comment available for this suggested redline."
    return "No direct precedent client comment available."


def _is_actionable_clause_type(value: str | None) -> bool:
    key = str(value or "").strip().lower()
    if not key:
        return False
    if key == "other":
        return False
    if key.startswith("redline_"):
        return False
    return True


def _token_set(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) > 2}


def _build_clause_candidates(raw_text: str) -> list[dict]:
    candidates: list[dict] = []
    raw = raw_text or ""
    raw_lower = raw.lower()
    cursor = 0
    segments = [seg.strip() for seg in clause_service.segment(raw_text or "") if seg and seg.strip()]
    for idx, seg in enumerate(segments[:300]):
        start = -1
        end = -1
        probe = seg[:160].lower()
        if probe:
            start = raw_lower.find(probe, cursor)
            if start < 0:
                start = raw_lower.find(probe)
        if start >= 0:
            end = min(len(raw), start + len(seg))
            cursor = min(len(raw), end)
        candidates.append(
            {
                "index": idx,
                "text": seg,
                "tokens": _token_set(seg),
                "start": start if start >= 0 else None,
                "end": end if end >= 0 else None,
            }
        )
    return candidates


def _match_clause_text_from_candidates(source: dict, clause_candidates: list[dict]) -> tuple[str | None, float]:
    if not clause_candidates:
        return None, 0.0
    basis = str(source.get("incoming_previous_text") or source.get("incoming_text") or "").strip()
    if not basis:
        return None, 0.0
    basis_tokens = _token_set(basis)
    source_pos_raw = source.get("source_position")
    source_pos = int(source_pos_raw) if isinstance(source_pos_raw, (int, float)) else None

    best: dict | None = None
    best_score = 0.0
    for cand in clause_candidates:
        token_score = 0.0
        cand_tokens = cand.get("tokens") or set()
        if basis_tokens and cand_tokens:
            overlap = len(basis_tokens.intersection(cand_tokens))
            token_score = overlap / max(1, len(basis_tokens))

        pos_score = 0.0
        if source_pos is not None and cand.get("start") is not None and cand.get("end") is not None:
            start = int(cand.get("start"))
            end = int(cand.get("end"))
            if start <= source_pos <= end:
                pos_score = 1.0
            else:
                distance = min(abs(source_pos - start), abs(source_pos - end))
                pos_score = 1.0 / (1.0 + (distance / 800.0))

        if source_pos is not None:
            score = (token_score * 0.45) + (pos_score * 0.55)
        else:
            score = token_score
        if score > best_score:
            best_score = score
            best = cand

    if not best:
        return None, 0.0
    text = str(best.get("text") or "").strip() or None
    return text, best_score


def _resolve_signal_clause_type(source: dict, examples: list[dict]) -> str | None:
    anchor_text = str(source.get("clause_anchor_text") or "").strip()
    anchor_score = float(source.get("clause_anchor_score") or 0.0)
    anchor_is_strong = anchor_score >= CLAUSE_ANCHOR_MIN_SCORE
    clause_examples = [ex for ex in examples if bool(ex.get("is_clause"))]

    # Prefer clause type from the closest retrieved clause example to matched in-document anchor text.
    if clause_examples and anchor_text and anchor_is_strong:
        best_type: str | None = None
        best_score = 0.0
        for ex in clause_examples:
            clause_type = str(ex.get("clause_type") or "").strip()
            if not _is_actionable_clause_type(clause_type):
                continue
            ex_text = str(ex.get("clause_text") or ex.get("anchor_clause_text") or ex.get("source_text") or "").strip()
            if not ex_text:
                continue
            sim = _doc_similarity(anchor_text, ex_text)
            score = (sim * 0.7) + (max(0.0, min(1.0, float(ex.get("score") or 0.0))) * 0.3)
            if score > best_score:
                best_score = score
                best_type = clause_type
        if best_type and best_score >= CLAUSE_TYPE_MIN_SCORE:
            return best_type

    # Fallback: weighted vote only from retrieved clause examples.
    if clause_examples:
        weights: dict[str, float] = defaultdict(float)
        max_seen = 0.0
        for ex in clause_examples:
            clause_type = str(ex.get("clause_type") or "").strip()
            if not _is_actionable_clause_type(clause_type):
                continue
            weight = max(0.0, min(1.0, float(ex.get("score") or 0.0)))
            weights[clause_type] += weight
            if weight > max_seen:
                max_seen = weight
        if weights and max_seen >= CLAUSE_TYPE_MIN_SCORE:
            return max(weights.items(), key=lambda item: item[1])[0]

    # Secondary fallback: classifier-based keyword mapping on anchor/incoming text.
    basis = str(source.get("incoming_previous_text") or source.get("incoming_text") or "").strip() or anchor_text
    if basis:
        try:
            guessed = clause_service.classify(basis)
            guessed_type = str(getattr(guessed, "clause_type", "") or "").strip()
            guessed_conf = float(getattr(guessed, "confidence", 0.0) or 0.0)
            if _is_actionable_clause_type(guessed_type) and guessed_conf >= 0.75:
                return guessed_type
        except Exception:
            pass
    return None


def _compact_signal_text(text: str, max_words: int = 36) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    # Keep only the first sentence-like fragment when text is very long.
    fragments = re.split(r"(?<=[.!?;:])\s+", clean)
    candidate = fragments[0].strip() if fragments else clean
    if len(candidate.split()) < 6 and len(fragments) > 1:
        candidate = f"{candidate} {fragments[1].strip()}".strip()
    return _word_limit(candidate, max_words=max_words)


def _compact_comment_block(text: str, max_lines: int = 4, max_words_per_line: int = 24) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        clean = " ".join(str(text or "").split()).strip()
        return _word_limit(clean, max_words=max_words_per_line) if clean else ""
    compacted = [_word_limit(line, max_words=max_words_per_line) for line in lines[:max_lines]]
    return "\n".join(compacted)


def _merge_comment_blocks(existing: str, incoming: str) -> str:
    parts: list[str] = []
    for chunk in (existing, incoming):
        for line in str(chunk or "").replace("\r\n", "\n").replace("|", "\n").split("\n"):
            clean = line.strip()
            if clean and clean not in parts:
                parts.append(clean)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    normalized: list[str] = []
    for line in parts:
        match = re.match(r"^\s*comment\s+\d+\s*(\(([^)]+)\))?\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if match:
            author = (match.group(2) or "").strip()
            text = (match.group(3) or "").strip()
            if author:
                normalized.append(f"({author}) {text}")
            else:
                normalized.append(text)
        else:
            normalized.append(line.strip())
    output: list[str] = []
    for idx, line in enumerate(normalized, start=1):
        author_match = re.match(r"^\(([^)]+)\)\s*(.*)$", line)
        if author_match:
            author = (author_match.group(1) or "").strip()
            text = (author_match.group(2) or "").strip()
            output.append(f"Comment {idx} ({author}): {text}")
        else:
            output.append(f"Comment {idx}: {line}")
    return "\n".join(output)


def _word_limit(text: str, max_words: int) -> str:
    words = [w for w in str(text or "").split() if w.strip()]
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:.") + "."


def _token_overlap_ratio(a: str, b: str) -> float:
    tokens_a = {t for t in re.findall(r"[a-z0-9]+", (a or "").lower()) if len(t) > 2}
    tokens_b = {t for t in re.findall(r"[a-z0-9]+", (b or "").lower()) if len(t) > 2}
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a.intersection(tokens_b)) / max(len(tokens_a), 1)


def _is_vague_instruction(text: str) -> bool:
    lowered = (text or "").lower()
    vague_markers = (
        "remove or revise",
        "more flexible clause",
        "please revise",
        "should be revised",
        "consider revising",
        "replace with appropriate",
        "update as needed",
    )
    return any(marker in lowered for marker in vague_markers)


def _is_low_quality_signal_text(text: str) -> bool:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return True
    if len(clean) < 12:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]+", clean.lower()) if len(t) > 1]
    if len(tokens) < 3:
        return True
    alpha_tokens = [t for t in tokens if any(ch.isalpha() for ch in t)]
    if len(alpha_tokens) < 2:
        return True
    return False


def _is_synthetic_summary_comment(text: str) -> bool:
    lowered = (text or "").lower()
    markers = (
        "synthetic outcome generated from parsed redlines/comments",
        "comment signals:",
        "top comment excerpts:",
    )
    return any(marker in lowered for marker in markers)


def _is_system_noise_text(text: str) -> bool:
    lowered = (text or "").lower()
    markers = (
        "extracted negotiation signals from corpus file",
        "redlines +",
        "profile=",
        "comment_accept=",
        "comment_reject=",
        "comment_revise=",
        "source_type=",
        "signal_text=",
        "anchor_clause=",
        "redline_before=",
        "redline_after=",
        "delete fragment:",
        "insert fragment:",
        "clause context:",
    )
    return any(marker in lowered for marker in markers)


def _deterministic_redline_rewrite(
    *,
    source: dict,
    resolution_example: dict | None,
    allow_precedent: bool = False,
) -> str | None:
    incoming = " ".join(str(source.get("incoming_text") or "").split()).strip()
    previous = " ".join(str(source.get("incoming_previous_text") or "").split()).strip()
    comment = " ".join(str(source.get("linked_comment_text") or "").split()).strip()
    event_type = str(source.get("redline_event_type") or "").strip().lower()

    base = incoming
    incoming_tokens = [t for t in re.findall(r"[a-z0-9]+", incoming.lower()) if len(t) > 2]
    if len(incoming_tokens) < 2 and previous:
        base = previous
    if not base:
        return None

    if allow_precedent and resolution_example:
        precedent_candidate = _preferred_resolution_text(base, resolution_example)
        if (
            precedent_candidate
            and not _is_same_text(precedent_candidate, base)
            and _token_overlap_ratio(precedent_candidate, base) >= 0.35
        ):
            return _word_limit(precedent_candidate, max_words=55)

    lowered_comment = comment.lower()
    qualifier = "subject to mutual written agreement."
    if any(k in lowered_comment for k in ("owner", "ownership", "trustee", "title", "assignee")):
        qualifier = "for clarity, ownership/title remains as stated in transaction documents."
    elif any(k in lowered_comment for k in ("warranty", "defect", "service level", "sla")):
        qualifier = "provided that obligations are limited to commercially reasonable efforts."
    elif any(k in lowered_comment for k in ("payment", "invoice", "fee", "cost", "price")):
        qualifier = "provided that payment timing follows mutually agreed invoice and approval terms."
    elif any(k in lowered_comment for k in ("liability", "indemn", "damages", "claim")):
        qualifier = "subject to agreed liability caps and carve-outs under this agreement."
    elif any(k in lowered_comment for k in ("termination", "notice", "cure", "renewal")):
        qualifier = "subject to clear notice and cure periods agreed by both parties."
    elif any(k in lowered_comment for k in ("confidential", "disclosure", "data", "privacy")):
        qualifier = "subject to confidentiality and data-use limits stated in this agreement."

    # Keep fallback output as a redline-focused suggestion only.
    # Do not concatenate full clause context into suggested redline text.
    if event_type == "deletion":
        return _word_limit(f"{base} {qualifier}", max_words=55)
    if event_type in {"insertion", "comment_range"}:
        if previous and incoming:
            if incoming.lower() in previous.lower():
                return _word_limit(f"{incoming} {qualifier}", max_words=55)
        return _word_limit(f"{base} {qualifier}", max_words=55)
    return _word_limit(f"{base} {qualifier}", max_words=55)


def _evidence_status(score: float, citations: int) -> str:
    if citations <= 0:
        return "none"
    # Pure precedent mode: only mark supported when both quality and sample size are strong.
    if citations >= MIN_STRONG_CITATIONS and score >= STRONG_EVIDENCE_SCORE:
        return "supported"
    if score >= MIN_EVIDENCE_SCORE:
        return "weak"
    return "weak"


def _resolve_linked_comment_text(event: dict, comments: list[dict], event_index: int | None = None) -> str | None:
    comment_ids = [str(cid).strip() for cid in (event.get("comment_ids") or []) if str(cid).strip()]
    if comment_ids:
        by_id: dict[str, tuple[str, str]] = {}
        for row in comments:
            if row.get("id") is None:
                continue
            cid = str(row.get("id")).strip()
            text = str(row.get("text") or "").strip()
            if not cid or not text:
                continue
            author = str(row.get("author") or "").strip()
            if cid not in by_id:
                by_id[cid] = (author, text)
        linked: list[tuple[str, str]] = []
        for cid in comment_ids:
            if cid in by_id and by_id[cid] not in linked:
                linked.append(by_id[cid])
        if linked:
            parts: list[str] = []
            for idx, (author, text) in enumerate(linked, start=1):
                author_label = author if author else "Unknown User"
                parts.append(f"Comment {idx} ({author_label}): {text}")
            return "\n".join(parts).strip()
        return f"Comment attached in document (id: {', '.join(comment_ids[:3])})"

    direct = str(
        event.get("comment_text")
        or event.get("linked_comment_text")
        or event.get("comment")
        or ""
    ).strip()
    if direct:
        return direct

    event_pos = event.get("position")
    if event_pos is None:
        return None
    try:
        event_pos_int = int(event_pos)
    except Exception:
        return None

    nearest_text: str | None = None
    nearest_distance: int | None = None
    for row in comments:
        text = str(row.get("text") or "").strip()
        pos = row.get("position")
        if not text or pos is None:
            continue
        try:
            pos_int = int(pos)
        except Exception:
            continue
        distance = abs(pos_int - event_pos_int)
        if distance > 2500:
            continue
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_text = text
    if nearest_text:
        return nearest_text

    if event_index is not None and 0 <= event_index < len(comments):
        indexed = str(comments[event_index].get("text") or "").strip()
        if indexed:
            return indexed

    author = str(event.get("author") or "").strip()
    timestamp = str(event.get("timestamp") or "").strip()
    if author or timestamp:
        if author and timestamp:
            return f"Track change by {author} on {timestamp}"
        if author:
            return f"Track change by {author}"
        return f"Track change timestamp: {timestamp}"

    return None


def _fallback_playbook(*, reason: str = "") -> dict:
    summary = "Generated with fallback mode. Review signal-level recommendations directly."
    if reason:
        summary = f"{summary} ({reason})"
    return {
        "playbook_summary": summary,
        "fastest_path_hint": "Prioritize high-confidence redlines first, then apply concise counterparty comments.",
        "expected_rounds_remaining": 2.0,
        "expected_days_to_close": 7,
        "probability_close_in_7_days": 0.5,
        "confidence": 0.4,
        "items": [],
    }


def _deterministic_playbook(*, signal_rows: list[dict], signal_examples: dict[tuple[str, int], list[dict]]) -> dict:
    total = len(signal_rows)
    if total <= 0:
        return {
            "playbook_summary": "No signals found.",
            "fastest_path_hint": "Upload a document with redlines/comments.",
            "expected_rounds_remaining": 2.0,
            "expected_days_to_close": 7,
            "probability_close_in_7_days": 0.5,
            "confidence": 0.4,
            "items": [],
        }

    supported = 0
    top_scores: list[float] = []
    for row in signal_rows:
        examples = signal_examples.get((row["source_type"], int(row["source_index"])), [])
        citations = len(examples)
        score = max((float(ex.get("score") or 0.0) for ex in examples), default=0.0)
        score = max(0.0, min(1.0, score))
        top_scores.append(score)
        if _evidence_status(score, citations) == "supported":
            supported += 1

    avg_score = sum(top_scores) / max(len(top_scores), 1)
    support_ratio = supported / max(total, 1)
    confidence = max(0.2, min(0.95, 0.35 + avg_score * 0.35 + support_ratio * 0.3))
    expected_rounds_remaining = max(1.0, round(3.6 - (support_ratio * 1.8 + avg_score * 1.2), 1))
    expected_days_to_close = max(3, int(round(expected_rounds_remaining * 3.0)))
    probability_close_in_7_days = max(0.05, min(0.95, 0.1 + support_ratio * 0.55 + avg_score * 0.3))

    redline_total = sum(1 for row in signal_rows if row.get("source_type") == "redline")
    comment_total = sum(1 for row in signal_rows if row.get("source_type") == "comment")
    topic_counts: dict[str, int] = defaultdict(int)
    stop_words = {
        "the", "and", "for", "that", "with", "this", "from", "shall", "will", "any",
        "are", "not", "all", "its", "into", "such", "have", "has", "was", "were",
        "you", "your", "our", "their", "but", "can", "may", "than", "then", "each",
        "per", "via", "new", "old", "inc", "llc", "ltd", "agreement",
    }
    for row in signal_rows:
        text = str(row.get("incoming_text") or "")
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if len(token) < 4 or token in stop_words:
                continue
            topic_counts[token] += 1
    top_topics = [token for token, _count in sorted(topic_counts.items(), key=lambda kv: kv[1], reverse=True)[:4]]
    topics_text = ", ".join(top_topics) if top_topics else "mixed clause edits"

    return {
        "playbook_summary": (
            "Deterministic retrieval mode (no LLM). "
            f"Document profile: {redline_total} redline signals and {comment_total} comment signals. "
            f"Primary themes: {topics_text}. "
            f"Supported signals: {supported}/{total}."
        ),
        "fastest_path_hint": "Resolve supported redlines first, reject unsupported ones, then request clarification for remaining gaps.",
        "expected_rounds_remaining": expected_rounds_remaining,
        "expected_days_to_close": expected_days_to_close,
        "probability_close_in_7_days": probability_close_in_7_days,
        "confidence": confidence,
        "items": [],
    }


def _insufficient_precedent_comment(*, source: dict, resolution_example: dict | None) -> str:
    incoming_comment = str(source.get("linked_comment_text") or "").strip()
    incoming_text = str(source.get("incoming_text") or "").strip()
    combined = f"{incoming_text} {incoming_comment}".lower()

    intent = "general"
    if any(k in combined for k in ("owner", "ownership", "title", "trustee", "assign")):
        intent = "ownership"
    elif any(k in combined for k in ("indemn", "liabil", "damages", "claim")):
        intent = "liability"
    elif any(k in combined for k in ("payment", "fee", "invoice", "price", "cost")):
        intent = "payment"
    elif any(k in combined for k in ("terminate", "termination", "notice", "renewal")):
        intent = "termination"
    elif any(k in combined for k in ("confidential", "nda", "disclos", "data")):
        intent = "confidentiality"
    elif any(k in combined for k in ("warranty", "service level", "sla", "uptime")):
        intent = "service"

    topic_snippet = _word_limit(incoming_text, max_words=10) if incoming_text else "this clause"
    if intent == "ownership":
        return (
            f"Ownership point needs explicit drafting in {topic_snippet}. "
            "Propose a narrow statement of title/beneficial ownership and ask counterparty to confirm exact legal entity wording."
        )
    if intent == "liability":
        return (
            f"Liability language around {topic_snippet} needs a bounded fallback. "
            "Propose cap/carve-out wording and request confirmation of risk allocation."
        )
    if intent == "payment":
        return (
            f"Payment terms in {topic_snippet} need a precise fallback. "
            "Propose objective trigger dates and clarify invoice/approval dependency."
        )
    if intent == "termination":
        return (
            f"Termination language in {topic_snippet} needs a narrower position. "
            "Propose clear notice/cure mechanics and ask which trigger is unacceptable."
        )
    if intent == "confidentiality":
        return (
            f"Confidentiality scope in {topic_snippet} requires targeted wording. "
            "Propose limited-use obligations with explicit carve-outs and confirm data categories."
        )
    if intent == "service":
        return (
            f"Service commitment wording in {topic_snippet} needs measurable terms. "
            "Propose objective SLA/warranty metrics and ask for acceptable thresholds."
        )

    if resolution_example and str(resolution_example.get("outcome") or "").strip():
        return (
            f"Nearest precedent is {resolution_example.get('outcome')}, but not close enough for direct reuse on {topic_snippet}. "
            "Propose a limited rewrite and request a concrete counterproposal."
        )
    return (
        f"No close precedent for {topic_snippet}. "
        "Draft a narrow fallback tied to the counterparty concern and request a concrete wording preference."
    )


@router.post("/documents/ingest", response_model=IngestDocumentResponse)
def ingest_document(
    request: IngestDocumentRequest,
    ctx: RequestContext = Depends(require_permission("document:ingest")),
) -> IngestDocumentResponse:
    try:
        document_id, clauses_ingested = ingestion_service.ingest_document(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="document.ingest",
            resource_type="contract_document",
            resource_id=str(document_id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "client_id": request.client_id,
                "doc_type": request.doc_type,
                "counterparty_name": request.counterparty_name,
                "clauses_ingested": clauses_ingested,
            },
        )
        ctx.db.commit()
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to ingest document: {exc}") from exc
    return IngestDocumentResponse(document_id=document_id, clauses_ingested=clauses_ingested)


@router.post("/outcomes", response_model=NegotiationOutcomeCreateResponse)
def record_outcome(
    request: NegotiationOutcomeCreateRequest,
    ctx: RequestContext = Depends(require_permission("outcome:write")),
) -> NegotiationOutcomeCreateResponse:
    try:
        outcome_id = outcome_service.record_outcome(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="outcome.record",
            resource_type="negotiation_outcome",
            resource_id=str(outcome_id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "client_id": request.client_id,
                "doc_type": request.doc_type,
                "clause_type": request.clause_type,
                "outcome": request.outcome,
            },
        )
        ctx.db.commit()
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to record outcome: {exc}") from exc
    return NegotiationOutcomeCreateResponse(outcome_id=outcome_id)


@router.post("/strategy/suggest", response_model=StrategicSuggestionResponse)
def strategy_suggest(
    request: StrategicSuggestionRequest,
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> StrategicSuggestionResponse:
    try:
        suggestion = strategy_service.suggest(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="strategy.suggest",
            resource_type="clause",
            resource_id=None,
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "analysis_scope": request.analysis_scope,
                "example_source": request.example_source,
                "client_id": request.client_id,
                "doc_type": request.doc_type,
                "counterparty_name": request.counterparty_name,
                "clause_type": suggestion.get("clause_type"),
                "top_k": request.top_k,
            },
        )
        ctx.db.commit()
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate strategy: {exc}") from exc
    return StrategicSuggestionResponse(**suggestion)


@router.post("/strategy/negotiation-suggest-upload", response_model=NegotiationFlowSuggestUploadResponse)
def strategy_negotiation_suggest_upload(
    file: UploadFile = File(...),
    analysis_scope: str = Form("single_client"),
    client_id: str | None = Form(None),
    doc_type: str | None = Form(None),
    counterparty_name: str | None = Form(None),
    contract_value: Decimal | None = Form(None),
    top_k: int = Form(6),
    max_signals: int = Form(0),
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> NegotiationFlowSuggestUploadResponse:
    temp_path: Path | None = None
    file_name = (file.filename or "").strip() or "upload"
    try:
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")
        if max_signals < 0:
            raise ValueError("max_signals must be >= 0 (0 means all)")

        suffix = Path(file_name).suffix.lower()
        if suffix not in parser_service.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension: {suffix or '(none)'}. "
                f"Supported: {', '.join(sorted(parser_service.SUPPORTED_EXTENSIONS))}"
            )

        file_bytes = file.file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".txt") as handle:
            handle.write(file_bytes)
            temp_path = Path(handle.name)

        parsed = parser_service.parse(temp_path)
        if parsed.parser_status != "ready":
            raise ValueError(parsed.parse_error or "Failed to parse uploaded file")
        if not parsed.raw_text.strip():
            raise ValueError("Uploaded file produced empty text")

        normalized_doc_type = doc_type.strip() if doc_type else _infer_upload_doc_type(file_name, parsed.raw_text)
        signal_rows: list[dict] = []
        all_comments = list(parsed.comments or [])
        redline_events = parsed.redline_events if max_signals == 0 else parsed.redline_events[:max_signals]
        comments = all_comments if max_signals == 0 else all_comments[:max_signals]
        redline_linked_comment_ids: set[str] = set()
        comment_range_merge_index: dict[tuple[str, int | None], int] = {}

        for idx, event in enumerate(redline_events):
            text = _compact_signal_text(str(event.get("text") or "").strip(), max_words=36)
            if not text:
                continue
            event_type = str(event.get("type") or "").strip().lower() or None
            comment_ids = [str(cid).strip() for cid in (event.get("comment_ids") or []) if str(cid).strip()]
            for cid in comment_ids:
                redline_linked_comment_ids.add(cid)
            paragraph_text = _compact_signal_text(str(event.get("paragraph_text") or "").strip(), max_words=40)
            previous_text: str | None = None
            if event_type in {"insertion", "comment_range"}:
                if paragraph_text and not _is_same_text(paragraph_text, text):
                    previous_text = paragraph_text
            elif event_type == "deletion":
                previous_text = text
            linked_comment = _compact_comment_block(
                str(_resolve_linked_comment_text(event, all_comments, idx) or "").strip(),
                max_lines=4,
                max_words_per_line=24,
            )
            if event_type == "comment_range":
                merge_key = (text.lower(), event.get("position"))
                existing_idx = comment_range_merge_index.get(merge_key)
                if existing_idx is not None:
                    existing = signal_rows[existing_idx]
                    existing_comment = str(existing.get("linked_comment_text") or "").strip()
                    incoming_comment = str(linked_comment or "").strip()
                    if incoming_comment:
                        existing["linked_comment_text"] = _merge_comment_blocks(existing_comment, incoming_comment)
                    existing_ids = [str(cid).strip() for cid in (existing.get("source_comment_ids") or []) if str(cid).strip()]
                    for cid in comment_ids:
                        if cid not in existing_ids:
                            existing_ids.append(cid)
                    existing["source_comment_ids"] = existing_ids
                    if not existing.get("source_comment_id") and existing_ids:
                        existing["source_comment_id"] = existing_ids[0]
                    continue

            signal_rows.append(
                {
                    "source_type": "redline",
                    "source_index": idx,
                    "source_position": event.get("position"),
                    "source_comment_id": comment_ids[0] if comment_ids else None,
                    "source_comment_ids": comment_ids,
                    "redline_event_type": event_type,
                    "incoming_text": text,
                    "incoming_previous_text": previous_text,
                    "linked_comment_text": linked_comment or None,
                }
            )
            if event_type == "comment_range":
                comment_range_merge_index[(text.lower(), event.get("position"))] = len(signal_rows) - 1
        for idx, comment in enumerate(comments):
            comment_id = str(comment.get("id")).strip() if comment.get("id") is not None else ""
            if comment_id and comment_id in redline_linked_comment_ids:
                # Already represented under the related redline item; avoid duplicate rows.
                continue
            author = str(comment.get("author") or "").strip()
            body_text = str(comment.get("text") or "").strip()
            combined_text = f"{author}: {body_text}" if author and body_text else body_text
            text = _compact_signal_text(combined_text, max_words=30)
            if not text:
                continue
            signal_rows.append(
                {
                    "source_type": "comment",
                    "source_index": idx,
                    "source_position": comment.get("position"),
                    "source_comment_id": str(comment.get("id")).strip() if comment.get("id") is not None else None,
                    "incoming_text": text,
                }
            )

        if not signal_rows:
            raise ValueError("No redline or comment signals found in uploaded document")

        clause_candidates = _build_clause_candidates(parsed.raw_text)
        for row in signal_rows:
            anchor_text, anchor_score = _match_clause_text_from_candidates(row, clause_candidates)
            row["clause_anchor_text"] = anchor_text
            row["clause_anchor_score"] = anchor_score

        requested_client = client_id.strip() if client_id else None
        signal_examples: dict[tuple[str, int], list[dict]] = {}
        flat_examples: list[dict] = []
        doc_type_weights: dict[str, float] = defaultdict(float)
        doc_type_weight_total = 0.0

        for row in signal_rows:
            request_model = StrategicSuggestionRequest(
                client_id=requested_client,
                analysis_scope=analysis_scope,
                example_source=row["source_type"],
                doc_type=normalized_doc_type or "GENERAL",
                counterparty_name=counterparty_name.strip() if counterparty_name else None,
                contract_value=contract_value,
                clause_type=None,
                new_clause_text=row["incoming_text"],
                top_k=top_k,
            )
            try:
                retrieval = retrieval_service.retrieve(ctx.db, ctx.tenant_id, request_model)
                examples = list(retrieval.get("examples") or [])
            except Exception:
                logger.exception(
                    "retrieve failed for signal source_type=%s source_index=%s",
                    row["source_type"],
                    row["source_index"],
                )
                examples = []

            # For redline signals, also retrieve clause-level precedents to expose legal clause types.
            if row["source_type"] == "redline":
                clause_examples: list[dict] = []
                try:
                    clause_request = StrategicSuggestionRequest(
                        client_id=requested_client,
                        analysis_scope=analysis_scope,
                        example_source="clause",
                        doc_type=normalized_doc_type or "GENERAL",
                        counterparty_name=counterparty_name.strip() if counterparty_name else None,
                        contract_value=contract_value,
                        clause_type=None,
                        new_clause_text=row["incoming_text"],
                        top_k=top_k,
                    )
                    clause_retrieval = retrieval_service.retrieve(ctx.db, ctx.tenant_id, clause_request)
                    clause_examples = list(clause_retrieval.get("examples") or [])
                except Exception:
                    logger.exception(
                        "clause retrieve failed for redline source_index=%s",
                        row["source_index"],
                    )
                if clause_examples:
                    seen_keys: set[tuple[str, str, str]] = set()
                    merged: list[dict] = []
                    for ex in [*examples, *clause_examples]:
                        key = (
                            str(ex.get("source_type") or ""),
                            str(ex.get("clause_id") or ""),
                            str(ex.get("source_text") or ex.get("clause_text") or ""),
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        merged.append(ex)
                    merged.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
                    examples = merged[: max(top_k, 1)]

            signal_examples[(row["source_type"], int(row["source_index"]))] = examples
            for ex in examples[: min(3, top_k)]:
                ex_text = _compact_signal_text(str(ex.get("source_text") or ex.get("clause_text") or ""), max_words=36)
                ex_client_response = _compact_signal_text(str(ex.get("client_response") or ""), max_words=28)
                ex_final_text = _compact_signal_text(str(ex.get("final_text") or ""), max_words=36)
                flat_examples.append(
                    {
                        "signal_source_type": row["source_type"],
                        "signal_source_index": row["source_index"],
                        "signal_text": row["incoming_text"][:500],
                        "example_source_type": ex.get("source_type"),
                        "example_text": ex_text,
                        "example_anchor_clause_text": ex.get("anchor_clause_text"),
                        "example_linked_redline_text": ex.get("linked_redline_text"),
                        "example_linked_comment_text": ex.get("linked_comment_text"),
                        "example_outcome": ex.get("outcome"),
                        "example_counterparty_edit": ex.get("counterparty_edit"),
                        "example_client_response": ex_client_response,
                        "example_final_text": ex_final_text,
                        "example_negotiation_rounds": ex.get("negotiation_rounds"),
                        "example_score": ex.get("score"),
                    }
                )
            clause_match_type, clause_match_conf = _best_doc_type(examples)
            if clause_match_type:
                weight = max(0.0, min(1.0, clause_match_conf))
                doc_type_weights[clause_match_type] += weight
                doc_type_weight_total += weight

        matched_doc_type: str | None = None
        matched_doc_type_confidence = 0.0
        if doc_type_weights:
            matched_doc_type, matched_weight = max(doc_type_weights.items(), key=lambda item: item[1])
            if doc_type_weight_total > 0:
                matched_doc_type_confidence = round(matched_weight / doc_type_weight_total, 4)

        playbook = _deterministic_playbook(signal_rows=signal_rows, signal_examples=signal_examples)

        items: list[NegotiationFlowItem] = []
        generated_items = playbook.get("items") if isinstance(playbook.get("items"), list) else []
        for idx, source in enumerate(signal_rows):
            generated = generated_items[idx] if idx < len(generated_items) and isinstance(generated_items[idx], dict) else {}
            examples = signal_examples.get((source["source_type"], source["source_index"]), [])
            citations = len(examples)
            top_score, score_mode = _effective_precedent_score(examples)
            top_score = max(0.0, min(1.0, top_score))
            status = _evidence_status(top_score, citations)
            has_supported_evidence = status == "supported"
            force_withhold = False
            resolution_example = _select_resolution_example(examples)
            generated_redline = str(generated.get("suggested_redline") or "").strip()
            if has_supported_evidence and (not generated_redline or _is_same_text(generated_redline, source["incoming_text"])):
                fallback_redline = _preferred_resolution_text(source["incoming_text"], resolution_example)
                if fallback_redline:
                    generated_redline = fallback_redline
            if has_supported_evidence and not generated_redline:
                generated_redline = source["incoming_text"]
            if has_supported_evidence and _token_overlap_ratio(generated_redline, source["incoming_text"]) < 0.2:
                fallback_redline = _preferred_resolution_text(source["incoming_text"], resolution_example)
                if fallback_redline:
                    generated_redline = fallback_redline
                else:
                    generated_redline = source["incoming_text"]
            if has_supported_evidence and any(
                marker in generated_redline.lower()
                for marker in (
                    "general terms agreement",
                    "this general terms agreement",
                    "by executing this",
                )
            ):
                fallback_redline = _preferred_resolution_text(source["incoming_text"], resolution_example)
                generated_redline = fallback_redline or source["incoming_text"]
            generated_redline = _word_limit(generated_redline, max_words=45) if generated_redline else ""

            generated_comment = str(generated.get("suggested_comment") or "").strip()
            if has_supported_evidence and (
                not generated_comment
                or _is_same_text(generated_comment, source["incoming_text"])
                or generated_comment.lower().startswith("please review this fallback phrasing")
            ):
                generated_comment = _build_contextual_comment(
                    suggested_redline=generated_redline,
                    example=resolution_example,
                )
            if has_supported_evidence and _token_overlap_ratio(generated_comment, generated_redline) < 0.12:
                generated_comment = _build_contextual_comment(
                    suggested_redline=generated_redline,
                    example=resolution_example,
                )
            generated_comment = _word_limit(generated_comment, max_words=28) if generated_comment else ""

            if has_supported_evidence and _is_vague_instruction(generated_redline):
                fallback_redline = _preferred_resolution_text(source["incoming_text"], resolution_example)
                if fallback_redline and not _is_vague_instruction(fallback_redline):
                    generated_redline = _word_limit(fallback_redline, max_words=45)

            if source.get("source_type") == "redline" and _is_low_quality_signal_text(source.get("incoming_text") or ""):
                generated_redline = NO_SUGGESTION_TEXT
                generated_comment = (
                    "Incoming redline text is too short/ambiguous for safe auto-drafting. "
                    "Client position: review the full clause context and draft a manual counter-redline."
                )
                generated_rationale = (
                    "Auto-redline suppressed: low-quality incoming signal text (short/fragmented). "
                    "Manual legal review required."
                )
                status = "weak"
                top_score = min(top_score, 0.12)
                citations = max(citations, 0)
                force_withhold = True

            if not has_supported_evidence and not force_withhold:
                heuristic_redline = _deterministic_redline_rewrite(
                    source=source,
                    resolution_example=resolution_example,
                    allow_precedent=False,
                )
                if heuristic_redline:
                    generated_redline = heuristic_redline
                    if status == "none":
                        generated_comment = (
                            "No close precedent found; provided deterministic fallback rewrite from incoming text and context."
                        )
                    else:
                        generated_comment = (
                            "Evidence is weak; provided deterministic fallback rewrite based on closest context."
                        )
                else:
                    generated_redline = NO_SUGGESTION_TEXT
                    if status == "none":
                        generated_comment = "No relevant precedent retrieved for this signal."
                    else:
                        generated_comment = "Retrieved precedent is weak; suggestion withheld to avoid hallucination."
            elif _is_same_text(generated_redline, source["incoming_text"]):
                heuristic_redline = _deterministic_redline_rewrite(
                    source=source,
                    resolution_example=resolution_example,
                    allow_precedent=True,
                )
                if heuristic_redline and not _is_same_text(heuristic_redline, source["incoming_text"]):
                    generated_redline = heuristic_redline
                    generated_comment = _build_contextual_comment(
                        suggested_redline=generated_redline,
                        example=resolution_example,
                    )
                else:
                    generated_redline = "INSUFFICIENT_PRECEDENT_FOR_CHANGE"
                    generated_comment = _insufficient_precedent_comment(
                        source=source,
                        resolution_example=resolution_example,
                    )

            generated_rationale = str(generated.get("rationale") or "").strip()
            if not generated_rationale and has_supported_evidence and resolution_example:
                outcome = str(resolution_example.get("outcome") or "resolved")
                rounds = resolution_example.get("negotiation_rounds")
                rounds_text = f", rounds={rounds}" if rounds is not None else ""
                generated_rationale = (
                    "Strong precedent match: "
                    f"outcome={outcome}, score_mode={score_mode}, precedent_quality={round(top_score, 4)}, "
                    f"citations={citations}{rounds_text}."
                )
            if not generated_rationale:
                if not has_supported_evidence:
                    generated_rationale = (
                        f"Abstained due to insufficient evidence (status={status}, "
                        f"score={round(top_score, 4)}, citations={citations})."
                    )
                else:
                    generated_rationale = "Generated from corpus signal retrieval."

            expected_outcome = str(
                generated.get("expected_outcome")
                or (resolution_example.get("outcome") if resolution_example else None)
                or "partially_accepted"
            )
            if expected_outcome not in {"accepted", "rejected", "partially_accepted"}:
                expected_outcome = "partially_accepted"
            if not has_supported_evidence:
                expected_outcome = "partially_accepted"
            signal_clause_type = _resolve_signal_clause_type(source, examples)
            if source.get("source_type") == "redline" and not signal_clause_type:
                if not has_supported_evidence:
                    generated_redline = NO_SUGGESTION_TEXT
                    generated_comment = (
                        "Clause association is weak for this redline. "
                        "Use manual legal review on full clause context before proposing edits."
                    )
                    generated_rationale = (
                        "Abstained: could not confidently map redline to a clause/type from precedent corpus."
                    )
                    status = "weak"
                    expected_outcome = "partially_accepted"
                else:
                    generated_rationale = f"{generated_rationale} Clause type unresolved from anchors/retrieval."
            items.append(
                NegotiationFlowItem(
                    source_type=source["source_type"],
                    source_index=source["source_index"],
                    clause_type=signal_clause_type,
                    source_position=(
                        int(source["source_position"]) if source.get("source_position") is not None else None
                    ),
                    source_comment_id=(
                        str(source.get("source_comment_id")).strip() if source.get("source_comment_id") else None
                    ),
                    redline_event_type=source.get("redline_event_type"),
                    incoming_text=source["incoming_text"],
                    incoming_previous_text=source.get("incoming_previous_text"),
                    linked_comment_text=source.get("linked_comment_text"),
                    suggested_redline=generated_redline,
                    suggested_comment=generated_comment,
                    rationale=generated_rationale,
                    expected_outcome=expected_outcome,
                    confidence=max(
                        0.0,
                        min(
                            1.0,
                            float(
                                generated.get("confidence")
                                or (resolution_example.get("score") if resolution_example else top_score)
                            ),
                        ),
                    ),
                    evidence_status=status,
                    evidence_score=top_score,
                    citation_count=citations,
                    retrieved_examples=examples[:top_k],
                )
            )

        supported_count = sum(1 for item in items if item.evidence_status == "supported")
        withheld_count = max(0, len(items) - supported_count)
        summary_text = (
            "Precedent-based analysis (no LLM). "
            f"Detected {len(redline_events)} redline item(s) and {len(comments)} comment item(s). "
            f"{supported_count} item(s) have strong precedent-backed guidance"
            + (
                f"; {withheld_count} item(s) need manual legal review due to weak/ambiguous evidence."
                if withheld_count > 0
                else "."
            )
        )

        linked_comment_count = sum(1 for row in signal_rows if row.get("source_type") == "redline" and row.get("linked_comment_text"))
        detected_comments = max(len(parsed.comments), linked_comment_count)

        response = NegotiationFlowSuggestUploadResponse(
            file_name=file_name,
            parser_status=parsed.parser_status,
            parse_error=parsed.parse_error,
            analysis_scope=analysis_scope,
            client_id=requested_client,
            doc_type=normalized_doc_type,
            matched_doc_type=matched_doc_type,
            matched_doc_type_confidence=matched_doc_type_confidence,
            counterparty_name=counterparty_name.strip() if counterparty_name else None,
            contract_value=contract_value,
            top_k=top_k,
            max_signals=max_signals,
            redline_events_detected=len(parsed.redline_events),
            comments_detected=detected_comments,
            playbook_summary=summary_text,
            fastest_path_hint=str(playbook.get("fastest_path_hint") or "Send one primary and one fallback option."),
            expected_rounds_remaining=max(0.0, float(playbook.get("expected_rounds_remaining") or 2.0)),
            expected_days_to_close=max(1, int(playbook.get("expected_days_to_close") or 7)),
            probability_close_in_7_days=max(0.0, min(1.0, float(playbook.get("probability_close_in_7_days") or 0.5))),
            confidence=max(0.0, min(1.0, float(playbook.get("confidence") or 0.5))),
            document_text=parsed.raw_text,
            items=items,
        )
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="strategy.negotiation_suggest_upload",
            resource_type="document_upload",
            resource_id=None,
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "file_name": file_name,
                "analysis_scope": analysis_scope,
                "client_id": response.client_id,
                "doc_type": response.doc_type,
                "matched_doc_type": response.matched_doc_type,
                "redline_events_detected": response.redline_events_detected,
                "comments_detected": response.comments_detected,
                "item_count": len(response.items),
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate negotiation flow suggestions: {exc}") from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@router.post("/strategy/redline-apply-upload")
def strategy_redline_apply_upload(
    file: UploadFile = File(...),
    decisions_json: str = Form(...),
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> Response:
    file_name = (file.filename or "").strip() or "upload.docx"
    try:
        suffix = Path(file_name).suffix.lower()
        if suffix != ".docx":
            raise ValueError("In-file redline updates are currently supported only for .docx")

        try:
            raw_decisions = json.loads(decisions_json)
        except Exception as exc:
            raise ValueError(f"decisions_json must be valid JSON: {exc}") from exc

        if not isinstance(raw_decisions, list):
            raise ValueError("decisions_json must be a JSON array")

        validated_decisions = [RedlineApplyDecision.model_validate(row) for row in raw_decisions]
        redline_decisions = [
            RedlineDecision(
                source_type=item.source_type,
                source_index=item.source_index,
                source_position=item.source_position,
                source_comment_id=item.source_comment_id,
                source_text=item.source_text,
                source_context_text=item.source_context_text,
                action=item.action,
                modified_text=item.modified_text,
                reply_comment=item.reply_comment,
            )
            for item in validated_decisions
        ]

        input_bytes = file.file.read()
        updated_bytes = redline_editor_service.apply_decisions(
            file_name=file_name,
            file_bytes=input_bytes,
            decisions=redline_decisions,
        )

        applied_count = sum(1 for item in validated_decisions if item.source_type == "redline")
        result = RedlineApplyResult(
            file_name=file_name,
            total_decisions=len(validated_decisions),
            applied_decisions=applied_count,
            skipped_decisions=len(validated_decisions) - applied_count,
        )
        output_name = f"{Path(file_name).stem}.updated.docx"

        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="strategy.redline_apply_upload",
            resource_type="document_upload",
            resource_id=None,
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata=result.model_dump(),
        )
        ctx.db.commit()

        return Response(
            content=updated_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{output_name}"',
                "X-Redline-Apply-Result": result.model_dump_json(),
            },
        )
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to apply redline decisions: {exc}") from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass


@router.get("/strategy/counterparties", response_model=LearnedCounterpartyListResponse)
def strategy_counterparties(
    client_id: str | None = Query(default=None),
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> LearnedCounterpartyListResponse:
    try:
        normalized_client = client_id.strip() if client_id else None
        stmt = (
            select(ContractDocument.counterparty_name, func.count(ContractDocument.id))
            .where(
                and_(
                    ContractDocument.tenant_id == ctx.tenant_id,
                    ContractDocument.counterparty_name.isnot(None),
                    ContractDocument.counterparty_name != "",
                )
            )
            .group_by(ContractDocument.counterparty_name)
            .order_by(func.count(ContractDocument.id).desc(), ContractDocument.counterparty_name.asc())
        )
        if normalized_client:
            stmt = stmt.where(ContractDocument.client_id == normalized_client)

        rows = ctx.db.execute(stmt).all()
        items = [
            LearnedCounterpartyItem(counterparty_name=str(name), document_count=int(count))
            for name, count in rows
            if name
        ]
        ctx.db.commit()
        return LearnedCounterpartyListResponse(
            analysis_scope="single_client" if normalized_client else "all_clients",
            client_id=normalized_client,
            items=items,
        )
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to list counterparties: {exc}") from exc


@router.post("/strategy/suggest-upload", response_model=StrategySuggestUploadResponse)
def strategy_suggest_upload(
    file: UploadFile = File(...),
    analysis_scope: str = Form("single_client"),
    client_id: str | None = Form(None),
    doc_type: str | None = Form(None),
    counterparty_name: str | None = Form(None),
    contract_value: Decimal | None = Form(None),
    clause_type: str | None = Form(None),
    top_k: int = Form(8),
    max_clauses: int = Form(12),
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> StrategySuggestUploadResponse:
    temp_path: Path | None = None
    file_name = (file.filename or "").strip() or "upload"
    try:
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")
        if max_clauses < 1 or max_clauses > 100:
            raise ValueError("max_clauses must be between 1 and 100")

        suffix = Path(file_name).suffix.lower()
        if suffix not in parser_service.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension: {suffix or '(none)'}. "
                f"Supported: {', '.join(sorted(parser_service.SUPPORTED_EXTENSIONS))}"
            )

        file_bytes = file.file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".txt") as handle:
            handle.write(file_bytes)
            temp_path = Path(handle.name)

        parsed = parser_service.parse(temp_path)
        if parsed.parser_status != "ready":
            raise ValueError(parsed.parse_error or "Failed to parse uploaded file")
        if not parsed.raw_text.strip():
            raise ValueError("Uploaded file produced empty text")

        normalized_upload_text = _normalize_doc_text(parsed.raw_text)
        scope_client_id = client_id.strip() if client_id else None
        doc_match_stmt = select(ContractDocument.raw_text).where(ContractDocument.tenant_id == ctx.tenant_id)
        if scope_client_id:
            doc_match_stmt = doc_match_stmt.where(ContractDocument.client_id == scope_client_id)
        if doc_type and doc_type.strip():
            doc_match_stmt = doc_match_stmt.where(ContractDocument.doc_type == doc_type.strip())
        candidate_docs = ctx.db.execute(doc_match_stmt.limit(500)).scalars().all()
        best_doc_similarity = 0.0
        for existing in candidate_docs:
            normalized_existing = _normalize_doc_text(existing or "")
            similarity = _doc_similarity(normalized_upload_text, normalized_existing)
            if similarity > best_doc_similarity:
                best_doc_similarity = similarity
        is_perfect_document_match = best_doc_similarity >= 0.995

        clauses = [chunk.strip() for chunk in clause_service.segment(parsed.raw_text) if chunk.strip()]
        substantive = [chunk for chunk in clauses if _is_substantive_clause(chunk)]
        selected_clauses = (substantive or clauses)[:max_clauses]
        redline_texts = [
            str(event.get("text") or "").strip()
            for event in parsed.redline_events
            if str(event.get("text") or "").strip()
        ][:max_clauses]
        comment_texts = [
            str(comment.get("text") or "").strip()
            for comment in parsed.comments
            if str(comment.get("text") or "").strip()
        ][:max_clauses]
        if not selected_clauses and not redline_texts and not comment_texts:
            raise ValueError("No analyzable clauses, redlines, or comments found in uploaded document")

        doc_type_weights: dict[str, float] = defaultdict(float)
        doc_type_weight_total = 0.0
        normalized_doc_type = doc_type.strip() if doc_type else _infer_upload_doc_type(file_name, parsed.raw_text)

        def _build_suggestion_rows(source_texts: list[str], source_type: str) -> list[UploadedClauseSuggestion]:
            nonlocal doc_type_weight_total
            rows: list[UploadedClauseSuggestion] = []
            for idx, source_text in enumerate(source_texts):
                request_model = StrategicSuggestionRequest(
                    client_id=client_id.strip() if client_id else None,
                    analysis_scope=analysis_scope,
                    example_source=source_type,
                    doc_type=normalized_doc_type or "GENERAL",
                    counterparty_name=counterparty_name.strip() if counterparty_name else None,
                    contract_value=contract_value,
                    clause_type=clause_type.strip() if clause_type else None,
                    new_clause_text=source_text,
                    top_k=top_k,
                )
                suggestion_data = strategy_service.suggest(ctx.db, ctx.tenant_id, request_model)
                clause_match_type, clause_match_conf = _best_doc_type(suggestion_data.get("retrieved_examples", []))
                if clause_match_type:
                    weight = max(0.0, min(1.0, clause_match_conf))
                    doc_type_weights[clause_match_type] += weight
                    doc_type_weight_total += weight
                rows.append(
                    UploadedClauseSuggestion(
                        clause_index=idx,
                        clause_text=source_text,
                        source_type=source_type,
                        matched_doc_type=clause_match_type,
                        matched_doc_type_confidence=clause_match_conf,
                        suggestion=StrategicSuggestionResponse(**suggestion_data),
                    )
                )
            return rows

        clause_rows = _build_suggestion_rows(selected_clauses, "clause")
        redline_rows = _build_suggestion_rows(redline_texts, "redline")
        comment_rows = _build_suggestion_rows(comment_texts, "comment")

        matched_doc_type: str | None = None
        matched_doc_type_confidence = 0.0
        if doc_type_weights:
            matched_doc_type, matched_weight = max(doc_type_weights.items(), key=lambda item: item[1])
            if doc_type_weight_total > 0:
                matched_doc_type_confidence = round(matched_weight / doc_type_weight_total, 4)

        if is_perfect_document_match:
            response = StrategySuggestUploadResponse(
                file_name=file_name,
                parser_status=parsed.parser_status,
                parse_error=parsed.parse_error,
                analysis_scope=analysis_scope,
                client_id=scope_client_id,
                doc_type=normalized_doc_type,
                matched_doc_type=matched_doc_type or normalized_doc_type,
                matched_doc_type_confidence=1.0,
                counterparty_name=counterparty_name.strip() if counterparty_name else None,
                contract_value=contract_value,
                clause_type=clause_type.strip() if clause_type else None,
                top_k=top_k,
                clauses_total=len(clauses),
                clauses_suggested=0,
                redline_events_detected=len(parsed.redline_events),
                comments_detected=len(parsed.comments),
                perfect_match=True,
                match_confidence=1.0,
                match_message=(
                    "Uploaded document matches learned corpus history for this scope. "
                    "No redlines or suggestions required."
                ),
                clause_suggestions=[],
                redline_suggestions=[],
                comment_suggestions=[],
                suggestions=[],
            )
            audit_service.record(
                ctx.db,
                tenant_id=ctx.tenant_id,
                action="strategy.suggest_upload",
                resource_type="document_upload",
                resource_id=None,
                actor_user_id=ctx.actor.user_id,
                request_id=ctx.request_id,
                ip_address=ctx.ip_address,
                metadata={
                    "file_name": file_name,
                    "analysis_scope": analysis_scope,
                    "client_id": response.client_id,
                    "doc_type": response.doc_type,
                    "matched_doc_type": response.matched_doc_type,
                    "matched_doc_type_confidence": response.matched_doc_type_confidence,
                    "perfect_match": True,
                    "match_confidence": 1.0,
                    "clauses_total": response.clauses_total,
                    "clauses_suggested": response.clauses_suggested,
                    "redline_events_detected": response.redline_events_detected,
                    "comments_detected": response.comments_detected,
                },
            )
            ctx.db.commit()
            return response

        response = StrategySuggestUploadResponse(
            file_name=file_name,
            parser_status=parsed.parser_status,
            parse_error=parsed.parse_error,
            analysis_scope=analysis_scope,
            client_id=client_id.strip() if client_id else None,
            doc_type=normalized_doc_type,
            matched_doc_type=matched_doc_type,
            matched_doc_type_confidence=matched_doc_type_confidence,
            counterparty_name=counterparty_name.strip() if counterparty_name else None,
            contract_value=contract_value,
            clause_type=clause_type.strip() if clause_type else None,
            top_k=top_k,
            clauses_total=len(clauses),
            clauses_suggested=len(selected_clauses),
            redline_events_detected=len(parsed.redline_events),
            comments_detected=len(parsed.comments),
            perfect_match=False,
            match_confidence=round(best_doc_similarity, 4),
            match_message=None,
            clause_suggestions=clause_rows,
            redline_suggestions=redline_rows,
            comment_suggestions=comment_rows,
            suggestions=clause_rows,
        )

        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="strategy.suggest_upload",
            resource_type="document_upload",
            resource_id=None,
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "file_name": file_name,
                "analysis_scope": analysis_scope,
                "client_id": response.client_id,
                "doc_type": response.doc_type,
                "matched_doc_type": response.matched_doc_type,
                "matched_doc_type_confidence": response.matched_doc_type_confidence,
                "counterparty_name": response.counterparty_name,
                "clause_type": response.clause_type,
                "top_k": top_k,
                "clauses_total": response.clauses_total,
                "clauses_suggested": response.clauses_suggested,
                "redline_suggestions": len(response.redline_suggestions),
                "comment_suggestions": len(response.comment_suggestions),
                "redline_events_detected": response.redline_events_detected,
                "comments_detected": response.comments_detected,
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate upload suggestions: {exc}") from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@router.post("/strategy/clause-suggest-upload", response_model=StrategySuggestUploadResponse)
def strategy_clause_suggest_upload(
    file: UploadFile = File(...),
    analysis_scope: str = Form("single_client"),
    client_id: str | None = Form(None),
    doc_type: str | None = Form(None),
    counterparty_name: str | None = Form(None),
    contract_value: Decimal | None = Form(None),
    clause_type: str | None = Form(None),
    top_k: int = Form(6),
    max_clauses: int = Form(6),
    ctx: RequestContext = Depends(require_permission("strategy:read")),
) -> StrategySuggestUploadResponse:
    temp_path: Path | None = None
    file_name = (file.filename or "").strip() or "upload"
    try:
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")
        if max_clauses < 1 or max_clauses > 100:
            raise ValueError("max_clauses must be between 1 and 100")

        suffix = Path(file_name).suffix.lower()
        if suffix not in parser_service.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension: {suffix or '(none)'}. "
                f"Supported: {', '.join(sorted(parser_service.SUPPORTED_EXTENSIONS))}"
            )

        file_bytes = file.file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".txt") as handle:
            handle.write(file_bytes)
            temp_path = Path(handle.name)

        parsed = parser_service.parse(temp_path)
        if parsed.parser_status != "ready":
            raise ValueError(parsed.parse_error or "Failed to parse uploaded file")
        if not parsed.raw_text.strip():
            raise ValueError("Uploaded file produced empty text")

        clauses = [chunk.strip() for chunk in clause_service.segment(parsed.raw_text) if chunk.strip()]
        substantive = [chunk for chunk in clauses if _is_substantive_clause(chunk)]
        selected_clauses = (substantive or clauses)[:max_clauses]
        if not selected_clauses:
            raise ValueError("No analyzable clauses found in uploaded document")

        doc_type_weights: dict[str, float] = defaultdict(float)
        doc_type_weight_total = 0.0
        normalized_doc_type = doc_type.strip() if doc_type else _infer_upload_doc_type(file_name, parsed.raw_text)
        clause_rows: list[UploadedClauseSuggestion] = []
        for idx, source_text in enumerate(selected_clauses):
            request_model = StrategicSuggestionRequest(
                client_id=client_id.strip() if client_id else None,
                analysis_scope=analysis_scope,
                example_source="clause",
                doc_type=normalized_doc_type or "GENERAL",
                counterparty_name=counterparty_name.strip() if counterparty_name else None,
                contract_value=contract_value,
                clause_type=clause_type.strip() if clause_type else None,
                new_clause_text=source_text,
                top_k=top_k,
            )
            suggestion_data = strategy_service.suggest(ctx.db, ctx.tenant_id, request_model)
            clause_match_type, clause_match_conf = _best_doc_type(suggestion_data.get("retrieved_examples", []))
            if clause_match_type:
                weight = max(0.0, min(1.0, clause_match_conf))
                doc_type_weights[clause_match_type] += weight
                doc_type_weight_total += weight
            clause_rows.append(
                UploadedClauseSuggestion(
                    clause_index=idx,
                    clause_text=source_text,
                    source_type="clause",
                    matched_doc_type=clause_match_type,
                    matched_doc_type_confidence=clause_match_conf,
                    suggestion=StrategicSuggestionResponse(**suggestion_data),
                )
            )

        matched_doc_type: str | None = None
        matched_doc_type_confidence = 0.0
        if doc_type_weights:
            matched_doc_type, matched_weight = max(doc_type_weights.items(), key=lambda item: item[1])
            if doc_type_weight_total > 0:
                matched_doc_type_confidence = round(matched_weight / doc_type_weight_total, 4)

        response = StrategySuggestUploadResponse(
            file_name=file_name,
            parser_status=parsed.parser_status,
            parse_error=parsed.parse_error,
            analysis_scope=analysis_scope,
            client_id=client_id.strip() if client_id else None,
            doc_type=normalized_doc_type,
            matched_doc_type=matched_doc_type,
            matched_doc_type_confidence=matched_doc_type_confidence,
            counterparty_name=counterparty_name.strip() if counterparty_name else None,
            contract_value=contract_value,
            clause_type=clause_type.strip() if clause_type else None,
            top_k=top_k,
            clauses_total=len(clauses),
            clauses_suggested=len(selected_clauses),
            redline_events_detected=len(parsed.redline_events),
            comments_detected=len(parsed.comments),
            perfect_match=False,
            match_confidence=0.0,
            match_message=None,
            clause_suggestions=clause_rows,
            redline_suggestions=[],
            comment_suggestions=[],
            suggestions=clause_rows,
        )
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="strategy.clause_suggest_upload",
            resource_type="document_upload",
            resource_id=None,
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "file_name": file_name,
                "analysis_scope": analysis_scope,
                "client_id": response.client_id,
                "doc_type": response.doc_type,
                "matched_doc_type": response.matched_doc_type,
                "clauses_suggested": response.clauses_suggested,
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate clause suggestions: {exc}") from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
