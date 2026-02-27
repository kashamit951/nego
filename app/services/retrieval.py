from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import ClauseRecord, ContractDocument, NegotiationOutcome
from app.schemas.contracts import StrategicSuggestionRequest
from app.services.clause_intelligence import ClauseIntelligenceService
from app.services.vector_store import VectorStore


def _normalize_source_type(value: str | None, default: str = "clause") -> str:
    if value in {"clause", "redline", "comment"}:
        return value
    return default


def _to_int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


class SmartRetrievalService:
    def __init__(self, clause_service: ClauseIntelligenceService, vector_store: VectorStore) -> None:
        self.clause_service = clause_service
        self.vector_store = vector_store

    def retrieve(
        self,
        db: Session,
        tenant_id: str,
        request: StrategicSuggestionRequest,
    ) -> dict:
        requested_client_id = request.client_id.strip() if request.client_id else None
        if request.analysis_scope == "single_client" and not requested_client_id:
            raise ValueError("client_id is required when analysis_scope is single_client")

        client_filter = requested_client_id if request.analysis_scope == "single_client" else None
        source_type = request.example_source
        clause_type = request.clause_type or "other"
        clause_type_confidence = 1.0 if request.clause_type else 0.5

        query_vector = self.clause_service.embed(request.new_clause_text)
        vector_hits = self.vector_store.search(
            tenant_id=tenant_id,
            query_vector=query_vector,
            top_k=max(request.top_k * 5, 25),
            clause_type=clause_type if (clause_type != "other" and source_type == "clause") else None,
            client_id=client_filter,
            source_type=source_type,
        )

        point_ids = [str(item["point_id"]) for item in vector_hits]
        point_details: dict[str, tuple] = {}
        if point_ids:
            detail_rows = db.execute(
                select(ClauseRecord, ContractDocument, NegotiationOutcome)
                .join(ContractDocument, ClauseRecord.document_id == ContractDocument.id)
                .outerjoin(
                    NegotiationOutcome,
                    and_(
                        NegotiationOutcome.clause_id == ClauseRecord.id,
                        NegotiationOutcome.tenant_id == tenant_id,
                    ),
                )
                .where(
                    and_(
                        ClauseRecord.tenant_id == tenant_id,
                        ClauseRecord.vector_point_id.in_(point_ids),
                    )
                )
            ).all()
            for clause, document, outcome in detail_rows:
                point_details[str(clause.vector_point_id)] = (clause, document, outcome)

        doc_ids: set[UUID] = set()
        clause_ids: set[UUID] = set()
        for hit in vector_hits[: request.top_k]:
            payload = hit["payload"]
            raw_doc_id = payload.get("document_id")
            raw_clause_id = payload.get("clause_id")
            if raw_doc_id:
                try:
                    doc_ids.add(UUID(str(raw_doc_id)))
                except Exception:
                    pass
            if raw_clause_id:
                try:
                    clause_ids.add(UUID(str(raw_clause_id)))
                except Exception:
                    pass

        latest_outcome_by_doc: dict[UUID, NegotiationOutcome] = {}
        latest_outcome_by_clause: dict[UUID, NegotiationOutcome] = {}
        if doc_ids or clause_ids:
            scope_filters = []
            if doc_ids:
                scope_filters.append(NegotiationOutcome.document_id.in_(list(doc_ids)))
            if clause_ids:
                scope_filters.append(NegotiationOutcome.clause_id.in_(list(clause_ids)))
            outcome_rows = db.execute(
                select(NegotiationOutcome)
                .where(
                    and_(
                        NegotiationOutcome.tenant_id == tenant_id,
                        or_(*scope_filters),
                    )
                )
                .order_by(NegotiationOutcome.created_at.desc())
                .limit(1000)
            ).scalars().all()
            for row in outcome_rows:
                if row.document_id and row.document_id not in latest_outcome_by_doc:
                    latest_outcome_by_doc[row.document_id] = row
                if row.clause_id and row.clause_id not in latest_outcome_by_clause:
                    latest_outcome_by_clause[row.clause_id] = row

        top_examples = []
        for hit in vector_hits[: request.top_k]:
            payload = hit["payload"]
            payload_source = _normalize_source_type(
                str(payload.get("source_type")) if payload.get("source_type") is not None else None,
                default=source_type,
            )
            clause = document = outcome = None
            if payload_source == "clause":
                clause, document, outcome = point_details.get(str(hit["point_id"]), (None, None, None))
            if outcome is None:
                raw_clause_id = payload.get("clause_id")
                raw_doc_id = payload.get("document_id")
                if raw_clause_id:
                    try:
                        outcome = latest_outcome_by_clause.get(UUID(str(raw_clause_id)))
                    except Exception:
                        outcome = None
                if outcome is None and raw_doc_id:
                    try:
                        outcome = latest_outcome_by_doc.get(UUID(str(raw_doc_id)))
                    except Exception:
                        outcome = None
            clause_text = (
                clause.clause_text
                if clause is not None
                else str(payload.get("text") or payload.get("source_text") or "")
            )
            top_examples.append(
                {
                    "clause_id": clause.id if clause is not None else None,
                    "client_id": (
                        document.client_id
                        if document is not None
                        else payload.get("client_id")
                    ),
                    "doc_type": (
                        document.doc_type
                        if document is not None
                        else payload.get("doc_type")
                    ),
                    "clause_text": clause_text,
                    "source_text": payload.get("source_text") or clause_text,
                    "anchor_clause_text": payload.get("anchor_clause_text") or clause_text,
                    "linked_redline_text": payload.get("linked_redline_text"),
                    "linked_comment_text": payload.get("linked_comment_text"),
                    "clause_index": _to_int_or_none(payload.get("clause_index")),
                    "clause_type": (
                        clause.clause_type
                        if clause is not None
                        else payload.get("clause_type", clause_type)
                    ),
                    "source_type": payload_source,
                    "is_clause": bool(payload.get("is_clause", payload_source == "clause")),
                    "is_redline": bool(payload.get("is_redline", payload_source == "redline")),
                    "is_comment": bool(payload.get("is_comment", payload_source == "comment")),
                    "outcome": (
                        outcome.outcome
                        if outcome is not None
                        else payload.get("outcome")
                    ),
                    "counterparty_name": (
                        outcome.counterparty_name
                        if outcome is not None and outcome.counterparty_name
                        else (
                            document.counterparty_name
                        if document is not None
                        else payload.get("counterparty_name")
                        )
                    ),
                    "counterparty_edit": outcome.counterparty_edit if outcome is not None else None,
                    "client_response": outcome.client_response if outcome is not None else None,
                    "final_text": outcome.final_text if outcome is not None else None,
                    "negotiation_rounds": (
                        int(outcome.negotiation_rounds)
                        if outcome is not None and outcome.negotiation_rounds is not None
                        else None
                    ),
                    "score": round(float(hit["score"]), 4),
                    "semantic_similarity": float(hit["score"]),
                    "same_counterparty": 0.0,
                    "same_client": 1.0 if client_filter else 0.5,
                    "similar_outcome": 0.5,
                    "similar_contract_value": 0.5,
                    "clause_type_confidence": clause_type_confidence,
                }
            )

        return {
            "clause_type": clause_type,
            "clause_type_confidence": clause_type_confidence,
            "analysis_scope": request.analysis_scope,
            "client_id": client_filter,
            "example_source": source_type,
            "examples": top_examples,
        }
