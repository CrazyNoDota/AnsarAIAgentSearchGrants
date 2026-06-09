"""Phase 2 follow-up: scope company_profiles to their owning user

Revision ID: 006_profile_user_scope
Revises: 005_phase2_profiles
Create Date: 2026-06-09

Adds an owner column `user_id` (FK -> users.id, ON DELETE CASCADE) plus an
index to the Phase-2 `company_profiles` table so profiles are private to the
user who created them. Closes a data-isolation gap where any authenticated user
could read/update/delete every profile.

`company_profiles` is introduced in the immediately preceding revision (005) and
is empty until this release is deployed, so the NOT NULL column needs no
backfill. This migration only ADDS Phase-2-owned objects; it does not touch any
pre-existing table/column. Reversible: downgrade drops only what it added.
"""
from alembic import op
import sqlalchemy as sa

revision = '006_profile_user_scope'
down_revision = '005_phase2_profiles'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'company_profiles',
        sa.Column('user_id', sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        'fk_company_profiles_user_id',
        'company_profiles', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_company_profiles_user_id', 'company_profiles', ['user_id'])


def downgrade() -> None:
    # Drop ONLY the objects this revision added.
    op.drop_index('ix_company_profiles_user_id', 'company_profiles')
    op.drop_constraint('fk_company_profiles_user_id', 'company_profiles', type_='foreignkey')
    op.drop_column('company_profiles', 'user_id')
