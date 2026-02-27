from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CorpusScanRequest(BaseModel):
    client_id: str = Field(default="default_client", min_length=1, max_length=128)
    source_path: str = Field(..., min_length=1, max_length=2048)
    source_label: str | None = Field(default=None, max_length=255)
    include_subdirectories: bool = True
    max_files: int = Field(default=4000, ge=1, le=50000)
    file_extensions: list[str] = Field(default_factory=list)


class CorpusFileRecord(BaseModel):
    file_id: UUID | None = None
    client_id: str
    relative_path: str
    absolute_path: str
    extension: str
    size_bytes: int
    hash_sha256: str
    change_status: str
    parser_status: str
    parse_error: str | None = None
    learned: bool
    last_learned_at: datetime | None = None
    redline_count: int
    comments_count: int
    document_id: UUID | None = None


class CorpusScanSummary(BaseModel):
    total_found: int
    new_count: int
    changed_count: int
    unchanged_count: int
    missing_count: int
    learned_count: int
    pending_count: int


class CorpusScanResponse(BaseModel):
    source_id: UUID
    client_id: str
    source_path: str
    source_label: str | None = None
    scanned_at: datetime
    summary: CorpusScanSummary
    files: list[CorpusFileRecord] = Field(default_factory=list)


class CorpusLearnRequest(CorpusScanRequest):
    default_doc_type: str | None = Field(default=None, max_length=64)
    counterparty_name: str | None = Field(default=None, max_length=255)
    contract_value: Decimal | None = Field(default=None, ge=0)
    mode: str = Field(default="new_or_changed", pattern=r"^(new_or_changed|all)$")
    create_outcomes_from_redlines: bool = False
    create_outcomes_from_comments: bool = True
    comment_signal_engine: str = Field(default="rules", pattern=r"^(llm|rules)$")
    comment_rule_profile: str = Field(default="balanced", pattern=r"^(strict|balanced|lenient)$")
    comment_accept_phrases: list[str] = Field(default_factory=list)
    comment_reject_phrases: list[str] = Field(default_factory=list)
    comment_revise_phrases: list[str] = Field(default_factory=list)


class CorpusLearnFileResult(BaseModel):
    file_id: UUID | None = None
    relative_path: str
    action: str
    document_id: UUID | None = None
    clauses_ingested: int = 0
    redlines_detected: int = 0
    comments_detected: int = 0
    error: str | None = None


class CorpusLearnResponse(BaseModel):
    source_id: UUID
    client_id: str
    source_path: str
    learned_documents: int
    skipped_unchanged: int
    failed_files: int
    parsed_redlines: int
    parsed_comments: int
    files: list[CorpusLearnFileResult] = Field(default_factory=list)


class CorpusSourceStatus(BaseModel):
    source_id: UUID
    client_id: str
    source_path: str
    source_label: str | None = None
    include_subdirectories: bool
    last_scanned_at: datetime | None = None
    last_learned_at: datetime | None = None
    total_files: int
    learned_files: int
    changed_files: int
    pending_files: int
    missing_files: int
    error_files: int


class CorpusStatusResponse(BaseModel):
    sources: list[CorpusSourceStatus] = Field(default_factory=list)
