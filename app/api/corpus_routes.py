from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import RequestContext, require_permission
from app.config import get_settings
from app.schemas.corpus import (
    CorpusLearnRequest,
    CorpusLearnResponse,
    CorpusScanRequest,
    CorpusScanResponse,
    CorpusStatusResponse,
)
from app.services.audit_service import AuditService
from app.services.clause_intelligence import build_clause_intelligence_service
from app.services.corpus_parser import CorpusParserService
from app.services.corpus_service import CorpusManagementService
from app.services.document_service import DocumentIngestionService
from app.services.llm_provider import build_llm_provider
from app.services.vector_store import VectorStore

router = APIRouter(prefix="/v1/corpus", tags=["corpus"])

settings = get_settings()
clause_service = build_clause_intelligence_service(settings)
vector_store = VectorStore(settings, embedding_dim=clause_service.embedding_dim)
ingestion_service = DocumentIngestionService(clause_service, vector_store)
parser_service = CorpusParserService()
llm_provider = build_llm_provider(settings)
corpus_service = CorpusManagementService(
    settings=settings,
    ingestion_service=ingestion_service,
    parser_service=parser_service,
    llm_provider=llm_provider,
)
audit_service = AuditService()


@router.post("/scan", response_model=CorpusScanResponse)
def scan_corpus(
    request: CorpusScanRequest,
    ctx: RequestContext = Depends(require_permission("corpus:read")),
) -> CorpusScanResponse:
    try:
        response = corpus_service.scan(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="corpus.scan",
            resource_type="corpus_source",
            resource_id=str(response.source_id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "client_id": response.client_id,
                "source_path": response.source_path,
                "total_found": response.summary.total_found,
                "new_count": response.summary.new_count,
                "changed_count": response.summary.changed_count,
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to scan corpus: {exc}") from exc


@router.post("/learn", response_model=CorpusLearnResponse)
def learn_corpus(
    request: CorpusLearnRequest,
    ctx: RequestContext = Depends(require_permission("corpus:write")),
) -> CorpusLearnResponse:
    try:
        response = corpus_service.learn(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="corpus.learn",
            resource_type="corpus_source",
            resource_id=str(response.source_id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "client_id": response.client_id,
                "source_path": response.source_path,
                "learned_documents": response.learned_documents,
                "failed_files": response.failed_files,
                "mode": request.mode,
                "create_outcomes_from_redlines": request.create_outcomes_from_redlines,
                "create_outcomes_from_comments": request.create_outcomes_from_comments,
                "comment_signal_engine": request.comment_signal_engine,
                "comment_rule_profile": request.comment_rule_profile,
                "custom_comment_rules": {
                    "accept_phrases": len(request.comment_accept_phrases),
                    "reject_phrases": len(request.comment_reject_phrases),
                    "revise_phrases": len(request.comment_revise_phrases),
                },
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to learn corpus: {exc}") from exc


@router.post("/update", response_model=CorpusLearnResponse)
def update_corpus(
    request: CorpusLearnRequest,
    ctx: RequestContext = Depends(require_permission("corpus:write")),
) -> CorpusLearnResponse:
    try:
        response = corpus_service.update(ctx.db, ctx.tenant_id, request)
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="corpus.update",
            resource_type="corpus_source",
            resource_id=str(response.source_id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={
                "client_id": response.client_id,
                "source_path": response.source_path,
                "learned_documents": response.learned_documents,
                "failed_files": response.failed_files,
                "create_outcomes_from_redlines": request.create_outcomes_from_redlines,
                "create_outcomes_from_comments": request.create_outcomes_from_comments,
                "comment_signal_engine": request.comment_signal_engine,
                "comment_rule_profile": request.comment_rule_profile,
                "custom_comment_rules": {
                    "accept_phrases": len(request.comment_accept_phrases),
                    "reject_phrases": len(request.comment_reject_phrases),
                    "revise_phrases": len(request.comment_revise_phrases),
                },
            },
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update corpus: {exc}") from exc


@router.get("/status", response_model=CorpusStatusResponse)
def corpus_status(
    source_path: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    ctx: RequestContext = Depends(require_permission("corpus:read")),
) -> CorpusStatusResponse:
    try:
        normalized_client = client_id.strip() if client_id else None
        response = corpus_service.status(
            ctx.db,
            ctx.tenant_id,
            source_path=source_path,
            client_id=normalized_client,
        )
        ctx.db.commit()
        return response
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to fetch corpus status: {exc}") from exc

