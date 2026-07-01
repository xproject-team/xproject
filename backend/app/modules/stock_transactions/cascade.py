"""Internal cascade machinery for sale ingestion.

Separated from service.py so the pure math is testable in isolation.

Chunk 3a note (July 2026): plan_ingredient_decrement below is the
RecipeItem-based ingredient cascade — it feeds
RecipeDeviationDetector's over-pour anomaly detection (see
app/modules/recipes/__init__.py), NOT the live sale-depletion alerts
Omar sees during an event. Those are computed at READ time by
app.modules.event_storage.bar_supplier_stock_service from
EventCategoryIngredient rows (Catalog > Recipes tab, Chunk 2) and
existing StockTransaction rows — no cascade write path needed, since
EventCategoryIngredient.supplier_product_id points at the warehouse
supplier_products table, not products.id, and there's no guaranteed
bridge to a bar_stock row keyed by product_id. Do not extend this
cascade to cover EventCategoryIngredient without resolving that
FK mismatch first.

The cascade for a sale:
1. Parent row: drink consumption at the bar (carries price_cents)
2. For each recipe_item: a child row consuming that ingredient

Stock clamping (Q6 policy):
- If a bar_stock row exists and current_qty >= requested qty:
    decrement normally, deficit_qty = 0
- If current_qty < requested qty:
    decrement down to 0, deficit_qty = (requested - current_qty)
- If no bar_stock row exists at all for this ingredient:
    write a child tx with bar_stock_id=NULL, deficit_qty = full qty

A "no stock row" scenario is NOT an error — it means someone sold a
drink with an ingredient that was never allocated. Reconciliation
reports this as a large anomaly signal.
"""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.bar_stock.models import BarStock
from app.modules.recipes.models import RecipeItem


@dataclass(frozen=True)
class StockDecrementPlan:
    """A planned decrement against one bar_stock row (or NULL if none)."""
    bar_stock_id: UUID | None
    product_id: UUID
    requested_qty: Decimal
    applied_qty: Decimal         # what we actually deduct (<= current_qty)
    deficit_qty: Decimal         # requested - applied (>= 0)
    note: str | None = None


def plan_parent_decrement(
    drink_stock: BarStock | None,
    product_id: UUID,
    qty: Decimal,
) -> StockDecrementPlan:
    """Plan the drink's own stock decrement (the parent row of a sale).

    For drinks served as glass/can/bottle the qty is typically 1 and
    there's usually a bar_stock row. If there's no stock row, the
    sale still goes through with a full deficit — reconciliation
    will surface this as a drink-without-allocation anomaly.
    """
    if drink_stock is None:
        return StockDecrementPlan(
            bar_stock_id=None,
            product_id=product_id,
            requested_qty=qty,
            applied_qty=Decimal("0"),
            deficit_qty=qty,
        )

    # Apply to bar_stock, clamping at 0
    available = Decimal(drink_stock.current_qty)
    applied = min(available, qty)
    deficit = qty - applied

    return StockDecrementPlan(
        bar_stock_id=drink_stock.id,
        product_id=product_id,
        requested_qty=qty,
        applied_qty=applied,
        deficit_qty=deficit,
    )


def plan_ingredient_decrement(
    ingredient_stock: BarStock | None,
    recipe_item: RecipeItem,
    sold_qty: Decimal,
) -> StockDecrementPlan:
    """Plan a child decrement for one ingredient.

    recipe_item.qty is per-single-sale (e.g. 50ml rum per 1 Mojito).
    If sold_qty > 1 (half-pour edge case: sold_qty=0.5), scale
    linearly: ingredient_needed = recipe_item.qty * sold_qty.

    Per Q5 decision: recipe qty is already in the product's native unit
    (e.g. 0.05 bottle), so no unit conversion here.
    """
    ingredient_needed = recipe_item.qty * sold_qty

    if ingredient_stock is None:
        return StockDecrementPlan(
            bar_stock_id=None,
            product_id=recipe_item.ingredient_product_id,
            requested_qty=ingredient_needed,
            applied_qty=Decimal("0"),
            deficit_qty=ingredient_needed,
        )

    available = Decimal(ingredient_stock.current_qty)
    applied = min(available, ingredient_needed)
    deficit = ingredient_needed - applied

    return StockDecrementPlan(
        bar_stock_id=ingredient_stock.id,
        product_id=recipe_item.ingredient_product_id,
        requested_qty=ingredient_needed,
        applied_qty=applied,
        deficit_qty=deficit,
    )


def apply_plan_to_stock(stock: BarStock | None, plan: StockDecrementPlan) -> None:
    """Mutate the BarStock in-place according to the plan.

    No-op if stock is None (deficit-only write, no stock row to decrement).
    Rounds applied_qty to int before decrementing current_qty, because
    bar_stock.current_qty is INTEGER (Q5 decision deferred NUMERIC migration).

    Rounding policy: ROUND_DOWN so we never over-deduct.
    """
    if stock is None:
        return
    if plan.applied_qty <= 0:
        return
    # Round DOWN to int — never deduct more than available
    deduct = int(plan.applied_qty)
    stock.current_qty = max(0, stock.current_qty - deduct)
