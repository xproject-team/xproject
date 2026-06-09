"""x2 — auto_created flag on bars (no-data-loss for unmapped Slesh shops)."""
from alembic import op
import sqlalchemy as sa


revision = "x2_auto_created_bars"
down_revision = "x1_food_kpi_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bars",
        sa.Column(
            "auto_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("bars", "auto_created")
