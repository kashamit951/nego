"""add corpus management schema

Revision ID: 0002_corpus
Revises: 0001_initial
Create Date: 2026-02-12 00:10:00
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_corpus"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sql_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sql" / "002_corpus_management.sql"


def upgrade() -> None:
    sql_blob = _sql_path().read_text(encoding="utf-8")
    bind = op.get_bind()
    statements = [stmt.strip() for stmt in sql_blob.split(";") if stmt.strip()]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in [
        "DROP TABLE IF EXISTS corpus_files CASCADE",
        "DROP TABLE IF EXISTS corpus_sources CASCADE",
    ]:
        bind.exec_driver_sql(statement)
