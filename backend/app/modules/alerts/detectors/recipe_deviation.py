"""RecipeDeviationDetector — anomaly alerts for over-pour / under-pour.

Owner-only alert class. Managers never see these alerts (audience=owner_only)
so the Owner can investigate quietly before confronting staff.

Algorithm:
    For each (bar, ingredient_product) at the active event:
        expected_qty = sum over (drink, recipe_item) where recipe_item.ingredient = this product:
                          count_of_drinks_sold * recipe_item.qty
        actual_qty   = sum of child stock_transactions for this ingredient at this bar
        deviation    = (actual - expected) / max(expected, MIN_FLOOR)

        if |deviation| >= 0.40:  fire critical
        elif |deviation| >= 0.20: fire warning

The signal is honest at the bar level regardless of which cocktail variants
were sold (Slesh does not tell us per-variant counts at Sundance scale —
all "Cocktail" sales are generic). What we catch is the bar-aggregate
mismatch: "this bar used more rum than 100 generic Cocktails should have used".

Owner-only on purpose. We do NOT want managers seeing "your bar over-poured
38% on rum" without first letting Omar investigate quietly.

Tunable thresholds at module level for post-Sundance recalibration.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import AlertsService
from app.modules.recipes.models import Recipe, RecipeItem
from app.modules.stock_transactions.models import StockTransaction, TransactionSource

logger = logging.getLogger(__name__)


# ─── Tunable thresholds ─────────────────────────────────────────────────────
DEVIATION_WARNING  = Decimal("0.20")    # >= 20%  absolute deviation -> warning
DEVIATION_CRITICAL = Decimal("0.40")    # >= 40%  absolute deviation -> critical

# Don't alert on tiny expected volumes — the ratio is noisy.
# E.g. expected 0.05 L of an ingredient is statistical noise, not a signal.
MIN_EXPECTED_FLOOR = Decimal("0.5")     # in the ingredient's native unit


class RecipeDeviationDetector:
    """Anomaly detector: fires when actual ingredient consumption deviates
    significantly from the recipe-expected consumption at a given bar.

    Owner-only. Stateless; instantiate one per evaluator tick.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.alerts_service = AlertsService(db)

    async def evaluate(
        self,
        tenant_id: UUID,
        event_id: UUID,
        name_maps: tuple[dict[UUID, tuple[str, str]], dict[UUID, str]] | None = None,
    ) -> dict[str, int]:
        """Run one deviation pass. Returns {'checked', 'fired'} counters.

        Reuses name_maps from the orchestrator if provided. Falls back to
        a minimal lookup when None.
        """
        counters = {"checked": 0, "fired": 0}

        # ── 1. Drinks sold per (drink_product, bar) at this event ──
        # Parent transactions only (parent_transaction_id IS NULL) so we
        # count one row per drink sold (children are ingredient-cascade rows).
        drink_count_stmt = (
            select(
                StockTransaction.product_id,        # the drink Product
                StockTransaction.bar_id,
                func.count(StockTransaction.id).label("drinks_sold"),
            )
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
            .where(StockTransaction.source == TransactionSource.SLESH_POS)
            .where(StockTransaction.parent_transaction_id.is_(None))
            .group_by(StockTransaction.product_id, StockTransaction.bar_id)
        )
        try:
            drink_rows = (await self.db.execute(drink_count_stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "recipe-deviation: drink-count query failed tenant=%s event=%s: %s",
                tenant_id, event_id, e,
            )
            return counters

        if not drink_rows:
            return counters

        # ── 2. Recipes for those drinks ──
        sold_drink_ids = {row.product_id for row in drink_rows}
        recipe_stmt = (
            select(Recipe, RecipeItem)
            .join(RecipeItem, RecipeItem.recipe_id == Recipe.id)
            .where(Recipe.tenant_id == tenant_id)
            .where(Recipe.drink_product_id.in_(sold_drink_ids))
        )
        recipe_rows = (await self.db.execute(recipe_stmt)).all()

        if not recipe_rows:
            return counters    # no recipes defined yet -> nothing to compare

        # Map drink_product_id -> [(ingredient_product_id, qty_per_drink), ...]
        drink_to_items: dict[UUID, list[tuple[UUID, Decimal]]] = defaultdict(list)
        for recipe, item in recipe_rows:
            drink_to_items[recipe.drink_product_id].append(
                (item.ingredient_product_id, item.qty)
            )

        # ── 3. Compute expected per (bar, ingredient) ──
        # expected[(bar, ingredient)] = sum over drinks sold * qty_per_drink
        expected: dict[tuple[UUID, UUID], Decimal] = defaultdict(lambda: Decimal("0"))
        for row in drink_rows:
            drink_pid = row.product_id
            bar_id    = row.bar_id
            n_sold    = Decimal(row.drinks_sold)
            for (ing_pid, qty_per_drink) in drink_to_items.get(drink_pid, []):
                expected[(bar_id, ing_pid)] += n_sold * qty_per_drink

        if not expected:
            return counters

        # ── 4. Compute actual ingredient consumption per (bar, ingredient) ──
        # Child transactions (parent_transaction_id IS NOT NULL) carry the
        # ingredient deductions written by the cascade. We sum qty per
        # (ingredient_product_id, bar_id).
        ingredient_pids = {ing_pid for (_bar, ing_pid) in expected}
        actual_stmt = (
            select(
                StockTransaction.bar_id,
                StockTransaction.product_id,        # the ingredient Product
                func.sum(StockTransaction.qty).label("total_qty"),
            )
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
            .where(StockTransaction.source == TransactionSource.SLESH_POS)
            .where(StockTransaction.parent_transaction_id.is_not(None))
            .where(StockTransaction.product_id.in_(ingredient_pids))
            .group_by(StockTransaction.bar_id, StockTransaction.product_id)
        )
        try:
            actual_rows = (await self.db.execute(actual_stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "recipe-deviation: actual-consumption query failed: %s", e,
            )
            return counters

        actual: dict[tuple[UUID, UUID], Decimal] = {
            (row.bar_id, row.product_id): Decimal(row.total_qty)
            for row in actual_rows
        }

        # Name maps for human-readable alert text
        if name_maps is None:
            products, bars = {}, {}
        else:
            products, bars = name_maps

        # ── 5. Per (bar, ingredient): compare and fire ──
        for (bar_id, ing_pid), expected_qty in expected.items():
            counters["checked"] += 1

            if expected_qty < MIN_EXPECTED_FLOOR:
                continue   # not enough volume for the signal to be reliable

            actual_qty = actual.get((bar_id, ing_pid), Decimal("0"))
            deviation_signed   = (actual_qty - expected_qty) / expected_qty
            deviation_absolute = abs(deviation_signed)

            if deviation_absolute >= DEVIATION_CRITICAL:
                severity = "critical"
            elif deviation_absolute >= DEVIATION_WARNING:
                severity = "warning"
            else:
                continue

            ingredient_name, unit = products.get(ing_pid, (f"ingredient {ing_pid}", "unit"))
            bar_name = bars.get(bar_id, f"bar {bar_id}")

            direction = "over-pour" if deviation_signed > 0 else "under-pour"
            pct       = (deviation_absolute * 100).quantize(Decimal("1"))
            sign      = "+" if deviation_signed > 0 else "-"

            title = f"Recipe deviation: {ingredient_name} at {bar_name} ({sign}{pct}%)"
            owner_message = (
                f"{bar_name} {direction} on {ingredient_name}: actual consumption "
                f"is {actual_qty} {unit} vs recipe-expected {expected_qty} {unit} "
                f"({sign}{pct}%). Investigate privately before confronting staff "
                f"— possible causes include free pouring, theft, or recipe mismatch."
            )
            suggested_action = (
                f"Ask the bar manager for a quiet manual count of {ingredient_name} "
                f"at {bar_name}. Cross-reference with bartender shift records before "
                f"raising the issue with staff."
            )

            payload = AlertCreate(
                event_id=event_id,
                bar_id=bar_id,
                product_id=ing_pid,
                alert_type="anomaly",
                severity=severity,
                audience="owner_only",
                title=title,
                owner_message=owner_message,
                manager_message=None,    # never reaches managers by design
                suggested_action=suggested_action,
                context_json={
                    "bar_name": bar_name,
                    "ingredient_name": ingredient_name,
                    "unit": unit,
                    "expected_qty": str(expected_qty),
                    "actual_qty":   str(actual_qty),
                    "deviation_pct": str(deviation_absolute * 100),
                    "direction":    direction,
                    "warning_threshold_pct":  str(DEVIATION_WARNING * 100),
                    "critical_threshold_pct": str(DEVIATION_CRITICAL * 100),
                },
            )
            try:
                await self.alerts_service.create_alert(tenant_id, payload)
                counters["fired"] += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "recipe-deviation: create_alert failed bar=%s ing=%s: %s",
                    bar_id, ing_pid, e,
                )

        return counters
