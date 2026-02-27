CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS contract_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    doc_type VARCHAR(64) NOT NULL,
    counterparty_name VARCHAR(255),
    contract_value NUMERIC(14,2),
    raw_text TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clause_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    document_id UUID NOT NULL REFERENCES contract_documents(id) ON DELETE CASCADE,
    clause_index INTEGER NOT NULL,
    clause_type VARCHAR(128) NOT NULL,
    clause_text TEXT NOT NULL,
    classifier_confidence DOUBLE PRECISION NOT NULL,
    vector_point_id VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS negotiation_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    document_id UUID REFERENCES contract_documents(id) ON DELETE SET NULL,
    clause_id UUID REFERENCES clause_records(id) ON DELETE SET NULL,
    doc_type VARCHAR(64) NOT NULL,
    clause_type VARCHAR(128) NOT NULL,
    counterparty_name VARCHAR(255),
    deal_size NUMERIC(14,2),
    original_text TEXT NOT NULL,
    counterparty_edit TEXT,
    client_response TEXT,
    final_text TEXT,
    outcome VARCHAR(32) NOT NULL CHECK (outcome IN ('accepted','rejected','partially_accepted')),
    negotiation_rounds INTEGER NOT NULL DEFAULT 1,
    won_by VARCHAR(32) CHECK (won_by IN ('client','counterparty','mutual')),
    redline_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    user_id UUID NOT NULL REFERENCES tenant_users(id) ON DELETE CASCADE,
    key_prefix VARCHAR(32) NOT NULL,
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    actor_user_id UUID REFERENCES tenant_users(id) ON DELETE SET NULL,
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    resource_id VARCHAR(128),
    request_id VARCHAR(64),
    ip_address VARCHAR(64),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contract_documents_tenant_doc_type
    ON contract_documents (tenant_id, doc_type);

CREATE INDEX IF NOT EXISTS idx_clause_records_tenant_clause_type
    ON clause_records (tenant_id, clause_type);

CREATE INDEX IF NOT EXISTS idx_outcomes_tenant_clause_outcome
    ON negotiation_outcomes (tenant_id, clause_type, outcome);

CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant_email
    ON tenant_users (tenant_id, email);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_users_tenant_email
    ON tenant_users (tenant_id, email);

CREATE INDEX IF NOT EXISTS idx_api_credentials_tenant_prefix
    ON api_credentials (tenant_id, key_prefix);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created
    ON audit_logs (tenant_id, created_at DESC);

ALTER TABLE contract_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE clause_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE clause_records FORCE ROW LEVEL SECURITY;
ALTER TABLE negotiation_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE negotiation_outcomes FORCE ROW LEVEL SECURITY;
ALTER TABLE tenant_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_users FORCE ROW LEVEL SECURITY;
ALTER TABLE api_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_documents ON contract_documents;
CREATE POLICY tenant_isolation_documents ON contract_documents
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_clauses ON clause_records;
CREATE POLICY tenant_isolation_clauses ON clause_records
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_outcomes ON negotiation_outcomes;
CREATE POLICY tenant_isolation_outcomes ON negotiation_outcomes
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_users ON tenant_users;
CREATE POLICY tenant_isolation_users ON tenant_users
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_api_credentials ON api_credentials;
CREATE POLICY tenant_isolation_api_credentials ON api_credentials
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_audit_logs ON audit_logs;
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
