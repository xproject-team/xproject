"""add chat_mentions table

Revision ID: a6_add_mentions
Revises: a5_chat_tenant_idx
Create Date: 2026-04-14

Each row = one user mentioned in one message.
A message can have N mentions. A mention can be read or unread
(read_at NULL = unread).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a6_add_mentions'
down_revision: Union[str, None] = 'a5_chat_tenant_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_mentions',
        # Inherited from TenantScopedModel
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        # Mention-specific
        sa.Column('message_id', UUID(as_uuid=True),
                  sa.ForeignKey('chat_messages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('message_id', 'user_id',
                            name='uq_chat_mentions_message_user'),
    )

    # Indexes: one message has N mentions → fast lookup by message_id
    # One user has many mentions → fast lookup + unread filter
    op.create_index('ix_chat_mentions_tenant_id',  'chat_mentions', ['tenant_id'])
    op.create_index('ix_chat_mentions_message_id', 'chat_mentions', ['message_id'])
    op.create_index('ix_chat_mentions_user_id',    'chat_mentions', ['user_id'])
    # Composite for "unread mentions for user X"
    op.create_index(
        'ix_chat_mentions_user_unread',
        'chat_mentions',
        ['user_id'],
        postgresql_where=sa.text('read_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_table('chat_mentions')
