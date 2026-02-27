from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestContext,
    auth_service,
    get_db,
    get_request_context,
    get_tenant_id,
    require_permission,
)
from app.config import get_settings
from app.db.models import TenantUser
from app.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyRevokeRequest,
    ApiKeyRevokeResponse,
    MeResponse,
    UserCreateRequest,
    UserResponse,
)
from app.services.audit_service import AuditService

router = APIRouter(prefix="/v1/auth", tags=["auth"])
audit_service = AuditService()
settings = get_settings()


@router.get("/me", response_model=MeResponse)
def me(ctx: RequestContext = Depends(get_request_context)) -> MeResponse:
    return MeResponse(
        user_id=ctx.actor.user_id,
        email=ctx.actor.email,
        role=ctx.actor.role,
        scopes=ctx.actor.scopes,
        tenant_id=ctx.tenant_id,
    )


@router.post("/bootstrap-admin", response_model=ApiKeyCreateResponse)
def bootstrap_admin(
    request: UserCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_db),
    x_bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
) -> ApiKeyCreateResponse:
    if not settings.auth_bootstrap_token or x_bootstrap_token != settings.auth_bootstrap_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bootstrap token")
    if request.role != "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bootstrap role must be admin")

    db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
    existing_users = db.execute(
        select(func.count(TenantUser.id)).where(TenantUser.tenant_id == tenant_id)
    ).scalar_one()
    if int(existing_users or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant already initialized",
        )

    try:
        user = auth_service.create_user(db=db, tenant_id=tenant_id, email=request.email, role="admin")
        credential, api_key = auth_service.create_api_key(
            db=db,
            tenant_id=tenant_id,
            user_id=user.id,
            scopes=["*"],
        )
        audit_service.record(
            db,
            tenant_id=tenant_id,
            action="auth.bootstrap_admin",
            resource_type="tenant_user",
            resource_id=str(user.id),
            actor_user_id=user.id,
            metadata={"email": user.email},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to bootstrap admin: {exc}") from exc

    return ApiKeyCreateResponse(
        key_id=credential.id,
        user_id=credential.user_id,
        key_prefix=credential.key_prefix,
        api_key=api_key,
        created_at=credential.created_at,
    )


@router.post("/users", response_model=UserResponse)
def create_user(
    request: UserCreateRequest,
    ctx: RequestContext = Depends(require_permission("auth:user:create")),
) -> UserResponse:
    try:
        user = auth_service.create_user(
            db=ctx.db,
            tenant_id=ctx.tenant_id,
            email=request.email,
            role=request.role,
        )
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="auth.user.create",
            resource_type="tenant_user",
            resource_id=str(user.id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={"email": user.email, "role": user.role},
        )
        ctx.db.commit()
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create user: {exc}") from exc

    return UserResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/keys", response_model=ApiKeyCreateResponse)
def create_api_key(
    request: ApiKeyCreateRequest,
    ctx: RequestContext = Depends(require_permission("auth:key:create")),
) -> ApiKeyCreateResponse:
    try:
        credential, api_key = auth_service.create_api_key(
            db=ctx.db,
            tenant_id=ctx.tenant_id,
            user_id=request.user_id,
            scopes=request.scopes,
        )
        audit_service.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="auth.key.create",
            resource_type="api_credential",
            resource_id=str(credential.id),
            actor_user_id=ctx.actor.user_id,
            request_id=ctx.request_id,
            ip_address=ctx.ip_address,
            metadata={"user_id": str(request.user_id), "scopes": credential.scopes},
        )
        ctx.db.commit()
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create api key: {exc}") from exc

    return ApiKeyCreateResponse(
        key_id=credential.id,
        user_id=credential.user_id,
        key_prefix=credential.key_prefix,
        api_key=api_key,
        created_at=credential.created_at,
    )


@router.post("/keys/revoke", response_model=ApiKeyRevokeResponse)
def revoke_api_key(
    request: ApiKeyRevokeRequest,
    ctx: RequestContext = Depends(require_permission("auth:key:revoke")),
) -> ApiKeyRevokeResponse:
    try:
        revoked = auth_service.revoke_api_key(
            db=ctx.db,
            tenant_id=ctx.tenant_id,
            key_prefix=request.key_prefix,
        )
        if revoked:
            audit_service.record(
                ctx.db,
                tenant_id=ctx.tenant_id,
                action="auth.key.revoke",
                resource_type="api_credential",
                resource_id=request.key_prefix,
                actor_user_id=ctx.actor.user_id,
                request_id=ctx.request_id,
                ip_address=ctx.ip_address,
                metadata={"key_prefix": request.key_prefix},
            )
        ctx.db.commit()
    except Exception as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to revoke key: {exc}") from exc

    return ApiKeyRevokeResponse(revoked=revoked)
