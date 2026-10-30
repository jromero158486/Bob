"""passage embeddings (BGE-M3 dense / sparse / multi-vector), optional pgvector column

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('passage_embeddings',
    sa.Column('patient_id', sa.String(length=128), nullable=False),
    sa.Column('passage_id', sa.String(length=320), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('model_revision', sa.String(length=64), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('dense', sa.JSON(), nullable=False),
    sa.Column('sparse', sa.JSON(), nullable=False),
    sa.Column('colbert', sa.LargeBinary(), nullable=True),
    sa.Column('colbert_tokens', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['patient_id', 'passage_id'], ['passages.patient_id', 'passages.passage_id'],
                            name='fk_embeddings_patient_passage', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('patient_id', 'passage_id', 'model'),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")).first():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("ALTER TABLE passage_embeddings ADD COLUMN dense_vec vector(1024)")


def downgrade() -> None:
    op.drop_table('passage_embeddings')
