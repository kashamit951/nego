CREATE TABLE IF NOT EXISTS corpus_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    source_path VARCHAR(1024) NOT NULL,
    source_label VARCHAR(255),
    include_subdirectories BOOLEAN NOT NULL DEFAULT TRUE,
    last_scanned_at TIMESTAMPTZ,
    last_learned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_corpus_sources_tenant_path UNIQUE (tenant_id, source_path)
);

CREATE TABLE IF NOT EXISTS corpus_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(128) NOT NULL,
    source_id UUID NOT NULL REFERENCES corpus_sources(id) ON DELETE CASCADE,
    relative_path VARCHAR(1024) NOT NULL,
    absolute_path VARCHAR(2048) NOT NULL,
    file_extension VARCHAR(16) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    file_hash_sha256 VARCHAR(128) NOT NULL,
    learned_hash_sha256 VARCHAR(128),
    parser_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    parse_error TEXT,
    redline_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    comments_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_missing BOOLEAN NOT NULL DEFAULT FALSE,
    document_id UUID REFERENCES contract_documents(id) ON DELETE SET NULL,
    last_seen_at TIMESTAMPTZ,
    last_learned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_corpus_files_path UNIQUE (tenant_id, source_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_corpus_sources_tenant_path
    ON corpus_sources (tenant_id, source_path);

CREATE INDEX IF NOT EXISTS idx_corpus_files_tenant_source
    ON corpus_files (tenant_id, source_id);

CREATE INDEX IF NOT EXISTS idx_corpus_files_parser_status
    ON corpus_files (tenant_id, parser_status);

CREATE INDEX IF NOT EXISTS idx_corpus_files_hash
    ON corpus_files (tenant_id, file_hash_sha256);

CREATE INDEX IF NOT EXISTS idx_corpus_files_learned_hash
    ON corpus_files (tenant_id, learned_hash_sha256);

CREATE INDEX IF NOT EXISTS idx_corpus_files_missing
    ON corpus_files (tenant_id, is_missing);

ALTER TABLE corpus_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE corpus_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE corpus_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE corpus_files FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_corpus_sources ON corpus_sources;
CREATE POLICY tenant_isolation_corpus_sources ON corpus_sources
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_corpus_files ON corpus_files;
CREATE POLICY tenant_isolation_corpus_files ON corpus_files
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
