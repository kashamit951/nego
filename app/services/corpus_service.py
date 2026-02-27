from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import ClauseRecord, CorpusFile, CorpusSource, NegotiationOutcome
from app.schemas.contracts import IngestDocumentRequest
from app.schemas.corpus import (
    CorpusFileRecord,
    CorpusLearnFileResult,
    CorpusLearnRequest,
    CorpusLearnResponse,
    CorpusScanRequest,
    CorpusScanResponse,
    CorpusScanSummary,
    CorpusSourceStatus,
    CorpusStatusResponse,
)
from app.services.corpus_parser import CorpusParserService
from app.services.document_service import DocumentIngestionService


@dataclass(slots=True)
class ScanOutcome:
    source: CorpusSource
    summary: CorpusScanSummary
    files: list[CorpusFileRecord]


@dataclass(slots=True)
class CommentSignalRules:
    profile: str
    accept_phrases: tuple[str, ...]
    reject_phrases: tuple[str, ...]
    revise_phrases: tuple[str, ...]


class CorpusManagementService:
    DEFAULT_EXTENSIONS = {".txt", ".md", ".docx", ".pdf", ".rtf"}

    def __init__(
        self,
        settings,
        ingestion_service: DocumentIngestionService,
        parser_service: CorpusParserService,
        llm_provider=None,
    ) -> None:
        self.settings = settings
        self.ingestion_service = ingestion_service
        self.parser_service = parser_service
        self.llm_provider = llm_provider

    def scan(self, db: Session, tenant_id: str, request: CorpusScanRequest) -> CorpusScanResponse:
        outcome = self._scan_internal(db, tenant_id, request)
        return CorpusScanResponse(
            source_id=outcome.source.id,
            client_id=outcome.source.client_id,
            source_path=outcome.source.source_path,
            source_label=outcome.source.source_label,
            scanned_at=outcome.source.last_scanned_at or datetime.now(timezone.utc),
            summary=outcome.summary,
            files=outcome.files,
        )

    def learn(self, db: Session, tenant_id: str, request: CorpusLearnRequest) -> CorpusLearnResponse:
        client_id = self._normalize_client_id(request.client_id)
        scan_request = CorpusScanRequest(
            client_id=client_id,
            source_path=request.source_path,
            source_label=request.source_label,
            include_subdirectories=request.include_subdirectories,
            max_files=request.max_files,
            file_extensions=request.file_extensions,
        )
        scan_outcome = self._scan_internal(db, tenant_id, scan_request)
        source = scan_outcome.source

        rows = db.execute(
            select(CorpusFile).where(
                and_(
                    CorpusFile.tenant_id == tenant_id,
                    CorpusFile.client_id == source.client_id,
                    CorpusFile.source_id == source.id,
                    CorpusFile.is_missing.is_(False),
                )
            )
        ).scalars().all()

        now = datetime.now(timezone.utc)
        learned_documents = 0
        skipped_unchanged = 0
        failed_files = 0
        parsed_redlines = 0
        parsed_comments = 0
        file_results: list[CorpusLearnFileResult] = []
        comment_rules = self._build_comment_rules(request)

        for row in sorted(rows, key=lambda r: r.relative_path):
            changed_or_new = row.learned_hash_sha256 != row.file_hash_sha256 or row.last_learned_at is None
            if request.mode == "new_or_changed" and not changed_or_new:
                skipped_unchanged += 1
                file_results.append(
                    CorpusLearnFileResult(
                        file_id=row.id,
                        relative_path=row.relative_path,
                        action="skipped_unchanged",
                    )
                )
                continue

            parsed = self.parser_service.parse(Path(row.absolute_path))
            redline_count = len(parsed.redline_events)
            comment_count = len(parsed.comments)
            parsed_redlines += redline_count
            parsed_comments += comment_count

            if parsed.parser_status != "ready":
                failed_files += 1
                row.parser_status = parsed.parser_status
                row.parse_error = parsed.parse_error
                row.redline_summary = {"count": redline_count}
                row.comments_summary = parsed.comments[:100]
                row.metadata_json = {
                    **(row.metadata_json or {}),
                    "last_parse_error": parsed.parse_error,
                    "last_parse_status": parsed.parser_status,
                }
                file_results.append(
                    CorpusLearnFileResult(
                        file_id=row.id,
                        relative_path=row.relative_path,
                        action="failed",
                        error=parsed.parse_error or "Parser failed",
                        redlines_detected=redline_count,
                        comments_detected=comment_count,
                    )
                )
                continue

            if not parsed.raw_text.strip():
                failed_files += 1
                row.parser_status = "error"
                row.parse_error = "Parser returned empty text"
                row.redline_summary = {"count": redline_count}
                row.comments_summary = parsed.comments[:100]
                file_results.append(
                    CorpusLearnFileResult(
                        file_id=row.id,
                        relative_path=row.relative_path,
                        action="failed",
                        error="Empty text extracted from corpus file",
                        redlines_detected=redline_count,
                        comments_detected=comment_count,
                    )
                )
                continue

            inferred_doc_type = self._infer_doc_type(row.relative_path, parsed.raw_text)
            doc_type = self._resolve_doc_type(request.default_doc_type, inferred_doc_type)
            metadata = {
                "corpus": {
                    "source_id": str(source.id),
                    "client_id": source.client_id,
                    "source_path": source.source_path,
                    "relative_path": row.relative_path,
                    "absolute_path": row.absolute_path,
                    "hash_sha256": row.file_hash_sha256,
                    "learned_at": now.isoformat(),
                },
                "redline_event_count": redline_count,
                "redline_events_preview": parsed.redline_events[:50],
                "comment_count": comment_count,
                "comments_preview": parsed.comments[:50],
            }

            try:
                document_id, clauses_ingested = self.ingestion_service.ingest_document(
                    db,
                    tenant_id,
                    IngestDocumentRequest(
                        client_id=source.client_id,
                        doc_type=doc_type,
                        counterparty_name=request.counterparty_name,
                        contract_value=request.contract_value,
                        raw_text=parsed.raw_text,
                        metadata=metadata,
                    ),
                )
                row.document_id = document_id
                row.parser_status = "ready"
                row.parse_error = None
                row.redline_summary = {
                    "count": redline_count,
                    "events": parsed.redline_events[:200],
                }
                row.comments_summary = parsed.comments[:200]
                row.learned_hash_sha256 = row.file_hash_sha256
                row.last_learned_at = now
                row.metadata_json = {
                    **(row.metadata_json or {}),
                    "client_id": source.client_id,
                    "doc_type": doc_type,
                    "counterparty_name": request.counterparty_name,
                    "contract_value": float(request.contract_value) if request.contract_value else None,
                }

                has_redline_events = bool(parsed.redline_events)
                has_comments = bool(parsed.comments)
                should_create_from_redlines = request.create_outcomes_from_redlines and has_redline_events
                should_create_from_comments = request.create_outcomes_from_comments and has_comments
                should_create_from_clean_final = not has_redline_events and not has_comments
                if has_redline_events or has_comments:
                    self._upsert_negotiation_signals(
                        db=db,
                        tenant_id=tenant_id,
                        client_id=source.client_id,
                        document_id=document_id,
                        source_path=row.relative_path,
                        raw_text=parsed.raw_text,
                        doc_type=doc_type,
                        counterparty_name=request.counterparty_name,
                        contract_value=request.contract_value,
                        redline_events=parsed.redline_events,
                        comments=parsed.comments,
                        comment_rules=comment_rules,
                        comment_signal_engine=request.comment_signal_engine,
                    )
                if should_create_from_redlines or should_create_from_comments or should_create_from_clean_final:
                    self._record_synthetic_outcome(
                        db,
                        tenant_id=tenant_id,
                        client_id=source.client_id,
                        document_id=document_id,
                        doc_type=doc_type,
                        source_path=row.relative_path,
                        raw_text=parsed.raw_text,
                        redline_events=parsed.redline_events,
                        comments=parsed.comments,
                        comment_rules=comment_rules,
                        comment_signal_engine=request.comment_signal_engine,
                    )

                learned_documents += 1
                file_results.append(
                    CorpusLearnFileResult(
                        file_id=row.id,
                        relative_path=row.relative_path,
                        action="learned",
                        document_id=document_id,
                        clauses_ingested=clauses_ingested,
                        redlines_detected=redline_count,
                        comments_detected=comment_count,
                    )
                )
            except Exception as exc:
                failed_files += 1
                row.parser_status = "error"
                row.parse_error = f"Ingestion failed: {exc}"
                file_results.append(
                    CorpusLearnFileResult(
                        file_id=row.id,
                        relative_path=row.relative_path,
                        action="failed",
                        error=str(exc),
                        redlines_detected=redline_count,
                        comments_detected=comment_count,
                    )
                )

        if learned_documents > 0:
            source.last_learned_at = now
        db.flush()

        return CorpusLearnResponse(
            source_id=source.id,
            client_id=source.client_id,
            source_path=source.source_path,
            learned_documents=learned_documents,
            skipped_unchanged=skipped_unchanged,
            failed_files=failed_files,
            parsed_redlines=parsed_redlines,
            parsed_comments=parsed_comments,
            files=file_results,
        )

    def update(self, db: Session, tenant_id: str, request: CorpusLearnRequest) -> CorpusLearnResponse:
        effective = request.model_copy(update={"mode": "new_or_changed"})
        return self.learn(db, tenant_id, effective)

    def status(
        self,
        db: Session,
        tenant_id: str,
        source_path: str | None = None,
        client_id: str | None = None,
    ) -> CorpusStatusResponse:
        stmt = select(CorpusSource).where(CorpusSource.tenant_id == tenant_id)
        if client_id:
            stmt = stmt.where(CorpusSource.client_id == self._normalize_client_id(client_id))
        if source_path:
            normalized = str(self._resolve_source_path(source_path))
            stmt = stmt.where(CorpusSource.source_path == normalized)

        sources = db.execute(stmt.order_by(CorpusSource.created_at.desc())).scalars().all()

        items: list[CorpusSourceStatus] = []
        for source in sources:
            rows = db.execute(
                select(CorpusFile).where(
                    and_(
                        CorpusFile.tenant_id == tenant_id,
                        CorpusFile.client_id == source.client_id,
                        CorpusFile.source_id == source.id,
                    )
                )
            ).scalars().all()

            total_files = len(rows)
            missing_files = sum(1 for row in rows if row.is_missing)
            error_files = sum(1 for row in rows if row.parser_status == "error")
            changed_files = sum(
                1
                for row in rows
                if not row.is_missing
                and row.last_learned_at is not None
                and row.learned_hash_sha256 != row.file_hash_sha256
            )
            pending_files = sum(
                1
                for row in rows
                if not row.is_missing
                and (row.last_learned_at is None or row.learned_hash_sha256 != row.file_hash_sha256)
            )
            learned_files = sum(
                1
                for row in rows
                if not row.is_missing and row.last_learned_at is not None and row.learned_hash_sha256 == row.file_hash_sha256
            )

            items.append(
                CorpusSourceStatus(
                    source_id=source.id,
                    client_id=source.client_id,
                    source_path=source.source_path,
                    source_label=source.source_label,
                    include_subdirectories=source.include_subdirectories,
                    last_scanned_at=source.last_scanned_at,
                    last_learned_at=source.last_learned_at,
                    total_files=total_files,
                    learned_files=learned_files,
                    changed_files=changed_files,
                    pending_files=pending_files,
                    missing_files=missing_files,
                    error_files=error_files,
                )
            )

        return CorpusStatusResponse(sources=items)

    def _scan_internal(self, db: Session, tenant_id: str, request: CorpusScanRequest) -> ScanOutcome:
        client_id = self._normalize_client_id(request.client_id)
        root = self._resolve_source_path(request.source_path)
        include_subdirectories = request.include_subdirectories
        extensions = self._normalize_extensions(request.file_extensions)

        source = self._get_or_create_source(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            source_path=str(root),
            source_label=request.source_label,
            include_subdirectories=include_subdirectories,
        )

        existing_rows = db.execute(
            select(CorpusFile).where(
                and_(
                    CorpusFile.tenant_id == tenant_id,
                    CorpusFile.client_id == source.client_id,
                    CorpusFile.source_id == source.id,
                )
            )
        ).scalars().all()
        by_relative = {row.relative_path: row for row in existing_rows}

        now = datetime.now(timezone.utc)
        files = self._list_files(
            root,
            include_subdirectories=include_subdirectories,
            extensions=extensions,
            max_files=min(request.max_files, self.settings.corpus_max_scan_files),
        )

        records: list[CorpusFileRecord] = []
        seen_relatives: set[str] = set()
        new_count = 0
        changed_count = 0
        unchanged_count = 0
        missing_count = 0

        for path in files:
            try:
                file_size = path.stat().st_size
                file_hash = self._sha256(path)
            except Exception:
                continue

            relative_path = str(path.relative_to(root))
            seen_relatives.add(relative_path)
            extension = path.suffix.lower()
            row = by_relative.get(relative_path)
            change_status = "unchanged"

            if row is None:
                row = CorpusFile(
                    tenant_id=tenant_id,
                    client_id=source.client_id,
                    source_id=source.id,
                    relative_path=relative_path,
                    absolute_path=str(path),
                    file_extension=extension,
                    file_size_bytes=file_size,
                    file_hash_sha256=file_hash,
                    learned_hash_sha256=None,
                    parser_status="pending",
                    parse_error=None,
                    redline_summary={},
                    comments_summary=[],
                    metadata_json={},
                    is_missing=False,
                    last_seen_at=now,
                )
                db.add(row)
                by_relative[relative_path] = row
                new_count += 1
                change_status = "new"
            else:
                if row.file_hash_sha256 != file_hash:
                    change_status = "changed"
                    changed_count += 1
                    row.parser_status = "pending"
                    row.parse_error = None
                else:
                    unchanged_count += 1
                    change_status = "unchanged"

                row.absolute_path = str(path)
                row.client_id = source.client_id
                row.file_extension = extension
                row.file_size_bytes = file_size
                row.file_hash_sha256 = file_hash
                row.last_seen_at = now
                row.is_missing = False

            records.append(self._file_record_from_row(row, change_status))

        for relative_path, row in by_relative.items():
            if relative_path in seen_relatives:
                continue
            row.is_missing = True
            missing_count += 1
            records.append(self._file_record_from_row(row, "missing"))

        source.last_scanned_at = now
        source.source_label = request.source_label or source.source_label
        source.include_subdirectories = include_subdirectories

        learned_count = sum(
            1
            for row in by_relative.values()
            if not row.is_missing
            and row.last_learned_at is not None
            and row.learned_hash_sha256 == row.file_hash_sha256
        )
        pending_count = sum(
            1
            for row in by_relative.values()
            if not row.is_missing
            and (row.last_learned_at is None or row.learned_hash_sha256 != row.file_hash_sha256)
        )

        records.sort(key=lambda item: item.relative_path)
        summary = CorpusScanSummary(
            total_found=len(files),
            new_count=new_count,
            changed_count=changed_count,
            unchanged_count=unchanged_count,
            missing_count=missing_count,
            learned_count=learned_count,
            pending_count=pending_count,
        )
        db.flush()
        return ScanOutcome(source=source, summary=summary, files=records)

    def _get_or_create_source(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str,
        source_path: str,
        source_label: str | None,
        include_subdirectories: bool,
    ) -> CorpusSource:
        source = db.execute(
            select(CorpusSource).where(
                and_(
                    CorpusSource.tenant_id == tenant_id,
                    CorpusSource.client_id == client_id,
                    CorpusSource.source_path == source_path,
                )
            )
        ).scalar_one_or_none()

        if source is None:
            source = CorpusSource(
                tenant_id=tenant_id,
                client_id=client_id,
                source_path=source_path,
                source_label=source_label,
                include_subdirectories=include_subdirectories,
            )
            db.add(source)
            db.flush()
        return source

    def _resolve_source_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Source path does not exist or is not a directory: {path}")

        allowed_roots = self._allowed_roots()
        if allowed_roots and not any(self._is_subpath(path, root) for root in allowed_roots):
            roots = ", ".join(str(root) for root in allowed_roots)
            raise ValueError(f"Source path {path} is outside allowed roots: {roots}")

        return path

    def _allowed_roots(self) -> list[Path]:
        raw = self.settings.corpus_allowed_roots
        if not raw:
            return []
        roots = []
        for part in raw.split(","):
            clean = part.strip()
            if not clean:
                continue
            roots.append(Path(clean).expanduser().resolve())
        return roots

    @staticmethod
    def _normalize_client_id(raw_client_id: str) -> str:
        client_id = raw_client_id.strip()
        if not client_id:
            raise ValueError("client_id cannot be empty")
        return client_id

    @staticmethod
    def _is_subpath(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _list_files(
        self,
        root: Path,
        *,
        include_subdirectories: bool,
        extensions: set[str],
        max_files: int,
    ) -> list[Path]:
        iterator = root.rglob("*") if include_subdirectories else root.glob("*")
        files = [p.resolve() for p in iterator if p.is_file() and p.suffix.lower() in extensions]
        files.sort()
        return files[:max_files]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _normalize_extensions(self, extensions: list[str]) -> set[str]:
        if not extensions:
            return set(self.DEFAULT_EXTENSIONS)

        normalized: set[str] = set()
        for ext in extensions:
            clean = ext.strip().lower()
            if not clean:
                continue
            if not clean.startswith("."):
                clean = f".{clean}"
            normalized.add(clean)

        return normalized or set(self.DEFAULT_EXTENSIONS)

    @staticmethod
    def _infer_doc_type(relative_path: str, raw_text: str) -> str:
        joined = f"{relative_path} {raw_text[:800]}".lower()
        if any(token in joined for token in ["master service agreement", " msa ", "_msa", "-msa"]):
            return "MSA"
        if any(token in joined for token in ["statement of work", " sow ", "_sow", "-sow"]):
            return "SOW"
        if any(token in joined for token in ["non-disclosure", " nda ", "_nda", "-nda"]):
            return "NDA"
        if "order form" in joined or "purchase order" in joined:
            return "ORDER_FORM"

        # Keep PO detection conservative to avoid matching unrelated words.
        normalized_path = relative_path.lower()
        if re.search(r"(^|[/_\-\s])po([/_\-\s]|$)", normalized_path):
            return "ORDER_FORM"
        return "GENERAL"

    @staticmethod
    def _resolve_doc_type(default_doc_type: str | None, inferred_doc_type: str) -> str:
        if default_doc_type is None:
            return inferred_doc_type
        cleaned = default_doc_type.strip().upper()
        # Treat blank/GENERAL as "auto" so filename/text inference can still work.
        if not cleaned or cleaned == "GENERAL":
            return inferred_doc_type
        return cleaned

    @staticmethod
    def _file_record_from_row(row: CorpusFile, change_status: str) -> CorpusFileRecord:
        redline_count = int((row.redline_summary or {}).get("count", 0))
        comments_count = len(row.comments_summary or [])
        learned = row.last_learned_at is not None and row.learned_hash_sha256 == row.file_hash_sha256
        return CorpusFileRecord(
            file_id=row.id,
            client_id=row.client_id,
            relative_path=row.relative_path,
            absolute_path=row.absolute_path,
            extension=row.file_extension,
            size_bytes=int(row.file_size_bytes),
            hash_sha256=row.file_hash_sha256,
            change_status=change_status,
            parser_status=row.parser_status,
            parse_error=row.parse_error,
            learned=learned,
            last_learned_at=row.last_learned_at,
            redline_count=redline_count,
            comments_count=comments_count,
            document_id=row.document_id,
        )

    def _record_synthetic_outcome(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str,
        document_id,
        doc_type: str,
        source_path: str,
        raw_text: str,
        redline_events: list[dict],
        comments: list[dict],
        comment_rules: CommentSignalRules,
        comment_signal_engine: str,
    ) -> None:
        insertions = sum(1 for event in redline_events if event.get("type") == "insertion")
        deletions = sum(1 for event in redline_events if event.get("type") == "deletion")
        comment_texts = self._extract_comment_texts(comments)
        comment_signals = self._analyze_comment_signals(
            comment_texts,
            comment_rules,
            comment_signal_engine=comment_signal_engine,
        )
        inferred_outcome = self._infer_outcome_from_signals(
            insertions=insertions,
            deletions=deletions,
            comment_signals=comment_signals,
            comment_rules=comment_rules,
        )
        response = (
            f"Extracted negotiation signals from corpus file {source_path}: "
            f"redlines +{insertions} / -{deletions}, comments={len(comment_texts)}, "
            f"profile={comment_rules.profile}, "
            f"comment_accept={comment_signals['accept']}, "
            f"comment_reject={comment_signals['reject']}, "
            f"comment_revise={comment_signals['revise']}"
        )
        client_response = self._build_synthetic_client_response(
            comment_texts=comment_texts,
            comment_signals=comment_signals,
            profile=comment_rules.profile,
        )
        structured_comment_events = [
            {
                "type": "comment",
                "source": "comment",
                "signal": self._comment_signal(
                    text,
                    comment_rules,
                    comment_signal_engine=comment_signal_engine,
                ),
                "text": text[:1000],
                "profile": comment_rules.profile,
            }
            for text in comment_texts[:50]
        ]

        row = NegotiationOutcome(
            tenant_id=tenant_id,
            client_id=client_id,
            document_id=document_id,
            clause_id=None,
            doc_type=doc_type,
            clause_type="other",
            counterparty_name=None,
            deal_size=Decimal("0"),
            original_text=raw_text[:10000],
            counterparty_edit=response,
            client_response=client_response,
            final_text=raw_text[:10000],
            outcome=inferred_outcome,
            negotiation_rounds=max(
                1,
                min(
                    6,
                    insertions + deletions + comment_signals["reject"] + comment_signals["revise"],
                ),
            ),
            won_by="mutual",
            redline_events=(redline_events[:150] + structured_comment_events)[:200],
        )
        db.add(row)
        db.flush()

    @staticmethod
    def _extract_comment_texts(comments: list[dict]) -> list[str]:
        texts: list[str] = []
        for comment in comments:
            text = comment.get("text")
            if isinstance(text, str):
                clean = text.strip()
                if clean:
                    texts.append(clean)
        return texts

    def _analyze_comment_signals(
        self,
        comment_texts: list[str],
        comment_rules: CommentSignalRules,
        *,
        comment_signal_engine: str,
    ) -> dict[str, int]:
        counts = {"accept": 0, "reject": 0, "revise": 0}
        llm_cache: dict[str, str] = {}
        for text in comment_texts:
            cache_key = text.strip().lower()
            if cache_key in llm_cache:
                signal = llm_cache[cache_key]
            else:
                signal = self._comment_signal(
                    text,
                    comment_rules,
                    comment_signal_engine=comment_signal_engine,
                )
                llm_cache[cache_key] = signal
            if signal in counts:
                counts[signal] += 1
        return counts

    def _comment_signal(
        self,
        text: str,
        comment_rules: CommentSignalRules,
        *,
        comment_signal_engine: str,
    ) -> str:
        if comment_signal_engine == "llm" and self.llm_provider is not None:
            try:
                result = self.llm_provider.classify_comment_signal(
                    comment_text=text,
                    profile=comment_rules.profile,
                )
                signal = str(result.get("signal") or "neutral").strip().lower()
                if signal in {"accept", "reject", "revise", "neutral"}:
                    return signal
            except Exception:
                pass
        lowered = text.lower()
        if CorpusManagementService._matches_any_phrase(lowered, comment_rules.reject_phrases):
            return "reject"
        if CorpusManagementService._matches_any_phrase(lowered, comment_rules.accept_phrases):
            return "accept"
        if CorpusManagementService._matches_any_phrase(lowered, comment_rules.revise_phrases):
            return "revise"
        return "neutral"

    @staticmethod
    def _infer_outcome_from_signals(
        *,
        insertions: int,
        deletions: int,
        comment_signals: dict[str, int],
        comment_rules: CommentSignalRules,
    ) -> str:
        if insertions == 0 and deletions == 0 and sum(comment_signals.values()) == 0:
            # In corpus progression, a clean final document with no further redlines/comments
            # is treated as accepted precedent.
            return "accepted"

        if comment_rules.profile == "strict":
            if comment_signals["reject"] > 0:
                return "rejected"
            if comment_signals["accept"] > 0 and comment_signals["revise"] == 0 and deletions == 0:
                return "accepted"
            return "partially_accepted"

        if comment_rules.profile == "lenient":
            if comment_signals["reject"] >= max(2, comment_signals["accept"] + 2):
                return "rejected"
            if comment_signals["accept"] >= comment_signals["reject"] and comment_signals["revise"] <= 2:
                return "accepted"
            return "partially_accepted"

        # balanced
        if comment_signals["reject"] > comment_signals["accept"] and comment_signals["reject"] >= 1:
            return "rejected"
        if (
            comment_signals["accept"] > 0
            and comment_signals["reject"] == 0
            and comment_signals["revise"] <= 1
            and deletions == 0
        ):
            return "accepted"
        return "partially_accepted"

    def _build_comment_rules(self, request: CorpusLearnRequest) -> CommentSignalRules:
        base_accept = (
            "accept",
            "accepted",
            "acceptable",
            "approve",
            "approved",
            "agree",
            "agreed",
            "looks good",
            "works for us",
            "no objection",
        )
        base_reject = (
            "reject",
            "rejected",
            "not acceptable",
            "cannot accept",
            "can't accept",
            "unacceptable",
            "decline",
            "deal breaker",
            "must remove",
            "strike this",
            "remove this",
        )
        base_revise = (
            "revise",
            "reword",
            "change",
            "update",
            "counter",
            "instead",
            "suggest",
            "replace with",
            "subject to",
            "provided that",
            "cap",
            "limit",
            "mutual",
            "carve-out",
        )

        return CommentSignalRules(
            profile=request.comment_rule_profile,
            accept_phrases=self._merge_phrase_sets(base_accept, request.comment_accept_phrases),
            reject_phrases=self._merge_phrase_sets(base_reject, request.comment_reject_phrases),
            revise_phrases=self._merge_phrase_sets(base_revise, request.comment_revise_phrases),
        )

    @staticmethod
    def _merge_phrase_sets(base_phrases: tuple[str, ...], custom_phrases: list[str]) -> tuple[str, ...]:
        merged = {item.strip().lower() for item in base_phrases if item.strip()}
        for item in custom_phrases:
            clean = item.strip().lower()
            if clean:
                merged.add(clean)
        return tuple(sorted(merged))

    @staticmethod
    def _matches_any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _build_synthetic_client_response(
        *,
        comment_texts: list[str],
        comment_signals: dict[str, int],
        profile: str,
    ) -> str:
        summary = (
            "Synthetic outcome generated from parsed redlines/comments. "
            f"profile={profile}. "
            f"Comment signals: accept={comment_signals['accept']}, "
            f"reject={comment_signals['reject']}, revise={comment_signals['revise']}."
        )
        if not comment_texts:
            return summary
        preview = " | ".join(comment_texts[:3])
        return f"{summary} Top comment excerpts: {preview[:1200]}"

    def _upsert_negotiation_signals(
        self,
        *,
        db: Session,
        tenant_id: str,
        client_id: str,
        document_id,
        source_path: str,
        raw_text: str,
        doc_type: str,
        counterparty_name: str | None,
        contract_value: Decimal | None,
        redline_events: list[dict],
        comments: list[dict],
        comment_rules: CommentSignalRules,
        comment_signal_engine: str,
    ) -> None:
        anchors = self._document_clause_anchors(db, tenant_id=tenant_id, document_id=document_id)
        if not anchors:
            anchors = self._fallback_anchors_from_raw_text(raw_text)
        signal_cache: dict[str, str] = {}

        for event_index, event in enumerate(redline_events):
            raw_text = str(event.get("text") or "").strip()
            paragraph_text = str(event.get("paragraph_text") or "").strip()
            if not raw_text and not paragraph_text:
                continue
            event_type = str(event.get("type") or "redline").strip().lower()
            linked_comment_text = self._resolve_event_linked_comment_text(
                event=event,
                comments=comments,
                event_index=event_index,
            )
            signal_text = self._build_redline_signal_text(
                raw_text=raw_text,
                paragraph_text=paragraph_text,
                event_type=event_type,
            )
            comment_signal = (
                signal_cache.get(linked_comment_text.strip().lower())
                if linked_comment_text
                else None
            )
            if linked_comment_text and comment_signal is None:
                comment_signal = self._comment_signal(
                    linked_comment_text,
                    comment_rules,
                    comment_signal_engine=comment_signal_engine,
                )
                signal_cache[linked_comment_text.strip().lower()] = comment_signal
            anchor_basis = f"{signal_text} {paragraph_text}".strip() if paragraph_text else signal_text
            anchor = self._match_anchor_clause(anchor_basis, anchors)
            anchor_clause_type = str(anchor.get("clause_type") or "").strip()
            clause_type = anchor_clause_type if self._is_actionable_clause_type(anchor_clause_type) else "other"
            anchor_text = str(anchor.get("clause_text") or "")
            before_text = paragraph_text if (event_type == "deletion" and paragraph_text) else (anchor_text if event_type == "deletion" else "")
            after_text = paragraph_text if (event_type == "insertion" and paragraph_text) else (anchor_text if event_type == "insertion" else "")
            combined_text = self._compose_signal_embedding_text(
                source_type="redline",
                signal_text=signal_text,
                anchor_clause_text=anchor_text,
                redline_before_text=before_text,
                redline_after_text=after_text,
                comment_signal=comment_signal,
                linked_comment_text=linked_comment_text,
                signal_context_text=paragraph_text,
            )
            vector = self.ingestion_service.clause_service.embed(combined_text)
            self.ingestion_service.vector_store.upsert_clause(
                tenant_id=tenant_id,
                point_id=str(uuid4()),
                vector=vector,
                payload={
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "clause_type": clause_type,
                    "doc_type": doc_type,
                    "counterparty_name": counterparty_name,
                    "contract_value": float(contract_value or 0),
                    "text": combined_text,
                    "source_text": signal_text,
                    "raw_signal_text": raw_text or None,
                    "source_type": "redline",
                    "redline_type": event_type,
                    "source_path": source_path,
                    "document_id": str(document_id),
                    "clause_id": anchor.get("clause_id"),
                    "clause_index": anchor.get("clause_index"),
                    "clause_anchor_score": anchor.get("score"),
                    "anchor_clause_text": anchor_text,
                    "source_context_text": paragraph_text or None,
                    "redline_before_text": before_text or None,
                    "redline_after_text": after_text or None,
                    "comment_signal": comment_signal,
                    "linked_comment_text": linked_comment_text or None,
                    "round_number": 1,
                    "outcome": None,
                    "time_to_resolution_days": None,
                    "is_clause": False,
                    "is_redline": True,
                    "is_comment": False,
                },
            )

    @staticmethod
    def _compose_signal_embedding_text(
        *,
        source_type: str,
        signal_text: str,
        anchor_clause_text: str | None,
        redline_before_text: str | None,
        redline_after_text: str | None,
        comment_signal: str | None,
        linked_comment_text: str | None,
        signal_context_text: str | None = None,
    ) -> str:
        parts = [f"source_type={source_type}", f"signal_text={signal_text.strip()}"]
        if signal_context_text:
            parts.append(f"signal_context={signal_context_text.strip()[:500]}")
        if anchor_clause_text:
            parts.append(f"anchor_clause={anchor_clause_text.strip()}")
        if redline_before_text:
            parts.append(f"redline_before={redline_before_text.strip()}")
        if redline_after_text:
            parts.append(f"redline_after={redline_after_text.strip()}")
        if comment_signal:
            parts.append(f"comment_signal={comment_signal.strip().lower()}")
        if linked_comment_text:
            parts.append(f"linked_comment={linked_comment_text.strip()[:300]}")
        return " | ".join(parts)

    @staticmethod
    def _resolve_event_linked_comment_text(*, event: dict, comments: list[dict], event_index: int) -> str:
        direct = str(
            event.get("comment_text")
            or event.get("linked_comment_text")
            or ""
        ).strip()
        if direct:
            return direct

        comment_ids = [str(cid).strip() for cid in (event.get("comment_ids") or []) if str(cid).strip()]
        if comment_ids:
            by_id = {
                str(row.get("id")).strip(): str(row.get("text") or "").strip()
                for row in comments
                if row.get("id") is not None and str(row.get("text") or "").strip()
            }
            linked = [by_id[cid] for cid in comment_ids if cid in by_id]
            if linked:
                return " ".join(linked).strip()
            return f"Comment attached in document (id: {', '.join(comment_ids[:3])})"

        event_pos = event.get("position")
        if event_pos is not None:
            try:
                event_pos_int = int(event_pos)
            except Exception:
                event_pos_int = None
            if event_pos_int is not None:
                nearest_text = ""
                nearest_distance = None
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

        if 0 <= event_index < len(comments):
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
        return ""

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}

    def _document_clause_anchors(self, db: Session, *, tenant_id: str, document_id) -> list[dict]:
        rows = db.execute(
            select(ClauseRecord).where(
                and_(
                    ClauseRecord.tenant_id == tenant_id,
                    ClauseRecord.document_id == document_id,
                )
            )
        ).scalars().all()
        anchors: list[dict] = []
        for row in rows:
            anchors.append(
                {
                    "clause_id": str(row.id),
                    "clause_index": int(row.clause_index),
                    "clause_text": row.clause_text,
                    "clause_type": row.clause_type,
                    "tokens": self._tokenize(row.clause_text),
                }
            )
        return anchors

    def _fallback_anchors_from_raw_text(self, raw_text: str) -> list[dict]:
        anchors: list[dict] = []
        segments = [chunk.strip() for chunk in self.ingestion_service.clause_service.segment(raw_text) if chunk.strip()]
        for idx, text in enumerate(segments[:40]):
            anchors.append(
                {
                    "clause_id": None,
                    "clause_index": idx,
                    "clause_text": text,
                    "clause_type": None,
                    "tokens": self._tokenize(text),
                }
            )
        if not anchors and raw_text.strip():
            text = raw_text.strip()[:1200]
            anchors.append(
                {
                    "clause_id": None,
                    "clause_index": 0,
                    "clause_text": text,
                    "clause_type": None,
                    "tokens": self._tokenize(text),
                }
            )
        return anchors

    def _match_anchor_clause(self, signal_text: str, anchors: list[dict]) -> dict:
        if not anchors:
            return {"clause_id": None, "clause_index": None, "clause_text": "", "clause_type": None, "score": 0.0}

        signal_tokens = self._tokenize(signal_text)
        if not signal_tokens:
            best = anchors[0]
            return {
                "clause_id": best.get("clause_id"),
                "clause_index": best.get("clause_index"),
                "clause_text": best.get("clause_text", ""),
                "clause_type": best.get("clause_type"),
                "score": 0.0,
            }

        best_anchor = anchors[0]
        best_score = -1.0
        for anchor in anchors:
            anchor_tokens = anchor.get("tokens") or set()
            if not anchor_tokens:
                score = 0.0
            else:
                overlap = len(signal_tokens.intersection(anchor_tokens))
                score = overlap / max(len(signal_tokens), 1)
            if score > best_score:
                best_score = score
                best_anchor = anchor

        return {
            "clause_id": best_anchor.get("clause_id"),
            "clause_index": best_anchor.get("clause_index"),
            "clause_text": best_anchor.get("clause_text", ""),
            "clause_type": best_anchor.get("clause_type"),
            "score": max(0.0, float(best_score)),
        }

    @staticmethod
    def _is_actionable_clause_type(value: str | None) -> bool:
        key = (value or "").strip().lower()
        return bool(key and key != "other" and not key.startswith("redline_"))

    def _match_related_redline(self, *, text: str, anchor_text: str, redline_events: list[dict]) -> dict:
        candidates = []
        basis_tokens = self._tokenize(f"{text} {anchor_text}")
        for event in redline_events:
            redline_text = str(event.get("text") or "").strip()
            if not redline_text:
                continue
            tokens = self._tokenize(redline_text)
            overlap = len(tokens.intersection(basis_tokens))
            score = overlap / max(len(tokens), 1)
            candidates.append(
                {
                    "text": redline_text,
                    "type": str(event.get("type") or "redline"),
                    "score": score,
                }
            )
        if not candidates:
            return {"text": None, "type": None}
        best = max(candidates, key=lambda item: item["score"])
        if best["score"] <= 0 and candidates:
            best = candidates[0]
        return {"text": best["text"], "type": best["type"]}

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return " ".join((text or "").split()).strip()

    def _build_redline_signal_text(self, *, raw_text: str, paragraph_text: str, event_type: str) -> str:
        clean_raw = self._normalize_spaces(raw_text)
        clean_para = self._normalize_spaces(paragraph_text)
        raw_tokens = self._tokenize(clean_raw)
        if len(clean_raw) >= 12 and len(raw_tokens) >= 2:
            return clean_raw
        if clean_para:
            if event_type == "deletion" and clean_raw:
                return f"delete fragment: {clean_raw} | clause context: {clean_para[:700]}"
            if event_type == "insertion" and clean_raw:
                return f"insert fragment: {clean_raw} | clause context: {clean_para[:700]}"
            return clean_para[:700]
        return clean_raw
