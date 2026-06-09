"""Phase 1: structured filter fields on grants (budget / geo region)

Revision ID: 004_phase1_filters
Revises: 003_rag_learning
Create Date: 2026-06-08

Adds normalized filter columns used by budget/geo/industry filtering:
  - budget_min, budget_max (Numeric)  — parsed from grant_amount free-text
  - currency (e.g. 'USD', 'EUR', 'GBP')
  - region   — coarse geo bucket ('Europe', 'United Kingdom', 'Global', ...)

This migration only adds NEW Phase-1-owned objects. Pre-existing objects are
NOT touched here:
  - `deadline` (Date) already exists (001) and `ix_grants_deadline` is already
    created in 001 — we must NOT (re)create or drop it here, or the clean
    001->002->003->004 chain would fail / the downgrade would drop a
    non-Phase-1 index.
  - `industry` column already exists (003); only the index on it is new.

New indexes (Phase-1-owned): ix_grants_region, ix_grants_budget_max,
ix_grants_industry.
"""
from alembic import op
import sqlalchemy as sa

revision = '004_phase1_filters'
down_revision = '003_rag_learning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New Phase-1 columns.
    op.add_column('grants', sa.Column('budget_min', sa.Numeric(18, 2), nullable=True))
    op.add_column('grants', sa.Column('budget_max', sa.Numeric(18, 2), nullable=True))
    op.add_column('grants', sa.Column('currency', sa.String(8), nullable=True))
    op.add_column('grants', sa.Column('region', sa.String(128), nullable=True))

    # New Phase-1 indexes only. ix_grants_deadline already exists from 001 and
    # is intentionally NOT created here.
    op.create_index('ix_grants_region', 'grants', ['region'])
    op.create_index('ix_grants_budget_max', 'grants', ['budget_max'])
    op.create_index('ix_grants_industry', 'grants', ['industry'])


def downgrade() -> None:
    # Drop ONLY Phase-1-owned objects. Never drop ix_grants_deadline (owned by
    # 001) — the deadline column itself also predates Phase 1 and is left alone.
    op.drop_index('ix_grants_industry', 'grants')
    op.drop_index('ix_grants_budget_max', 'grants')
    op.drop_index('ix_grants_region', 'grants')
    op.drop_column('grants', 'region')
    op.drop_column('grants', 'currency')
    op.drop_column('grants', 'budget_max')
    op.drop_column('grants', 'budget_min')
