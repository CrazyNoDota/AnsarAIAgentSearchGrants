"""Phase 2: company/project profiles for grant fit matching

Revision ID: 005_phase2_profiles
Revises: 004_phase1_filters
Create Date: 2026-06-09

Adds ONE new table, `company_profiles`, plus two helper indexes. This is the
only object Phase 2 owns at the schema level — the fit/match engine compares
these profiles against the EXISTING Phase-1 grant fields (industry / region /
budget_min / budget_max / startup_stage / deadline) and the EXISTING
`grant_embeddings` pgvector table, so no pre-existing column, table, or index
is created, altered, or dropped here.

Reversible: downgrade drops only the Phase-2-owned table + indexes.
"""
from alembic import op
import sqlalchemy as sa

revision = '005_phase2_profiles'
down_revision = '004_phase1_filters'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'company_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('industry', sa.String(256), nullable=True),
        sa.Column('stage', sa.String(128), nullable=True),
        sa.Column('region', sa.String(128), nullable=True),
        sa.Column('country', sa.String(256), nullable=True),
        sa.Column('funding_amount_sought', sa.Numeric(18, 2), nullable=True),
        sa.Column('currency', sa.String(8), nullable=True),
        sa.Column('team_size', sa.Integer(), nullable=True),
        sa.Column('organization_type', sa.String(128), nullable=True),
        sa.Column('keywords', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('past_funding', sa.Numeric(18, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_company_profiles_industry', 'company_profiles', ['industry'])
    op.create_index('ix_company_profiles_region', 'company_profiles', ['region'])


def downgrade() -> None:
    # Drop ONLY Phase-2-owned objects.
    op.drop_index('ix_company_profiles_region', 'company_profiles')
    op.drop_index('ix_company_profiles_industry', 'company_profiles')
    op.drop_table('company_profiles')
