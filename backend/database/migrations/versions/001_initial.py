"""Initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(128), nullable=False),
        sa.Column('hashed_password', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )

    op.create_table(
        'grants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('organization', sa.String(512), nullable=True),
        sa.Column('country', sa.String(256), nullable=True),
        sa.Column('category', sa.String(256), nullable=True),
        sa.Column('deadline', sa.Date(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('ai_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('telegram_msg_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_url'),
    )

    op.create_table(
        'reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('grant_id', sa.Integer(), nullable=False),
        sa.Column('reviewer_name', sa.String(256), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['grant_id'], ['grants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'grant_features',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('grant_id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(256), nullable=False),
        sa.Column('category', sa.String(256), nullable=True),
        sa.Column('country', sa.String(256), nullable=True),
        sa.Column('score_delta', sa.Float(), nullable=False, server_default='0.0'),
        sa.ForeignKeyConstraint(['grant_id'], ['grants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Index for fast status filtering
    op.create_index('ix_grants_status', 'grants', ['status'])
    op.create_index('ix_grants_deadline', 'grants', ['deadline'])
    op.create_index('ix_grants_ai_score', 'grants', ['ai_score'])


def downgrade() -> None:
    op.drop_index('ix_grants_ai_score', 'grants')
    op.drop_index('ix_grants_deadline', 'grants')
    op.drop_index('ix_grants_status', 'grants')
    op.drop_table('grant_features')
    op.drop_table('reviews')
    op.drop_table('grants')
    op.drop_table('users')
