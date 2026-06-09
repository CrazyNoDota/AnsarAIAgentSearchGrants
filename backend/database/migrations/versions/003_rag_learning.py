"""RAG + Learning System: pgvector embeddings, user preferences, search logs, new grant fields

Revision ID: 003_rag_learning
Revises: 002_notif_sub
Create Date: 2026-05-11

New tables:
  - grant_embeddings: vector (1024-dim) embeddings for semantic search
  - user_preferences: learned approval/rejection patterns
  - search_logs: query history

New columns on grants:
  - grant_amount, eligibility, industry, startup_stage, application_url
  - confidence_score, embedding_status
"""
from alembic import op
import sqlalchemy as sa

revision = '003_rag_learning'
down_revision = '002_notif_sub'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension is available (may already exist from init_db.sql)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── Add new columns to grants table ───────────────────────
    op.add_column('grants', sa.Column('grant_amount', sa.String(256), nullable=True))
    op.add_column('grants', sa.Column('eligibility', sa.Text(), nullable=True))
    op.add_column('grants', sa.Column('industry', sa.String(256), nullable=True))
    op.add_column('grants', sa.Column('startup_stage', sa.String(128), nullable=True))
    op.add_column('grants', sa.Column('application_url', sa.Text(), nullable=True))
    op.add_column('grants', sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.85'))
    op.add_column('grants', sa.Column('embedding_status', sa.String(32), nullable=False, server_default='pending'))

    op.create_index('ix_grants_embedding_status', 'grants', ['embedding_status'])
    op.create_index('ix_grants_country', 'grants', ['country'])
    op.create_index('ix_grants_category', 'grants', ['category'])

    # ── Grant embeddings table ─────────────────────────────────
    # Stores vector embeddings for RAG semantic search
    op.create_table(
        'grant_embeddings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('grant_id', sa.Integer(), nullable=False),
        sa.Column('chunk_type', sa.String(50), nullable=False),  # 'summary', 'eligibility', 'full'
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['grant_id'], ['grants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add vector(1024) column using raw SQL (pgvector type not natively in SQLAlchemy)
    op.execute("ALTER TABLE grant_embeddings ADD COLUMN embedding vector(1024)")

    # IVFFlat index for fast approximate nearest-neighbor search (cosine distance)
    op.execute(
        "CREATE INDEX ix_grant_embeddings_vector "
        "ON grant_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.create_index('ix_grant_embeddings_grant_id', 'grant_embeddings', ['grant_id'])
    op.create_index('ix_grant_embeddings_chunk_type', 'grant_embeddings', ['chunk_type'])

    # ── User preferences table ─────────────────────────────────
    # Stores AI learning data from Aydar's approval/rejection decisions
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('preference_type', sa.String(50), nullable=False),   # 'category', 'country', 'keyword', 'industry'
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('approved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejected_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('preference_type', 'value', name='uq_pref_type_value'),
    )
    op.create_index('ix_user_preferences_type', 'user_preferences', ['preference_type'])

    # ── Search logs table ─────────────────────────────────────
    op.create_table(
        'search_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('user_id', sa.String(50), nullable=True),
        sa.Column('results_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('search_type', sa.String(32), nullable=True),  # 'semantic', 'keyword', 'hybrid'
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_search_logs_created_at', 'search_logs', ['created_at'])


def downgrade() -> None:
    op.drop_table('search_logs')
    op.drop_table('user_preferences')
    op.drop_table('grant_embeddings')
    op.drop_index('ix_grants_category', 'grants')
    op.drop_index('ix_grants_country', 'grants')
    op.drop_index('ix_grants_embedding_status', 'grants')
    op.drop_column('grants', 'embedding_status')
    op.drop_column('grants', 'confidence_score')
    op.drop_column('grants', 'application_url')
    op.drop_column('grants', 'startup_stage')
    op.drop_column('grants', 'industry')
    op.drop_column('grants', 'eligibility')
    op.drop_column('grants', 'grant_amount')
