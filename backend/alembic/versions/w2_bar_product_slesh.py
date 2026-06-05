"""w2 — bar + product Slesh extensions (device_count, IVA, cauzione).

Adds Slesh-aligned columns to bars and products (Phase B w2):

  bars.device_count          int   nullable  -- POS devices at this bar
  bars.slesh_category        str   nullable  -- Slesh-side category label
                                                ("Panineria"/"Bar"/etc.
                                                 Distinct from bar_type
                                                 which is XProject-native.)

  products.iva_pct           num   nullable  -- VAT rate, e.g. 0.100 = 10%
  products.cauzione_cents    int   nullable  -- Deposit in cents (e.g.
                                                100 = €1 for bicchiere).
                                                NULL = no deposit.

All nullable; existing rows unaffected. Reversible (downgrade
drops all 4 columns).

Mirrors Omar's "Project Plan - Cashless" Excel sheets 3 (Device
Count) and 4 (Listini Bar with Categoria/Iva/Cauzione cols).
Spec: docs/sundance-1-setup-plan.md, Phase B.
"""
from alembic import op
import sqlalchemy as sa


revision = "w2_bar_product_slesh"
down_revision = "w1_event_slesh_ext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bars",
        sa.Column("device_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bars",
        sa.Column("slesh_category", sa.String(40), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("iva_pct", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("cauzione_cents", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "cauzione_cents")
    op.drop_column("products", "iva_pct")
    op.drop_column("bars", "slesh_category")
    op.drop_column("bars", "device_count")
