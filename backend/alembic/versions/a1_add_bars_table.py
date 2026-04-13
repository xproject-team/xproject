"""add bars table

Revision ID: a1_add_bars
Revises: 960521bf64a4
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a1_add_bars'
down_revision: Union[str, None] = '960521bf64a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bars',
        # Inherited from TenantScopedModel
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            'tenant_id',
            UUID(as_uuid=True),
            sa.ForeignKey('tenants.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        # Bar-specific columns
        sa.Column(
            'event_id',
            UUID(as_uuid=True),
            sa.ForeignKey('events.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slesh_negozio_id', sa.String(length=128), nullable=True),
        sa.Column('bar_type', sa.String(length=32), nullable=False, server_default='drinks'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table('bars')
