ALTER TABLE contract_documents
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(128);

UPDATE contract_documents
SET client_id = 'default_client'
WHERE client_id IS NULL;

ALTER TABLE contract_documents
    ALTER COLUMN client_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contract_documents_tenant_client
    ON contract_documents (tenant_id, client_id);

ALTER TABLE clause_records
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(128);

UPDATE clause_records cr
SET client_id = cd.client_id
FROM contract_documents cd
WHERE cr.document_id = cd.id
  AND cr.client_id IS NULL;

UPDATE clause_records
SET client_id = 'default_client'
WHERE client_id IS NULL;

ALTER TABLE clause_records
    ALTER COLUMN client_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_clause_records_tenant_client_clause_type
    ON clause_records (tenant_id, client_id, clause_type);

ALTER TABLE negotiation_outcomes
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(128);

UPDATE negotiation_outcomes n
SET client_id = cd.client_id
FROM contract_documents cd
WHERE n.document_id = cd.id
  AND n.client_id IS NULL;

UPDATE negotiation_outcomes
SET client_id = 'default_client'
WHERE client_id IS NULL;

ALTER TABLE negotiation_outcomes
    ALTER COLUMN client_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_outcomes_tenant_client_clause_outcome
    ON negotiation_outcomes (tenant_id, client_id, clause_type, outcome);

ALTER TABLE corpus_sources
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(128);

UPDATE corpus_sources
SET client_id = 'default_client'
WHERE client_id IS NULL;

ALTER TABLE corpus_sources
    ALTER COLUMN client_id SET NOT NULL;

ALTER TABLE corpus_sources
    DROP CONSTRAINT IF EXISTS uq_corpus_sources_tenant_path;

ALTER TABLE corpus_sources
    ADD CONSTRAINT uq_corpus_sources_tenant_client_path
    UNIQUE (tenant_id, client_id, source_path);

CREATE INDEX IF NOT EXISTS idx_corpus_sources_tenant_client_path
    ON corpus_sources (tenant_id, client_id, source_path);

ALTER TABLE corpus_files
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(128);

UPDATE corpus_files cf
SET client_id = cs.client_id
FROM corpus_sources cs
WHERE cf.source_id = cs.id
  AND cf.client_id IS NULL;

UPDATE corpus_files
SET client_id = 'default_client'
WHERE client_id IS NULL;

ALTER TABLE corpus_files
    ALTER COLUMN client_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_corpus_files_tenant_client_source
    ON corpus_files (tenant_id, client_id, source_id);
