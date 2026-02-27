from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog


class AuditService:
    def record(
        self,
        db: Session,
        *,
        tenant_id: str,
        action: str,
        resource_type: str,
        actor_user_id,
        resource_id: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        row = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            ip_address=ip_address,
            metadata_json=metadata or {},
        )
        db.add(row)
        db.flush()
        return row

    def list_logs(
        self,
        db: Session,
        *,
        tenant_id: str,
        limit: int = 100,
        action: str | None = None,
        actor_user_id=None,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        filters = []
        if action:
            filters.append(AuditLog.action == action)
        if actor_user_id:
            filters.append(AuditLog.actor_user_id == actor_user_id)
        if filters:
            stmt = stmt.where(and_(*filters))

        stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)
        return list(db.execute(stmt).scalars().all())
