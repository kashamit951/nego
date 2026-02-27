from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db.models import ClauseRecord, ContractDocument, NegotiationOutcome
from app.schemas.contracts import IngestDocumentRequest, NegotiationOutcomeCreateRequest
from app.services.clause_intelligence import ClauseIntelligenceService
from app.services.vector_store import VectorStore


class DocumentIngestionService:
    def __init__(self, clause_service: ClauseIntelligenceService, vector_store: VectorStore) -> None:
        self.clause_service = clause_service
        self.vector_store = vector_store

    def ingest_document(
        self,
        db: Session,
        tenant_id: str,
        request: IngestDocumentRequest,
    ) -> tuple[UUID, int]:
        clauses = self.clause_service.segment(request.raw_text)
        client_id = (request.client_id or "").strip() or "default_client"

        document = ContractDocument(
            tenant_id=tenant_id,
            client_id=client_id,
            doc_type=request.doc_type,
            counterparty_name=request.counterparty_name,
            contract_value=request.contract_value,
            raw_text=request.raw_text,
            metadata_json=request.metadata,
        )
        db.add(document)
        db.flush()

        for idx, clause_text in enumerate(clauses):
            classification = self.clause_service.classify(clause_text)
            vector = self.clause_service.embed(clause_text)
            point_id = str(uuid4())

            clause = ClauseRecord(
                tenant_id=tenant_id,
                client_id=client_id,
                document_id=document.id,
                clause_index=idx,
                clause_type=classification.clause_type,
                clause_text=clause_text,
                classifier_confidence=classification.confidence,
                vector_point_id=point_id,
            )
            db.add(clause)

            self.vector_store.upsert_clause(
                tenant_id=tenant_id,
                point_id=point_id,
                vector=vector,
                payload={
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "clause_type": classification.clause_type,
                    "doc_type": request.doc_type,
                    "counterparty_name": request.counterparty_name,
                    "contract_value": float(request.contract_value or 0),
                    "text": clause_text,
                    "source_text": clause_text,
                    "clause_index": idx,
                    "anchor_clause_text": clause_text,
                    "source_type": "clause",
                    "is_clause": True,
                    "is_redline": False,
                    "is_comment": False,
                },
            )

        # Session autoflush is disabled globally; flush so downstream same-request
        # queries (e.g., comment/redline anchoring) can resolve clause rows.
        db.flush()

        return document.id, len(clauses)


class OutcomeService:
    def record_outcome(
        self,
        db: Session,
        tenant_id: str,
        request: NegotiationOutcomeCreateRequest,
    ) -> UUID:
        client_id = self._resolve_client_id(db, tenant_id, request)
        row = NegotiationOutcome(
            tenant_id=tenant_id,
            client_id=client_id,
            document_id=request.document_id,
            clause_id=request.clause_id,
            doc_type=request.doc_type,
            clause_type=request.clause_type,
            counterparty_name=request.counterparty_name,
            deal_size=request.deal_size,
            original_text=request.original_text,
            counterparty_edit=request.counterparty_edit,
            client_response=request.client_response,
            final_text=request.final_text,
            outcome=request.outcome,
            negotiation_rounds=request.negotiation_rounds,
            won_by=request.won_by,
            redline_events=request.redline_events,
        )
        db.add(row)
        db.flush()
        return row.id

    @staticmethod
    def _resolve_client_id(
        db: Session,
        tenant_id: str,
        request: NegotiationOutcomeCreateRequest,
    ) -> str:
        explicit = request.client_id.strip() if request.client_id else None
        if request.document_id is None:
            return explicit or "default_client"

        document = db.get(ContractDocument, request.document_id)
        if document is None:
            raise ValueError(f"document_id not found: {request.document_id}")
        if document.tenant_id != tenant_id:
            raise ValueError("document_id does not belong to current tenant")

        doc_client_id = (document.client_id or "default_client").strip()
        if explicit and explicit != doc_client_id:
            raise ValueError("client_id does not match the provided document_id client scope")
        return explicit or doc_client_id
