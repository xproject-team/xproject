"""add tenant_id indexes to chat tables

Revision ID: a5_chat_tenant_idx
Revises: a4_add_chat
Create Date: 2026-04-13

These indexes were expected to be auto-created via TenantScopedModel's
index=True on tenant_id, but op.create_table() does not honor that —
indexes only get created when the model is reflected through SQLAlchemy
metadata, not when the migration uses raw op.create_table.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a5_chat_tenant_idx'
down_revision: Union[str, None] = 'a4_add_chat'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_channels_tenant_id',         'channels',         ['tenant_id'])
    op.create_index('ix_channel_members_tenant_id',  'channel_members',  ['tenant_id'])
    op.create_index('ix_chat_messages_tenant_id',    'chat_messages',    ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_chat_messages_tenant_id',   table_name='chat_messages')
    op.drop_index('ix_channel_members_tenant_id', table_name='channel_members')
    op.drop_index('ix_channels_tenant_id',        table_name='channels')
