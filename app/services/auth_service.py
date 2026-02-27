from datetime import datetime, timezone
import hashlib
import secrets
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import ApiCredential, TenantUser
from app.security import AuthenticatedActor, ROLE_DEFAULT_SCOPES, known_role


class AuthenticationError(Exception):
    pass


class AuthService:
    def __init__(self, key_pepper: str) -> None:
        self.key_pepper = key_pepper

    def authenticate(self, db: Session, tenant_id: str, api_key: str | None) -> AuthenticatedActor:
        if not api_key:
            raise AuthenticationError("Missing X-Api-Key")

        prefix = self._parse_prefix(api_key)
        stmt = (
            select(ApiCredential, TenantUser)
            .join(
                TenantUser,
                and_(
                    TenantUser.id == ApiCredential.user_id,
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.is_active.is_(True),
                ),
            )
            .where(
                and_(
                    ApiCredential.tenant_id == tenant_id,
                    ApiCredential.key_prefix == prefix,
                    ApiCredential.revoked_at.is_(None),
                )
            )
            .limit(1)
        )
        row = db.execute(stmt).first()
        if row is None:
            raise AuthenticationError("Invalid API key")

        credential, user = row
        expected_hash = self.hash_api_key(api_key)
        if not secrets.compare_digest(expected_hash, credential.key_hash):
            raise AuthenticationError("Invalid API key")

        credential.last_used_at = datetime.now(timezone.utc)

        return AuthenticatedActor(
            user_id=user.id,
            email=user.email,
            role=user.role,
            scopes=list(credential.scopes or []),
        )

    def create_user(self, db: Session, tenant_id: str, email: str, role: str) -> TenantUser:
        role_normalized = role.strip().lower()
        if not known_role(role_normalized):
            raise ValueError(f"Unknown role: {role}")

        existing = db.execute(
            select(TenantUser).where(
                and_(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.email == email,
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError("User already exists for tenant")

        user = TenantUser(
            tenant_id=tenant_id,
            email=email,
            role=role_normalized,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user

    def create_api_key(
        self,
        db: Session,
        tenant_id: str,
        user_id: UUID,
        scopes: list[str] | None,
    ) -> tuple[ApiCredential, str]:
        user = db.execute(
            select(TenantUser).where(
                and_(
                    TenantUser.id == user_id,
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("User not found or inactive")

        key_prefix = secrets.token_hex(6)
        key_secret = secrets.token_hex(24)
        api_key = f"nego_{key_prefix}_{key_secret}"

        final_scopes = scopes if scopes else ROLE_DEFAULT_SCOPES.get(user.role, [])
        credential = ApiCredential(
            tenant_id=tenant_id,
            user_id=user.id,
            key_prefix=key_prefix,
            key_hash=self.hash_api_key(api_key),
            scopes=final_scopes,
        )
        db.add(credential)
        db.flush()
        return credential, api_key

    def revoke_api_key(self, db: Session, tenant_id: str, key_prefix: str) -> bool:
        credential = db.execute(
            select(ApiCredential).where(
                and_(
                    ApiCredential.tenant_id == tenant_id,
                    ApiCredential.key_prefix == key_prefix,
                    ApiCredential.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if credential is None:
            return False

        credential.revoked_at = datetime.now(timezone.utc)
        db.flush()
        return True

    def hash_api_key(self, api_key: str) -> str:
        payload = f"{self.key_pepper}:{api_key}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _parse_prefix(api_key: str) -> str:
        parts = api_key.split("_", 2)
        if len(parts) != 3 or parts[0] != "nego" or not parts[1]:
            raise AuthenticationError("Malformed API key")
        return parts[1]
