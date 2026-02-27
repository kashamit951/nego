"""add client-level scoping inside tenant

Revision ID: 0003_client_scoping
Revises: 0002_corpus
Create Date: 2026-02-12 01:00:00
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_client_scoping"
down_revision: Union[str, None] = "0002_corpus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sql_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sql" / "003_client_scoping.sql"


def upgrade() -> None:
    sql_blob = _sql_path().read_text(encoding="utf-8")
    bind = op.get_bind()
    statements = [stmt.strip() for stmt in sql_blob.split(";") if stmt.strip()]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "DROP INDEX IF EXISTS idx_corpus_files_tenant_client_source",
        "ALTER TABLE corpus_files DROP COLUMN IF EXISTS client_id",
        "DROP INDEX IF EXISTS idx_corpus_sources_tenant_client_path",
        "ALTER TABLE corpus_sources DROP CONSTRAINT IF EXISTS uq_corpus_sources_tenant_client_path",
        "ALTER TABLE corpus_sources ADD CONSTRAINT uq_corpus_sources_tenant_path UNIQUE (tenant_id, source_path)",
        "ALTER TABLE corpus_sources DROP COLUMN IF EXISTS client_id",
        "DROP INDEX IF EXISTS idx_outcomes_tenant_client_clause_outcome",
        "ALTER TABLE negotiation_outcomes DROP COLUMN IF EXISTS client_id",
        "DROP INDEX IF EXISTS idx_clause_records_tenant_client_clause_type",
        "ALTER TABLE clause_records DROP COLUMN IF EXISTS client_id",
        "DROP INDEX IF EXISTS idx_contract_documents_tenant_client",
        "ALTER TABLE contract_documents DROP COLUMN IF EXISTS client_id",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
