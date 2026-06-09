"""Phase 3: generated application document packages

Revision ID: 007_phase3_applications
Revises: 006_profile_user_scope
Create Date: 2026-06-09

Adds ONE new table, `application_packages`, that stores generated grant-
application document packages (their drafted sections as JSON) for a user. It is
owned by the creating user (NOT NULL user_id FK -> users.id, ON DELETE CASCADE)
and references the source profile/grant with ON DELETE SET NULL so a generated
package survives deletion of its source rows.

This is the only object Phase 3 owns at the schema level; no pre-existing table,
column or index is created, altered or dropped here. Reversible: downgrade drops
only the Phase-3-owned table + index.
"""
from alembic import op
import sqlalchemy as sa

revision = '007_phase3_applications'
down_revision = '006_profile_user_scope'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'application_packages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=True),
        sa.Column('grant_id', sa.Integer(), nullable=True),
        sa.Column('grant_title', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='draft'),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['profile_id'], ['company_profiles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['grant_id'], ['grants.id'], ondelete='SET NULL'),
    )
    op.create_index(
        'ix_application_packages_user_id', 'application_packages', ['user_id']
    )


def downgrade() -> None:
    # Drop ONLY Phase-3-owned objects.
    op.drop_index('ix_application_packages_user_id', 'application_packages')
    op.drop_table('application_packages')
