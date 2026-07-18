"""alerts.bar_id — allow NULL for bar-less alerts (unmapped-shop).

Revision ID: aa9
Revises: aa8
Create Date: 2026-07-17

The phantom-bar defensive fix (migration aa8) needs to fire an alert for
"unknown Slesh shop_id, no matching bar" — by definition there is no bar
to attach it to. alerts.bar_id was NOT NULL, blocking this outright.

alerts.bar_id is also part of the application-level dedup key in
AlertsService.create_alert() (tenant, event, bar_id, product_id,
alert_type) — SQLAlchemy's `Column == None` already compiles to `IS
NULL`, so NULL-bar_id alerts dedup correctly against each other without
any query changes there. (In practice, the unmapped-shop alert bypasses
create_alert()'s dedup anyway — see pending_shop_mappings_service.py —
because that key can't discriminate between two different unmapped
shop_ids in the same event; the same problem already exists for
supplier_product-scoped depletion alerts, solved there the same way,
see app/modules/event_storage/bar_supplier_stock_service.py.)
"""
from alembic import op


revision = "aa9"
down_revision = "aa8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("alerts", "bar_id", nullable=True)


def downgrade() -> None:
    op.alter_column("alerts", "bar_id", nullable=False)
