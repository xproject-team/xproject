"""pending_shop_mappings — real-time defensive fix for the phantom-bar bug.

Revision ID: aa8
Revises: aa7
Create Date: 2026-07-17

Root cause of the Sundance Jul-5 phantom-bar incidents: three food
trucks (Twist & Chips, Focacceria Romana, Gastronomade Bistrot) came
online mid-event with no slesh_negozio_id set on their bars. The first
order from each unmapped shop_id caused order_ingester._resolve_bar to
silently auto-create a phantom bar (see order_ingester.py). Omar had to
manually SQL-merge phantoms into the real bars three times during the
event.

This table parks orders for an unmapped shop_id instead of auto-creating
a bar. The operator resolves via POST .../pending-shop-mappings/{id}/resolve,
which sets the target bar's slesh_negozio_id and replays every parked
order through the normal ingestion path.

Deviation from the literal spec: added parked_orders_json (JSONB array of
raw Slesh order payloads). Neither of the two storage options in the
spec actually work — stock_transactions.bar_id is NOT NULL (can't write
a transaction with no bar), and the spec's pending_shop_mappings columns
only carry aggregate counters (order_count, total_gross_cents), not the
replayable order data itself. Without storing the raw orders, "replay
parked orders into it" (the resolve endpoint's core job) would have
nothing to replay. Storing raw Order JSON (round-trips via the existing
pydantic Order schema) reuses this one new table rather than adding a
second one, in the spirit of "do not invent a new table for parked
orders if the existing schema can accommodate this."

Note: this is a distinct, separate system from slesh_shop_match_proposals
(migration v1) — that one is populated by the hourly sync_shops() cron
using fuzzy name-matching against Slesh's shop *list*; this one is
populated by the real-time ingester the moment an *order* arrives for an
unmapped shop_id, which is the only way to catch a shop appearing mid-
event before the next hourly sync tick. See docs cross-reference in
app/modules/pos/models.py.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "aa8"
down_revision = "aa7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_shop_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),

        sa.Column("slesh_shop_id", sa.String(128), nullable=False),

        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("order_count", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("total_gross_cents", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("sample_operator_email", sa.String(255), nullable=True),

        # Raw Slesh order payloads (see module docstring) — replayed via
        # ingest_order() once the shop_id is resolved to a bar.
        sa.Column("parked_orders_json", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),

        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_bar_id", postgresql.UUID(as_uuid=True), nullable=True),

        # TenantScopedModel's base columns (see app/core/tenancy.py) —
        # every tenant-scoped table needs these explicitly in the migration.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_bar_id"], ["bars.id"], ondelete="SET NULL"),
    )

    # One PENDING (unresolved) row per (tenant, event, shop_id). Once
    # resolved, the shop_id may re-park under a NEW row if it somehow
    # goes unmapped again (bar deleted, slesh_negozio_id cleared, etc.)
    # — the partial WHERE clause means only unresolved rows compete for
    # this uniqueness.
    op.create_index(
        "uq_pending_shop_mappings_tenant_event_shop_unresolved",
        "pending_shop_mappings",
        ["tenant_id", "event_id", "slesh_shop_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    # Hot path: list unresolved mappings for an event's alert / approval UI.
    op.create_index(
        "ix_pending_shop_mappings_event",
        "pending_shop_mappings",
        ["tenant_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pending_shop_mappings_event", table_name="pending_shop_mappings")
    op.drop_index(
        "uq_pending_shop_mappings_tenant_event_shop_unresolved",
        table_name="pending_shop_mappings",
    )
    op.drop_table("pending_shop_mappings")
