"""Phase 5: knowledge base (past applications, cases, templates, submissions)

Revision ID: 009_phase5_knowledge_base
Revises: 008_phase4_email_channel
Create Date: 2026-06-09

Adds the Phase-5 knowledge base used by the AI consultant to ground advice in a
user's prior grant work. Two NEW objects, both owned by the creating user:

  - ``knowledge_entries``    — one row per knowledge item (kind = past_application
                               | successful_case | template | submission). NOT
                               NULL user_id FK -> users.id ON DELETE CASCADE;
                               optional package_id/grant_id FKs ON DELETE SET NULL
                               so an entry survives deletion of its source rows.
  - ``knowledge_embeddings`` — pgvector embeddings of each entry's search text for
                               semantic retrieval (mirrors ``grant_embeddings``).
                               The ``embedding`` column is ``vector(1024)`` and is
                               created via raw SQL (pgvector type), exactly like
                               the existing grant_embeddings table.

This is purely additive: no pre-existing table, column or index is altered or
dropped. Reversible: downgrade drops ONLY the two Phase-5-owned tables (and their
indexes). The ``vector`` extension is assumed already present (created with
grant_embeddings in the initial migration); it is NOT created or dropped here.
"""
from alembic import op
import sqlalchemy as sa

revision = '009_phase5_knowledge_base'
down_revision = '008_phase4_email_channel'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'knowledge_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('outcome', sa.String(32), nullable=True),
        sa.Column('package_id', sa.Integer(), nullable=True),
        sa.Column('grant_id', sa.Integer(), nullable=True),
        sa.Column('funder', sa.Text(), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column(
            'embedding_status', sa.String(32), nullable=False,
            server_default='pending',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['package_id'], ['application_packages.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['grant_id'], ['grants.id'], ondelete='SET NULL'),
    )
    op.create_index(
        'ix_knowledge_entries_user_id', 'knowledge_entries', ['user_id']
    )
    op.create_index(
        'ix_knowledge_entries_kind', 'knowledge_entries', ['kind']
    )

    # Embeddings table — the embedding column is the pgvector type, created via
    # raw SQL exactly like grant_embeddings (SQLAlchemy has no native vector
    # type here). The `vector` extension is assumed already enabled.
    op.create_table(
        'knowledge_embeddings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entry_id', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['entry_id'], ['knowledge_entries.id'], ondelete='CASCADE'
        ),
    )
    op.add_column(
        'knowledge_embeddings',
        sa.Column('embedding', sa.Text(), nullable=True),
    )
    # Replace the placeholder text column with a real pgvector column.
    op.execute('ALTER TABLE knowledge_embeddings DROP COLUMN embedding')
    op.execute('ALTER TABLE knowledge_embeddings ADD COLUMN embedding vector(1024)')
    op.execute(
        'CREATE INDEX ix_knowledge_embeddings_vector '
        'ON knowledge_embeddings USING ivfflat (embedding vector_cosine_ops) '
        'WITH (lists = 100)'
    )
    op.create_index(
        'ix_knowledge_embeddings_entry_id', 'knowledge_embeddings', ['entry_id']
    )


def downgrade() -> None:
    # Drop ONLY the Phase-5-owned objects (extension left intact).
    op.drop_index('ix_knowledge_embeddings_vector', 'knowledge_embeddings')
    op.drop_index('ix_knowledge_embeddings_entry_id', 'knowledge_embeddings')
    op.drop_table('knowledge_embeddings')
    op.drop_index('ix_knowledge_entries_kind', 'knowledge_entries')
    op.drop_index('ix_knowledge_entries_user_id', 'knowledge_entries')
    op.drop_table('knowledge_entries')
