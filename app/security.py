from dataclasses import dataclass, field
from uuid import UUID


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "document:ingest",
        "outcome:write",
        "strategy:read",
        "corpus:read",
        "corpus:write",
        "auth:user:create",
        "auth:key:create",
        "auth:key:revoke",
        "audit:read",
    },
    "legal_reviewer": {
        "document:ingest",
        "outcome:write",
        "strategy:read",
        "corpus:read",
        "corpus:write",
        "audit:read",
    },
    "analyst": {
        "strategy:read",
        "corpus:read",
        "audit:read",
    },
    "viewer": {
        "strategy:read",
    },
}


ROLE_DEFAULT_SCOPES: dict[str, list[str]] = {
    "admin": ["*"],
    "legal_reviewer": [
        "document:ingest",
        "outcome:write",
        "strategy:read",
        "corpus:read",
        "corpus:write",
        "audit:read",
    ],
    "analyst": ["strategy:read", "corpus:read", "audit:read"],
    "viewer": ["strategy:read"],
}


@dataclass(slots=True)
class AuthenticatedActor:
    user_id: UUID | None
    email: str
    role: str
    scopes: list[str] = field(default_factory=list)


class AuthorizationError(Exception):
    pass


def known_role(role: str) -> bool:
    return role in ROLE_PERMISSIONS


def has_permission(actor: AuthenticatedActor, permission: str) -> bool:
    role_permissions = ROLE_PERMISSIONS.get(actor.role)
    if role_permissions is None:
        return False
    if permission not in role_permissions:
        return False

    scopes = actor.scopes or []
    if not scopes:
        return True
    return "*" in scopes or permission in scopes


def ensure_permission(actor: AuthenticatedActor, permission: str) -> None:
    if not has_permission(actor, permission):
        raise AuthorizationError(f"Missing permission: {permission}")
