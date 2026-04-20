"""add alerts table (event-scoped early warning signals)

Revision ID: g1_add_alerts
Revises: f1_add_stock_transactions
Create Date: 2026-04-17

Creates the alerts table + three Postgres enums (alert_type, alert_severity,
alert_audience).

Alerts are the product's core signal: early warnings so the Owner discovers
operational problems before they become painful. The table is append-only
in spirit — rows are NEVER deleted during an event. Lifecycle transitions
(acknowledge, auto-resolve, expire) are captured as nullable timestamps so
the post-event report can reconstruct the full narrative of what happened
and who acted on it.

Design principles:

1. Multi-tenant isolation — every row carries tenant_id, every query
   filtered by tenant_id. Same pattern as all other modules.

2. Three native Postgres ENUMs (not free strings) —
   alert_type     : depletion | anomaly | discrepancy | system
   alert_severity : info | warning | critical | anomaly
   alert_audience : owner_only | owner_and_manager
   Same pattern as product_type, product_category, product_unit.

3. Deduplication key (logical, enforced in service layer, not DB) —
   (tenant_id, event_id, bar_id, product_id, alert_type) has at most ONE
   active (acknowledged_at IS NULL AND auto_resolved_at IS NULL AND
   expired_at IS NULL) row at a time. The service checks before insert
   and updates context/severity on the existing active row instead of
   flooding the Owner with duplicates.

4. Split messaging for owner vs manager —
   owner_message (NOT NULL)     : detailed text, numbers, the WHY
   manager_message (nullable)   : sanitized operational text, or NULL
                                  when audience=owner_only (anomaly)
   Enforces the Architecture Bible rule that managers never see anomaly
   details — physically impossible to leak via DB.

5. JSONB context — each detector documents its own schema for the
   context_json column. Extensible without migrations.

6. AI-advisor forward slot — ai_advisory column is nullable. A future
   LLM advisor populates it with historical reasoning; frontend already
   reads the slot. Zero schema churn at upgrade time.

7. Lifecycle timestamps as append-only narrative —
   created_at        : when fired
   acknowledged_at   : when Owner clicked ack (NULL = still active)
   auto_resolved_at  : when condition stopped applying on its own
   expired_at        : when event ended while alert still unresolved
   Reports read this to tell Omar: "X alerts fired, Y resolved, Z timed
   out, W you acknowledged."

8. Optimistic locking via version column — same pattern as Events
   module. Prevents double-ack race from two Owner tabs.

9. Three indexes —
   ix_alerts_tenant_event_active : hot path "what's active right now"
   ix_alerts_dedup_key            : dedup lookup before insert
   ix_alerts_tenant_event_bar     : per-bar drill-down in overlay
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "g1_add_alerts"
down_revision = "f1_add_stock_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create the three native Postgres ENUM types ──
    # create_type=True here (the default) — these are brand-new types.
    # The ORM-level SqlEnum uses create_type=False so it doesn't try
    # to recreate them when ORM metadata is emitted.

    alert_type_enum = postgresql.ENUM(
        "depletion",
        "anomaly",
        "discrepancy",
        "system",
        name="alert_type",
    )
    alert_type_enum.create(op.get_bind(), checkfirst=True)

    alert_severity_enum = postgresql.ENUM(
        "info",
        "warning",
        "critical",
        "anomaly",
        name="alert_severity",
    )
    alert_severity_enum.create(op.get_bind(), checkfirst=True)

    alert_audience_enum = postgresql.ENUM(
        "owner_only",
        "owner_and_manager",
        name="alert_audience",
    )
    alert_audience_enum.create(op.get_bind(), checkfirst=True)

    # ── 2. Create the alerts table ──
    op.create_table(
        "alerts",
        # Identity & tenancy
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Scope
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Classification — reference the enum types by name (already created)
        sa.Column(
            "alert_type",
            postgresql.ENUM(name="alert_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "severity",
            postgresql.ENUM(name="alert_severity", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "audience",
            postgresql.ENUM(name="alert_audience", create_type=False),
            nullable=False,
        ),
        # Display content
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("owner_message", sa.Text(), nullable=False),
        sa.Column("manager_message", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("ai_advisory", sa.Text(), nullable=True),
        # Detector context
        sa.Column(
            "context_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Lifecycle
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "acknowledged_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "auto_resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "expired_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # Concurrency
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    # ── 3. Indexes ──
    # Hot path: "what's active right now for this event"
    op.create_index(
        "ix_alerts_tenant_event_active",
        "alerts",
        ["tenant_id", "event_id", "created_at"],
    )
    # Dedup key: before insert, look up active row with this combination
    op.create_index(
        "ix_alerts_dedup_key",
        "alerts",
        ["tenant_id", "event_id", "bar_id", "product_id", "alert_type"],
    )
    # Per-bar drill-down in BarDetailOverlay
    op.create_index(
        "ix_alerts_tenant_event_bar",
        "alerts",
        ["tenant_id", "event_id", "bar_id"],
    )


def downgrade() -> None:
    # Reverse order: indexes → table → enum types.
    op.drop_index("ix_alerts_tenant_event_bar", table_name="alerts")
    op.drop_index("ix_alerts_dedup_key", table_name="alerts")
    op.drop_index("ix_alerts_tenant_event_active", table_name="alerts")
    op.drop_table("alerts")

    # Drop enum types. Safe because only this table uses them.
    sa.Enum(name="alert_audience").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="alert_severity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="alert_type").drop(op.get_bind(), checkfirst=True)