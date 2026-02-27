from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal
from app.security import AuthenticatedActor, AuthorizationError, ensure_permission
from app.services.auth_service import AuthService, AuthenticationError

settings = get_settings()
auth_service = AuthService(key_pepper=settings.auth_key_pepper)


@dataclass(slots=True)
class RequestContext:
    tenant_id: str
    db: Session
    actor: AuthenticatedActor
    request_id: str
    ip_address: str | None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-Id")) -> str:
    tenant_id = x_tenant_id.strip()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id cannot be empty",
        )
    return tenant_id


def get_request_context(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> RequestContext:
    db.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )

    if settings.auth_enabled:
        try:
            actor = auth_service.authenticate(db, tenant_id, x_api_key)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
    else:
        actor = AuthenticatedActor(
            user_id=None,
            email="system@local",
            role="admin",
            scopes=["*"],
        )

    request_id = (x_request_id or str(uuid4())).strip()
    ip_address = request.client.host if request.client else None
    return RequestContext(
        tenant_id=tenant_id,
        db=db,
        actor=actor,
        request_id=request_id,
        ip_address=ip_address,
    )


def require_permission(permission: str):
    def permission_dependency(ctx: RequestContext = Depends(get_request_context)) -> RequestContext:
        try:
            ensure_permission(ctx.actor, permission)
        except AuthorizationError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return ctx

    return permission_dependency
