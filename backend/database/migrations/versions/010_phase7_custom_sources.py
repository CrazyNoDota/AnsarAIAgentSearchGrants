"""Phase 7: user-registered custom grant sources

Revision ID: 010_phase7_custom_sources
Revises: 009_phase5_knowledge_base
Create Date: 2026-06-09

Adds the ``custom_sources`` table — arbitrary grant/funding listing URLs an
operator registers from the Telegram bot (``/addsource``). Each cycle (and on
demand) the page is fetched and run through the AdaptiveParser; extracted grants
land in the existing ``grants`` table, so no change to grant storage is needed.

Purely additive: one NEW table + a unique index on ``url``. Reversible — the
downgrade drops only this table.
"""
from alembic import op
import sqlalchemy as sa

revision = '010_phase7_custom_sources'
down_revision = '009_phase5_knowledge_base'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'custom_sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('url', sa.String(2000), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('country', sa.String(255), nullable=True),
        sa.Column('added_by', sa.String(128), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_scraped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(32), nullable=True),
        sa.Column('last_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_custom_sources_url', 'custom_sources', ['url'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_custom_sources_url', 'custom_sources')
    op.drop_table('custom_sources')
