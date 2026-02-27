from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class IngestDocumentRequest(BaseModel):
    client_id: str = Field(default="default_client", min_length=1, max_length=128)
    doc_type: str = Field(..., max_length=64)
    counterparty_name: str | None = Field(default=None, max_length=255)
    contract_value: Decimal | None = Field(default=None, ge=0)
    raw_text: str = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)


class IngestDocumentResponse(BaseModel):
    document_id: UUID
    clauses_ingested: int


class NegotiationOutcomeCreateRequest(BaseModel):
    client_id: str | None = Field(default=None, min_length=1, max_length=128)
    document_id: UUID | None = None
    clause_id: UUID | None = None
    doc_type: str = Field(..., max_length=64)
    clause_type: str = Field(..., max_length=128)
    counterparty_name: str | None = Field(default=None, max_length=255)
    deal_size: Decimal | None = Field(default=None, ge=0)
    original_text: str = Field(..., min_length=1)
    counterparty_edit: str | None = None
    client_response: str | None = None
    final_text: str | None = None
    outcome: str = Field(..., pattern=r"^(accepted|rejected|partially_accepted)$")
    negotiation_rounds: int = Field(default=1, ge=1)
    won_by: str | None = Field(default=None, pattern=r"^(client|counterparty|mutual)$")
    redline_events: list[dict] = Field(default_factory=list)


class NegotiationOutcomeCreateResponse(BaseModel):
    outcome_id: UUID


class StrategicSuggestionRequest(BaseModel):
    client_id: str | None = Field(default=None, min_length=1, max_length=128)
    analysis_scope: str = Field(default="all_clients", pattern=r"^(single_client|all_clients)$")
    example_source: str = Field(default="clause", pattern=r"^(clause|redline|comment)$")
    doc_type: str = Field(..., max_length=64)
    counterparty_name: str | None = Field(default=None, max_length=255)
    contract_value: Decimal | None = Field(default=None, ge=0)
    clause_type: str | None = Field(default=None, max_length=128)
    new_clause_text: str = Field(..., min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)


class RetrievedExample(BaseModel):
    clause_id: UUID | None = None
    client_id: str | None = None
    doc_type: str | None = None
    clause_text: str
    source_text: str | None = None
    anchor_clause_text: str | None = None
    linked_redline_text: str | None = None
    linked_comment_text: str | None = None
    clause_index: int | None = None
    clause_type: str
    source_type: str = Field(default="clause", pattern=r"^(clause|redline|comment)$")
    is_clause: bool = True
    is_redline: bool = False
    is_comment: bool = False
    outcome: str | None = None
    counterparty_name: str | None = None
    score: float


class CloseTimeEstimate(BaseModel):
    expected_rounds_remaining: float = Field(default=0.0, ge=0.0)
    expected_days_to_close: int = Field(default=1, ge=1)
    probability_close_in_7_days: float = Field(default=0.0, ge=0.0, le=1.0)
    sample_size: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fastest_path_hint: str = ""


class HistoricalNegotiationPattern(BaseModel):
    sample_size: int = Field(default=0, ge=0)
    avg_rounds: float = Field(default=0.0, ge=0.0)
    avg_redline_events: float = Field(default=0.0, ge=0.0)
    accepted_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    partially_accepted_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    rejected_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    dominant_redline_type: str | None = None
    negotiation_style_hint: str = ""


class StrategicSuggestionResponse(BaseModel):
    clause_type: str
    analysis_scope: str
    client_id: str | None = None
    example_source: str = Field(default="clause", pattern=r"^(clause|redline|comment)$")
    risk_score: float
    acceptance_probability: float
    proposed_redline: str
    business_explanation: str
    fallback_position: str
    pattern_alert: str | None = None
    predicted_final_outcome: str = Field(default="partially_accepted", pattern=r"^(accepted|rejected|partially_accepted)$")
    historical_pattern: HistoricalNegotiationPattern = Field(default_factory=HistoricalNegotiationPattern)
    close_time_estimate: CloseTimeEstimate = Field(default_factory=CloseTimeEstimate)
    retrieved_examples: list[RetrievedExample] = Field(default_factory=list)


