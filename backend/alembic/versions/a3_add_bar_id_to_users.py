"""add bar_id to users

Revision ID: a3_add_user_bar
Revises: a2_add_bars_idx
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a3_add_user_bar'
down_revision: Union[str, None] = 'a2_add_bars_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable bar_id column with FK to bars.id (SET NULL on bar deletion)
    op.add_column(
        'users',
        sa.Column('bar_id', UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_users_bar_id_bars',
        'users',
        'bars',
        ['bar_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_users_bar_id', 'users', ['bar_id'])


def downgrade() -> None:
    op.drop_index('ix_users_bar_id', table_name='users')
    op.drop_constraint('fk_users_bar_id_bars', 'users', type_='foreignkey')
    op.drop_column('users', 'bar_id')
