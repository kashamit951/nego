"""initial multi-tenant schema with RLS

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-12 00:00:00
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sql_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sql" / "001_multi_tenant_rls.sql"


def upgrade() -> None:
    sql_blob = _sql_path().read_text(encoding="utf-8")
    bind = op.get_bind()
    statements = [stmt.strip() for stmt in sql_blob.split(";") if stmt.strip()]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    drop_statements = [
        "DROP TABLE IF EXISTS audit_logs CASCADE",
        "DROP TABLE IF EXISTS api_credentials CASCADE",
        "DROP TABLE IF EXISTS tenant_users CASCADE",
        "DROP TABLE IF EXISTS negotiation_outcomes CASCADE",
        "DROP TABLE IF EXISTS clause_records CASCADE",
        "DROP TABLE IF EXISTS contract_documents CASCADE",
    ]
    for statement in drop_statements:
        bind.exec_driver_sql(statement)
