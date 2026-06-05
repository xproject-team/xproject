"""w1 — event Slesh extensions (Stripe, top-ups, refunds, wristbands).

Adds 9 nullable columns to the events table mirroring Omar's official
Slesh "Project Plan - Cashless" template (sheets 1 + 2):
  - stripe_ragione_sociale (legal entity name for Stripe payments)
  - staff_arrival_time (TIME, separate from event hours)
  - wristband_qty_per_type (JSONB: quantities per wristband type)
  - topup_denominations_user (JSONB array of cent values)
  - topup_denominations_staff (JSONB array of cent values)
  - refund_min_credit_cents (minimum credit balance to request refund)
  - refund_fee_cents (handling fee deducted from refund)
  - refund_window_open_at / close_at (when refunds can be requested)

All NULL-safe; existing Sundance 2026 event row stays intact.
Reversible (downgrade drops all 9 columns).

Spec: docs/sundance-1-setup-plan.md, Phase B.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "w1_event_slesh_ext"
down_revision = "v1_add_shop_match_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("stripe_ragione_sociale", sa.String(255), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("staff_arrival_time", sa.Time(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("wristband_qty_per_type", JSONB, nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("topup_denominations_user", JSONB, nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("topup_denominations_staff", JSONB, nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("refund_min_credit_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("refund_fee_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column(
            "refund_window_open_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "refund_window_close_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "refund_window_close_at")
    op.drop_column("events", "refund_window_open_at")
    op.drop_column("events", "refund_fee_cents")
    op.drop_column("events", "refund_min_credit_cents")
    op.drop_column("events", "topup_denominations_staff")
    op.drop_column("events", "topup_denominations_user")
    op.drop_column("events", "wristband_qty_per_type")
    op.drop_column("events", "staff_arrival_time")
    op.drop_column("events", "stripe_ragione_sociale")