class UploadedClauseSuggestion(BaseModel):
    clause_index: int = Field(..., ge=0)
    clause_text: str
    source_type: str = Field(default="clause", pattern=r"^(clause|redline|comment)$")
    matched_doc_type: str | None = None
    matched_doc_type_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    suggestion: StrategicSuggestionResponse


class StrategySuggestUploadResponse(BaseModel):
    file_name: str
    parser_status: str
    parse_error: str | None = None
    analysis_scope: str
    client_id: str | None = None
    doc_type: str | None = None
    matched_doc_type: str | None = None
    matched_doc_type_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    counterparty_name: str | None = None
    contract_value: Decimal | None = None
    clause_type: str | None = None
    top_k: int = Field(..., ge=1, le=50)
    clauses_total: int = Field(..., ge=0)
    clauses_suggested: int = Field(..., ge=0)
    redline_events_detected: int = Field(..., ge=0)
    comments_detected: int = Field(..., ge=0)
    perfect_match: bool = False
    match_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    match_message: str | None = None
    clause_suggestions: list[UploadedClauseSuggestion] = Field(default_factory=list)
    redline_suggestions: list[UploadedClauseSuggestion] = Field(default_factory=list)
    comment_suggestions: list[UploadedClauseSuggestion] = Field(default_factory=list)
    suggestions: list[UploadedClauseSuggestion] = Field(default_factory=list)


class NegotiationFlowItem(BaseModel):
    source_type: str = Field(default="redline", pattern=r"^(redline|comment)$")
    source_index: int = Field(default=0, ge=0)
    clause_type: str | None = None
    source_position: int | None = None
    source_comment_id: str | None = None
    redline_event_type: str | None = None
    incoming_text: str
    incoming_previous_text: str | None = None
    linked_comment_text: str | None = None
    suggested_redline: str
    suggested_comment: str
    rationale: str
    expected_outcome: str = Field(default="partially_accepted", pattern=r"^(accepted|rejected|partially_accepted)$")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_status: str = Field(default="weak", pattern=r"^(supported|weak|none)$")
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_count: int = Field(default=0, ge=0)
    retrieved_examples: list[RetrievedExample] = Field(default_factory=list)


class NegotiationFlowSuggestUploadResponse(BaseModel):
    file_name: str
    parser_status: str
    parse_error: str | None = None
    analysis_scope: str
    client_id: str | None = None
    doc_type: str | None = None
    matched_doc_type: str | None = None
    matched_doc_type_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    counterparty_name: str | None = None
    contract_value: Decimal | None = None
    top_k: int = Field(..., ge=1, le=50)
    max_signals: int = Field(..., ge=0)
    redline_events_detected: int = Field(..., ge=0)
    comments_detected: int = Field(..., ge=0)
    playbook_summary: str
    fastest_path_hint: str
    expected_rounds_remaining: float = Field(default=0.0, ge=0.0)
    expected_days_to_close: int = Field(default=1, ge=1)
    probability_close_in_7_days: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    document_text: str | None = None
    items: list[NegotiationFlowItem] = Field(default_factory=list)


class RedlineApplyDecision(BaseModel):
    source_type: str = Field(default="redline", pattern=r"^(redline|comment)$")
    source_index: int = Field(default=0, ge=0)
    source_position: int | None = None
    source_comment_id: str | None = None
    source_text: str | None = None
    source_context_text: str | None = None
    action: str = Field(..., pattern=r"^(accept|modify|reject|reply)$")
    modified_text: str | None = None
    reply_comment: str | None = None


class RedlineApplyResult(BaseModel):
    file_name: str
    total_decisions: int = Field(..., ge=0)
    applied_decisions: int = Field(..., ge=0)
    skipped_decisions: int = Field(..., ge=0)


class LearnedCounterpartyItem(BaseModel):
    counterparty_name: str
    document_count: int = Field(..., ge=1)


class LearnedCounterpartyListResponse(BaseModel):
    analysis_scope: str
    client_id: str | None = None
    items: list[LearnedCounterpartyItem] = Field(default_factory=list)
