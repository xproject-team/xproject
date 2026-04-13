"""add indexes to bars table

Revision ID: a2_add_bars_idx
Revises: a1_add_bars
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a2_add_bars_idx'
down_revision: Union[str, None] = 'a1_add_bars'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ix_bars_tenant_id already exists — auto-created by TenantScopedModel's
    # index=True declaration on tenant_id during the a1 create_table.
    op.create_index('ix_bars_event_id', 'bars', ['event_id'])
    op.create_index('ix_bars_slesh_negozio_id', 'bars', ['slesh_negozio_id'])


def downgrade() -> None:
    op.drop_index('ix_bars_slesh_negozio_id', table_name='bars')
    op.drop_index('ix_bars_event_id', table_name='bars')
