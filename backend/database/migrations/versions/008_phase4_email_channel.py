"""Phase 4: email notification channel on notification_subscriptions

Revision ID: 008_phase4_email_channel
Revises: 007_phase3_applications
Create Date: 2026-06-09

Adds the email notification channel ALONGSIDE the existing Telegram channel by
adding two nullable/defaulted columns to the existing
``notification_subscriptions`` table:

  - ``email``         (VARCHAR(320), NULLABLE)  — optional destination address.
  - ``email_enabled`` (BOOLEAN, NOT NULL, server_default TRUE) — lets a
                       subscriber mute email while keeping the address on file.

This is the only schema change Phase 4 owns. It is purely additive: no existing
column is altered or dropped, no new table is created, and the existing Telegram
columns are untouched. Reversible: downgrade drops ONLY the two Phase-4 columns.

The ``email_enabled`` server_default TRUE backfills existing rows safely (so the
NOT NULL constraint is satisfiable on a non-empty table without a data step).
"""
from alembic import op
import sqlalchemy as sa

revision = '008_phase4_email_channel'
down_revision = '007_phase3_applications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'notification_subscriptions',
        sa.Column('email', sa.String(length=320), nullable=True),
    )
    op.add_column(
        'notification_subscriptions',
        sa.Column(
            'email_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    # Drop ONLY the Phase-4-owned columns.
    op.drop_column('notification_subscriptions', 'email_enabled')
    op.drop_column('notification_subscriptions', 'email')
