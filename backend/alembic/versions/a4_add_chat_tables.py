"""add chat tables: channels, channel_members, chat_messages

Revision ID: a4_add_chat
Revises: a3_add_user_bar
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a4_add_chat'
down_revision: Union[str, None] = 'a3_add_user_bar'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── channels ─────────────────────────────────────────────────────
    op.create_table(
        'channels',
        # Inherited from TenantScopedModel
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        # Channel-specific
        sa.Column('channel_type', sa.String(length=32), nullable=False),
        sa.Column('bar_id', UUID(as_uuid=True),
                  sa.ForeignKey('bars.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
    )
    op.create_index('ix_channels_channel_type', 'channels', ['channel_type'])
    op.create_index('ix_channels_bar_id',      'channels', ['bar_id'])

    # ─── channel_members ──────────────────────────────────────────────
    op.create_table(
        'channel_members',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('channel_id', UUID(as_uuid=True),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('channel_id', 'user_id',
                            name='uq_channel_members_channel_user'),
    )
    op.create_index('ix_channel_members_channel_id', 'channel_members', ['channel_id'])
    op.create_index('ix_channel_members_user_id',    'channel_members', ['user_id'])

    # ─── chat_messages ────────────────────────────────────────────────
    op.create_table(
        'chat_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('channel_id', UUID(as_uuid=True),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('sender_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_chat_messages_channel_id', 'chat_messages', ['channel_id'])
    op.create_index('ix_chat_messages_sender_id',  'chat_messages', ['sender_id'])
    # Composite index for "load latest N messages for channel"
    op.create_index(
        'ix_chat_messages_channel_created',
        'chat_messages',
        ['channel_id', sa.text('created_at DESC')],
    )


def downgrade() -> None:
    op.drop_table('chat_messages')
    op.drop_table('channel_members')
    op.drop_table('channels')
