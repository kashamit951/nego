from datetime import datetime
from decimal import Decimal
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ContractDocument(Base):
    __tablename__ = "contract_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True, default="default_client")
    doc_type: Mapped[str] = mapped_column(String(64), index=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clauses: Mapped[list["ClauseRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ClauseRecord(Base):
    __tablename__ = "clause_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True, default="default_client")
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_documents.id", ondelete="CASCADE"), index=True
    )
    clause_index: Mapped[int] = mapped_column(Integer)
    clause_type: Mapped[str] = mapped_column(String(128), index=True)
    clause_text: Mapped[str] = mapped_column(Text)
    classifier_confidence: Mapped[float] = mapped_column(Float)
    vector_point_id: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[ContractDocument] = relationship(back_populates="clauses")


class NegotiationOutcome(Base):
    __tablename__ = "negotiation_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True, default="default_client")
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    clause_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_records.id", ondelete="SET NULL"), nullable=True
    )
    doc_type: Mapped[str] = mapped_column(String(64), index=True)
    clause_type: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    deal_size: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    original_text: Mapped[str] = mapped_column(Text)
    counterparty_edit: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    negotiation_rounds: Mapped[int] = mapped_column(Integer, default=1)
    won_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    redline_events: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantUser(Base):
    __tablename__ = "tenant_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credentials: Mapped[list["ApiCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ApiCredential(Base):
    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="CASCADE"), index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(32), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[TenantUser] = relationship(back_populates="credentials")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorpusSource(Base):
    __tablename__ = "corpus_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_id", "source_path", name="uq_corpus_sources_tenant_client_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True, default="default_client")
    source_path: Mapped[str] = mapped_column(String(1024))
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    include_subdirectories: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_learned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    files: Mapped[list["CorpusFile"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class CorpusFile(Base):
    __tablename__ = "corpus_files"
    __table_args__ = (UniqueConstraint("tenant_id", "source_id", "relative_path", name="uq_corpus_files_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True, default="default_client")
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("corpus_sources.id", ondelete="CASCADE"), index=True
    )
    relative_path: Mapped[str] = mapped_column(String(1024))
    absolute_path: Mapped[str] = mapped_column(String(2048))
    file_extension: Mapped[str] = mapped_column(String(16), index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_hash_sha256: Mapped[str] = mapped_column(String(128), index=True)
    learned_hash_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    parser_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    redline_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    comments_summary: Mapped[list] = mapped_column(JSONB, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_learned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[CorpusSource] = relationship(back_populates="files")
