"""Add notification_subscriptions table

Revision ID: 002_notif_sub
Revises: 001_initial
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa


revision = '002_notif_sub'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notification_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_user_id'),
    )


def downgrade() -> None:
    op.drop_table('notification_subscriptions')
