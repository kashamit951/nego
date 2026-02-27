export interface ClientConfig {
  apiBaseUrl: string;
  tenantId: string;
  apiKey: string;
  bootstrapToken: string;
}

export interface HealthResponse {
  status: string;
}

export interface UserCreateRequest {
  email: string;
  role: 'admin' | 'legal_reviewer' | 'analyst' | 'viewer';
}

export interface UserResponse {
  user_id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface ApiKeyCreateRequest {
  user_id: string;
  scopes: string[];
}

export interface ApiKeyCreateResponse {
  key_id: string;
  user_id: string;
  key_prefix: string;
  api_key: string;
  created_at: string;
}

export interface ApiKeyRevokeRequest {
  key_prefix: string;
}

export interface ApiKeyRevokeResponse {
  revoked: boolean;
}

export interface MeResponse {
  user_id: string | null;
  email: string;
  role: string;
  scopes: string[];
  tenant_id: string;
}

export interface RetrievedExample {
  clause_id: string | null;
  client_id: string | null;
  doc_type: string | null;
  clause_text: string;
  source_text?: string | null;
  anchor_clause_text?: string | null;
  linked_redline_text?: string | null;
  linked_comment_text?: string | null;
  clause_index?: number | null;
  clause_type: string;
  source_type: 'clause' | 'redline' | 'comment';
  is_clause: boolean;
  is_redline: boolean;
  is_comment: boolean;
  outcome: string | null;
  counterparty_name: string | null;
  score: number;
}

export interface CloseTimeEstimate {
  expected_rounds_remaining: number;
  expected_days_to_close: number;
  probability_close_in_7_days: number;
  sample_size: number;
  confidence: number;
  fastest_path_hint: string;
}

export interface HistoricalNegotiationPattern {
  sample_size: number;
  avg_rounds: number;
  avg_redline_events: number;
  accepted_rate: number;
  partially_accepted_rate: number;
  rejected_rate: number;
  dominant_redline_type: string | null;
  negotiation_style_hint: string;
}

export interface StrategicSuggestionResponse {
  clause_type: string;
  analysis_scope: 'single_client' | 'all_clients';
  client_id: string | null;
  example_source: 'clause' | 'redline' | 'comment';
  risk_score: number;
  acceptance_probability: number;
  proposed_redline: string;
  business_explanation: string;
  fallback_position: string;
  pattern_alert: string | null;
  predicted_final_outcome: 'accepted' | 'rejected' | 'partially_accepted';
  historical_pattern: HistoricalNegotiationPattern;
  close_time_estimate: CloseTimeEstimate;
  retrieved_examples: RetrievedExample[];
}

export interface UploadedClauseSuggestion {
  clause_index: number;
  clause_text: string;
  source_type: 'clause' | 'redline' | 'comment';
  matched_doc_type: string | null;
  matched_doc_type_confidence: number;
  suggestion: StrategicSuggestionResponse;
}

export interface StrategySuggestUploadResponse {
  file_name: string;
  parser_status: string;
  parse_error: string | null;
  analysis_scope: 'single_client' | 'all_clients';
  client_id: string | null;
  doc_type: string | null;
  matched_doc_type: string | null;
  matched_doc_type_confidence: number;
  counterparty_name: string | null;
  contract_value: number | null;
  clause_type: string | null;
  top_k: number;
  clauses_total: number;
  clauses_suggested: number;
  redline_events_detected: number;
  comments_detected: number;
  perfect_match: boolean;
  match_confidence: number;
  match_message: string | null;
  clause_suggestions: UploadedClauseSuggestion[];
  redline_suggestions: UploadedClauseSuggestion[];
  comment_suggestions: UploadedClauseSuggestion[];
  suggestions: UploadedClauseSuggestion[];
}

export interface NegotiationFlowItem {
  source_type: 'redline' | 'comment';
  source_index: number;
  clause_type?: string | null;
  source_position?: number | null;
  source_comment_id?: string | null;
  redline_event_type?: string | null;
  incoming_text: string;
  incoming_previous_text?: string | null;
  linked_comment_text?: string | null;
  suggested_redline: string;
  suggested_comment: string;
  rationale: string;
  expected_outcome: 'accepted' | 'rejected' | 'partially_accepted';
  confidence: number;
  evidence_status: 'supported' | 'weak' | 'none';
  evidence_score: number;
  citation_count: number;
  retrieved_examples: RetrievedExample[];
}

export interface NegotiationFlowSuggestUploadResponse {
  file_name: string;
  parser_status: string;
  parse_error: string | null;
  analysis_scope: 'single_client' | 'all_clients';
  client_id: string | null;
  doc_type: string | null;
  matched_doc_type: string | null;
  matched_doc_type_confidence: number;
  counterparty_name: string | null;
  contract_value: number | null;
  top_k: number;
  max_signals: number;
  redline_events_detected: number;
  comments_detected: number;
  playbook_summary: string;
  fastest_path_hint: string;
  expected_rounds_remaining: number;
  expected_days_to_close: number;
  probability_close_in_7_days: number;
  confidence: number;
  document_text?: string | null;
  items: NegotiationFlowItem[];
}

export interface RedlineApplyDecision {
  source_type: 'redline' | 'comment';
  source_index: number;
  source_position?: number | null;
  source_comment_id?: string | null;
  source_text?: string | null;
  source_context_text?: string | null;
  action: 'accept' | 'modify' | 'reject' | 'reply';
  modified_text?: string | null;
  reply_comment?: string | null;
}

export interface LearnedCounterpartyItem {
  counterparty_name: string;
  document_count: number;
}

export interface LearnedCounterpartyListResponse {
  analysis_scope: 'single_client' | 'all_clients';
  client_id: string | null;
  items: LearnedCounterpartyItem[];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  request_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  count: number;
}

export interface ApiErrorShape {
  detail?: string;
}

export interface CorpusScanRequest {
  client_id: string;
  source_path: string;
  source_label?: string | null;
  include_subdirectories: boolean;
  max_files: number;
  file_extensions: string[];
}

export interface CorpusFileRecord {
  file_id: string | null;
  client_id: string;
  relative_path: string;
  absolute_path: string;
  extension: string;
  size_bytes: number;
  hash_sha256: string;
  change_status: string;
  parser_status: string;
  parse_error: string | null;
  learned: boolean;
  last_learned_at: string | null;
  redline_count: number;
  comments_count: number;
  document_id: string | null;
}

export interface CorpusScanSummary {
  total_found: number;
  new_count: number;
  changed_count: number;
  unchanged_count: number;
  missing_count: number;
  learned_count: number;
  pending_count: number;
}

export interface CorpusScanResponse {
  source_id: string;
  client_id: string;
  source_path: string;
  source_label: string | null;
  scanned_at: string;
  summary: CorpusScanSummary;
  files: CorpusFileRecord[];
}

export interface CorpusLearnRequest extends CorpusScanRequest {
  default_doc_type?: string | null;
  counterparty_name?: string | null;
  contract_value?: number | null;
  mode: 'new_or_changed' | 'all';
  create_outcomes_from_redlines: boolean;
  create_outcomes_from_comments: boolean;
  comment_signal_engine?: 'rules' | 'llm';
  comment_rule_profile: 'strict' | 'balanced' | 'lenient';
  comment_accept_phrases: string[];
  comment_reject_phrases: string[];
  comment_revise_phrases: string[];
}

export interface CorpusLearnFileResult {
  file_id: string | null;
  relative_path: string;
  action: string;
  document_id: string | null;
  clauses_ingested: number;
  redlines_detected: number;
  comments_detected: number;
  error: string | null;
}

export interface CorpusLearnResponse {
  source_id: string;
  client_id: string;
  source_path: string;
  learned_documents: number;
  skipped_unchanged: number;
  failed_files: number;
  parsed_redlines: number;
  parsed_comments: number;
  files: CorpusLearnFileResult[];
}

export interface CorpusSourceStatus {
  source_id: string;
  client_id: string;
  source_path: string;
  source_label: string | null;
  include_subdirectories: boolean;
  last_scanned_at: string | null;
  last_learned_at: string | null;
  total_files: number;
  learned_files: number;
  changed_files: number;
  pending_files: number;
  missing_files: number;
  error_files: number;
}

export interface CorpusStatusResponse {
  sources: CorpusSourceStatus[];
}
