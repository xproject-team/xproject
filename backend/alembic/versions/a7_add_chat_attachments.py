"""add chat_attachments table

Revision ID: a7_add_attachments
Revises: a6_add_mentions
Create Date: 2026-04-14

Each row = one file attached to one chat message. A message can have N
attachments (images, PDFs, etc). Files live in MinIO; this table only
holds the metadata: object key, original filename, MIME type, size.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a7_add_attachments'
down_revision: Union[str, None] = 'a6_add_mentions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_attachments',
        # Inherited from TenantScopedModel
        sa.Column('id',         UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id',  UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        # Attachment-specific
        sa.Column('message_id', UUID(as_uuid=True),
                  sa.ForeignKey('chat_messages.id', ondelete='CASCADE'),
                  nullable=True),                               # nullable: pre-attach
        sa.Column('uploaded_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('object_key',        sa.String(512), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('content_type',      sa.String(127), nullable=False),
        sa.Column('size_bytes',        sa.BigInteger(), nullable=False),
    )

    # Indexes
    op.create_index('ix_chat_attachments_tenant_id',  'chat_attachments', ['tenant_id'])
    op.create_index('ix_chat_attachments_message_id', 'chat_attachments', ['message_id'])
    # Unique key constraint on object_key (no two rows can point to the same blob)
    op.create_unique_constraint(
        'uq_chat_attachments_object_key', 'chat_attachments', ['object_key'],
    )


def downgrade() -> None:
    op.drop_table('chat_attachments')
