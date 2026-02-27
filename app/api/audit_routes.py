from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import RequestContext, require_permission
from app.schemas.audit import AuditLogEntry, AuditLogListResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/v1/audit", tags=["audit"])
audit_service = AuditService()


@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    ctx: RequestContext = Depends(require_permission("audit:read")),
    limit: int = Query(default=100, ge=1, le=200),
    action: str | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
) -> AuditLogListResponse:
    rows = audit_service.list_logs(
        ctx.db,
        tenant_id=ctx.tenant_id,
        limit=limit,
        action=action,
        actor_user_id=actor_user_id,
    )

    items = [
        AuditLogEntry(
            id=row.id,
            actor_user_id=row.actor_user_id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            request_id=row.request_id,
            ip_address=row.ip_address,
            metadata=row.metadata_json,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return AuditLogListResponse(items=items, count=len(items))
