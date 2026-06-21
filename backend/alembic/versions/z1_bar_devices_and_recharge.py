"""z1 add bar_devices, recharge_stations, recharge_devices, ricarica_transactions

Adds the device and ricarica data model needed for per-device dashboard
KPIs and ricarica (wristband top-up) tracking. All four tables are
event-scoped — configuration is set in the Create Event wizard and
locked once status transitions to LIVE.

Tables:
  bar_devices            POS device assigned to a bar (= 1 bartender or
                         helper). Joins to Slesh order data via
                         slesh_operator_id.
  recharge_stations      Stand-alone recharge desk at the event. Separate
                         from bars because ricarica is not a sales activity.
  recharge_devices       POS device at a recharge station, used for
                         wristband top-ups (Ss-ricarica-1 etc.).
  ricarica_transactions  Money loaded onto wristbands. Stores individual
                         transactions when available (source='api'), or
                         per-device-per-payment-method aggregates from
                         Slesh Excel exports (source='slesh_export').

Revision ID: z1_bar_devices_and_recharge
Revises: eo2_event_orders_timestamps
Create Date: 2026-06-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "z1_bar_devices_and_recharge"
down_revision = "eo2_event_orders_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bar_devices
    op.create_table(
        "bar_devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("bar_id", sa.UUID(), nullable=False),
        sa.Column("slesh_operator_id", sa.String(length=64), nullable=False),
        sa.Column("slesh_operator_email", sa.String(length=255), nullable=False),
        sa.Column("device_number", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False,
                  server_default=sa.text("'bartender'")),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bar_id"], ["bars.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "slesh_operator_id",
                            name="uq_bar_devices_event_operator"),
    )
    op.create_index("ix_bar_devices_tenant_id", "bar_devices", ["tenant_id"])
    op.create_index("ix_bar_devices_event_id", "bar_devices", ["event_id"])
    op.create_index("ix_bar_devices_bar_id", "bar_devices", ["bar_id"])
    op.create_index("ix_bar_devices_slesh_operator_id",
                    "bar_devices", ["slesh_operator_id"])

    # recharge_stations
    op.create_table(
        "recharge_stations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False,
                  server_default=sa.text("'Recharge Desk'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recharge_stations_tenant_id",
                    "recharge_stations", ["tenant_id"])
    op.create_index("ix_recharge_stations_event_id",
                    "recharge_stations", ["event_id"])

    # recharge_devices
    op.create_table(
        "recharge_devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("recharge_station_id", sa.UUID(), nullable=False),
        sa.Column("slesh_operator_id", sa.String(length=64), nullable=False),
        sa.Column("slesh_operator_email", sa.String(length=255), nullable=False),
        sa.Column("device_number", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False,
                  server_default=sa.text("'cashier'")),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recharge_station_id"],
                                ["recharge_stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "slesh_operator_id",
                            name="uq_recharge_devices_event_operator"),
    )
    op.create_index("ix_recharge_devices_tenant_id",
                    "recharge_devices", ["tenant_id"])
    op.create_index("ix_recharge_devices_event_id",
                    "recharge_devices", ["event_id"])
    op.create_index("ix_recharge_devices_station_id",
                    "recharge_devices", ["recharge_station_id"])

    # ricarica_transactions
    op.create_table(
        "ricarica_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("recharge_device_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("slesh_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("created_at_slesh", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recharge_device_id"],
                                ["recharge_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ricarica_transactions_tenant_id",
                    "ricarica_transactions", ["tenant_id"])
    op.create_index("ix_ricarica_transactions_event_id",
                    "ricarica_transactions", ["event_id"])
    op.create_index("ix_ricarica_transactions_device_id",
                    "ricarica_transactions", ["recharge_device_id"])


def downgrade() -> None:
    op.drop_index("ix_ricarica_transactions_device_id",
                  table_name="ricarica_transactions")
    op.drop_index("ix_ricarica_transactions_event_id",
                  table_name="ricarica_transactions")
    op.drop_index("ix_ricarica_transactions_tenant_id",
                  table_name="ricarica_transactions")
    op.drop_table("ricarica_transactions")

    op.drop_index("ix_recharge_devices_station_id",
                  table_name="recharge_devices")
    op.drop_index("ix_recharge_devices_event_id",
                  table_name="recharge_devices")
    op.drop_index("ix_recharge_devices_tenant_id",
                  table_name="recharge_devices")
    op.drop_table("recharge_devices")

    op.drop_index("ix_recharge_stations_event_id",
                  table_name="recharge_stations")
    op.drop_index("ix_recharge_stations_tenant_id",
                  table_name="recharge_stations")
    op.drop_table("recharge_stations")

    op.drop_index("ix_bar_devices_slesh_operator_id", table_name="bar_devices")
    op.drop_index("ix_bar_devices_bar_id", table_name="bar_devices")
    op.drop_index("ix_bar_devices_event_id", table_name="bar_devices")
    op.drop_index("ix_bar_devices_tenant_id", table_name="bar_devices")
    op.drop_table("bar_devices")
