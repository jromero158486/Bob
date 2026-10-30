"""rebuild PostgreSQL indexes after the server image changed C library (postgres:16-alpine/musl -> pgvector:pg16/glibc)

Text btree indexes built under musl collation order are not valid under glibc; lookups through them (including
foreign-key checks on uq_passages_patient_passage) silently miss rows. Rebuilding is cheap at this data size and
harmless on fresh databases.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for (table,) in bind.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).all():
        op.execute(f'REINDEX TABLE "{table}"')
    # No REFRESH COLLATION VERSION: musl records no version, and PostgreSQL rejects changing an empty one.


def downgrade() -> None:
    pass
