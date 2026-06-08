"""x1 — food KPI fields: food_type enum + products.food_type + events.food_revenue_share_pct."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "x1_food_kpi_fields"
down_revision = "w3_device_count_notnull"
branch_labels = None
depends_on = None


FOOD_TYPE_VALUES = (
    "burgers",
    "sandwiches",
    "fried",
    "skewers",
    "pizza",
    "gelato",
    "other",
)


def upgrade() -> None:
    food_type_enum = postgresql.ENUM(
        *FOOD_TYPE_VALUES,
        name="food_type",
        create_type=False,
    )
    food_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "products",
        sa.Column("food_type", food_type_enum, nullable=True),
    )
    op.create_index("ix_products_food_type", "products", ["food_type"])

    op.add_column(
        "events",
        sa.Column("food_revenue_share_pct", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "events_food_share_pct_range",
        "events",
        "food_revenue_share_pct IS NULL OR "
        "(food_revenue_share_pct >= 0 AND food_revenue_share_pct <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint("events_food_share_pct_range", "events", type_="check")
    op.drop_column("events", "food_revenue_share_pct")
    op.drop_index("ix_products_food_type", table_name="products")
    op.drop_column("products", "food_type")
    postgresql.ENUM(name="food_type").drop(op.get_bind(), checkfirst=True)
