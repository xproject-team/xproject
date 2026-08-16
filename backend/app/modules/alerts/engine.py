"""DepletionEvaluator — consumes burn-rate output and fires time-based alerts.

This is where Alerts meets Burn-rate. Every 5 minutes (configurable) the
background scheduler runs an evaluator per-tenant per-active-event. The
evaluator:

  1. Calls StockTransactionService.compute_burn_rates() for the event.
  2. Applies the Architecture Bible §4.5 severity ladder to each
     (bar, product) result:
        TTD < 20 min OR stock = 0  → CRITICAL
        TTD < 45 min               → WARNING
        TTD < 60 min               → INFO
        else                       → no alert
  3. Builds AlertCreate payloads with role-appropriate messages and
     a rule-based suggested_action (the AI-advisor slot stays empty for
     now; future LLM agent fills it).
  4. Calls AlertsService.create_alert() which deduplicates by key —
     no floods when the same condition persists across cycles.
  5. Auto-resolves previously-active alerts whose underlying condition
     no longer applies (stock was restocked, burn rate dropped).

The evaluator is ISOLATED from the user-facing API: if it crashes, the
HTTP layer keeps serving cached alerts. Same soft-dependency pattern we
used for chat broadcast. Exceptions are logged and swallowed at the
tenant-run boundary.

Routing rule (Architecture Bible + Discovery Report §3):
  INFO             → owner_only  (Owner sees yellow dot, manager untouched)
  WARNING/CRITICAL → owner_and_manager  (Manager sees operational text)
  ANOMALY          → owner_only  (future, handled by AnomalyEngine)
Managers are NEVER shown anomaly alerts — enforced at the service _view()
projection. This is a core security/trust principle.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import AlertsService
from app.modules.bars.models import Bar
from app.modules.products.models import Product
from app.modules.stock_transactions.service import StockTransactionService

logger = logging.getLogger(__name__)


# ─── Thresholds (Architecture Bible §4.5) ─────────────────────────────────────
# Minutes of runway remaining before action is required.

THRESHOLD_CRITICAL_MIN = 20
THRESHOLD_WARNING_MIN = 45
THRESHOLD_INFO_MIN = 60


# ─── Severity decision helper ─────────────────────────────────────────────────


def _severity_for(
    current_qty: 'Decimal | int | None',
    ttd_minutes: Decimal | None,
) -> str | None:
    """Return 'info' / 'warning' / 'critical' or None if no alert warranted.

    Args:
        current_qty: Units remaining at the bar for this product. None means
            the burn-rate row didn't carry stock info (defensive).
        ttd_minutes: Time-to-depletion in minutes, or None if no rate was
            computable (no sales in any window → no alert, on purpose).

    Rules (in order):
        stock == 0          → CRITICAL (already out)
        ttd < 20            → CRITICAL (20 min runway)
        ttd < 45            → WARNING  (45 min runway)
        ttd < 60            → INFO
        else                → None
    """
    if current_qty is not None and current_qty == 0:
        return "critical"
    if ttd_minutes is None:
        return None
    # ttd == 0 is effectively depleted too, but we handle it via current_qty
    # above. Defensive: if somehow only ttd is 0 and stock isn't, still crit.
    if ttd_minutes <= 0:
        return "critical"
    if ttd_minutes < THRESHOLD_CRITICAL_MIN:
        return "critical"
    if ttd_minutes < THRESHOLD_WARNING_MIN:
        return "warning"
    if ttd_minutes < THRESHOLD_INFO_MIN:
        return "info"
    return None


def _audience_for(severity: str) -> str:
    """Alert routing matrix for depletion alerts.

    INFO stays on the Owner dashboard only (yellow dot, feed entry).
    WARNING + CRITICAL go to the assigned Manager's channel too, with
    sanitized operational text.
    """
    if severity == "info":
        return "owner_only"
    return "owner_and_manager"


# ─── Quantity + unit formatting helpers ──────────────────────────────────────
_UNIT_PLURAL = {
    'bottle': 'bottles',
    'glass': 'glasses',
    'can': 'cans',
    'draft_glass': 'draft glasses',
    'shot': 'shots',
    'piece': 'pieces',
    'gram': 'g',
    'ml': 'ml',
}

def _fmt_qty(qty) -> str:
    """Format a Decimal/int quantity for human display.
    18120.000  -> '18,120'
    0.750      -> '0.75'
    1.500      -> '1.5'
    """
    from decimal import Decimal as _D
    d = _D(str(qty)).normalize()
    # If it's a whole number show as int with comma separator
    if d == d.to_integral_value():
        return f'{int(d):,}'
    # Otherwise strip trailing zeros and show up to 3 decimal places
    return f'{float(d):.3f}'.rstrip('0')

def _fmt_unit(unit: str, qty=None) -> str:
    """Return display-friendly unit string, pluralized when qty != 1."""
    singular_map = {v: k for k, v in _UNIT_PLURAL.items()}
    # gram and ml are already abbreviations — no plural needed
    if unit in ('gram', 'ml', 'g'):
        return _UNIT_PLURAL.get(unit, unit)
    plural = _UNIT_PLURAL.get(unit, unit + 's')
    if qty is None:
        return plural
    try:
        return singular_map.get(unit, unit) if float(str(qty)) == 1.0 else plural
    except (ValueError, TypeError):
        return plural

# ─── Message builders (rule-based; AI-advisor slot stays empty for now) ───────


def _build_messages(
    severity: str,
    product_name: str,
    bar_name: str,
    current_qty: 'Decimal | int',
    unit: str,
    burn_rate_per_hour: Decimal,
    ttd_minutes: Decimal | None,
) -> tuple[str, str, str | None, str]:
    """Produce (title, owner_message, manager_message, suggested_action).

    Owner text includes full context (numbers, the WHY). Manager text is
    operational only — 'stock low, restock needed'. Anomaly-grade detail is
    never in manager_message by construction.

    suggested_action is a rule-based string today. Future AI advisor
    replaces it with historical reasoning via the ai_advisory column;
    schema + frontend unchanged.
    """
    # Round presentation values sensibly.
    rate_str = f"{burn_rate_per_hour:.1f}"
    qty_str = _fmt_qty(current_qty)
    unit_str = _fmt_unit(unit, current_qty)
    unit_rate = _fmt_unit(unit)
    if current_qty == 0:
        title = f"{product_name} depleted at {bar_name}"
        owner_message = (
            f"{product_name} at {bar_name} is fully depleted (0 {unit_str} "
            f"remaining). Consumption was running at {rate_str} {unit_rate}/h. "
            f"Any further orders will create deficit (phantom sales)."
        )
        manager_message = (
            f"Stock depleted for {product_name}. Restock urgently."
        )
        suggested_action = (
            f"Dispatch replenishment of {product_name} to {bar_name} "
            f"immediately. Typical restock takes 10-15 min."
        )
        return title, owner_message, manager_message, suggested_action

    ttd_int = int(ttd_minutes) if ttd_minutes is not None else 0

    if severity == "critical":
        title = f"{product_name} critically low at {bar_name}"
        owner_message = (
            f"{product_name} at {bar_name} will deplete in approximately "
            f"{ttd_int} minutes at the current rate of {rate_str} {unit_rate}/h. "
            f"{qty_str} {unit_str} remaining. Action needed now to avoid "
            f"stock-out."
        )
        manager_message = (
            f"Low stock warning: {product_name}. Restock needed urgently."
        )
        suggested_action = (
            f"Dispatch {product_name} to {bar_name} within the next "
            f"10 minutes. Current runway is ~{ttd_int} min."
        )
    elif severity == "warning":
        title = f"{product_name} running low at {bar_name}"
        owner_message = (
            f"{product_name} at {bar_name} will deplete in approximately "
            f"{ttd_int} minutes at {rate_str} {unit_rate}/h. {qty_str} "
            f"{unit_str} remaining. Plan a restock."
        )
        manager_message = (
            f"Stock low for {product_name}. Restock recommended."
        )
        suggested_action = (
            f"Prepare restock of {product_name} for {bar_name} within the "
            f"next 30 minutes."
        )
    else:  # info
        title = f"{product_name} approaching threshold at {bar_name}"
        owner_message = (
            f"{product_name} at {bar_name} has {qty_str} {unit_str} "
            f"remaining, running at {rate_str} {unit_rate}/h. Projected "
            f"depletion in ~{ttd_int} minutes. Monitor and plan restock."
        )
        manager_message = None  # INFO is owner_only; never reaches manager
        suggested_action = (
            f"No immediate action needed. Verify warehouse has "
            f"{product_name} available for timely restock if rate holds."
        )

    return title, owner_message, manager_message, suggested_action


# ─── The evaluator itself ─────────────────────────────────────────────────────


class DepletionEvaluator:
    """Runs one full depletion pass for one tenant × one event.

    Stateless; create one per scheduler tick. Holds the AsyncSession.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.stock_tx_service = StockTransactionService(db)
        self.alerts_service = AlertsService(db)

    async def _load_name_maps(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> tuple[dict[UUID, tuple[str, str]], dict[UUID, str]]:
        """Fetch product (id → (name, unit)) and bar (id → name) maps for
        this tenant. One round-trip each. Cached per evaluator instance.

        Scoped to tenant to prevent cross-tenant name bleed.
        """
        prod_stmt = select(
            Product.id, Product.name, Product.unit,
        ).where(Product.tenant_id == tenant_id)
        prod_rows = (await self.db.execute(prod_stmt)).all()
        products: dict[UUID, tuple[str, str]] = {
            pid: (name, unit.value if hasattr(unit, "value") else str(unit)) for pid, name, unit in prod_rows
        }

        bar_stmt = select(Bar.id, Bar.name).where(Bar.tenant_id == tenant_id)
        bar_rows = (await self.db.execute(bar_stmt)).all()
        bars: dict[UUID, str] = {bid: name for bid, name in bar_rows}

        return products, bars

    async def evaluate(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> dict[str, int]:
        """Run one depletion-evaluation pass for an event.

        Returns a counters dict: {'fired': N, 'auto_resolved': M, 'checked': K}.
        Never raises — exceptions are logged and the counters reflect what
        got done before the error. This keeps the scheduler resilient.
        """
        counters = {"checked": 0, "fired": 0, "auto_resolved": 0}

        try:
            burn_rows = await self.stock_tx_service.compute_burn_rates(
                tenant_id=tenant_id,
                event_id=event_id,
                bar_id=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "depletion evaluator: burn-rate fetch failed for "
                "tenant=%s event=%s: %s", tenant_id, event_id, e,
            )
            return counters

        if not burn_rows:
            # No transactions in event yet → nothing to evaluate, nothing to
            # auto-resolve. This is the common case for a quiet event.
            return counters

        products, bars = await self._load_name_maps(tenant_id, event_id)

        # Track which (bar, product, type) keys are still alert-worthy for
        # the auto-resolve diff at the end.
        still_active_keys: set[tuple[UUID, UUID | None, str]] = set()

        for row in burn_rows:
            counters["checked"] += 1

            # Pull values, coerce to the right types.
            product_id: UUID = row["product_id"]
            bar_id: UUID = row["bar_id"]
            current_qty = row.get("current_qty")
            burn_rate = row.get("burn_rate_per_hour") or Decimal("0")
            ttd = row.get("time_to_depletion_min")
            window_label = row.get("window_label", "event_wide")

            # Severity decision
            severity = _severity_for(current_qty, ttd)
            if severity is None:
                continue

            # Lookup display names (snapshot)
            prod_entry = products.get(product_id)
            if prod_entry is None:
                # Product was deleted or tenant mismatch — skip. Shouldn't
                # happen in steady-state, but defensive.
                logger.warning(
                    "depletion: product %s not found for tenant %s; skip",
                    product_id, tenant_id,
                )
                continue
            product_name, unit = prod_entry
            bar_name = bars.get(bar_id, "Unknown bar")

            # Build messages + action
            title, owner_msg, manager_msg, suggested = _build_messages(
                severity=severity,
                product_name=product_name,
                bar_name=bar_name,
                current_qty=current_qty or 0,
                unit=unit,
                burn_rate_per_hour=burn_rate,
                ttd_minutes=ttd,
            )

            audience = _audience_for(severity)

            context = {
                "current_stock": int(current_qty or 0),
                "burn_rate_per_hour": float(burn_rate),
                "ttd_minutes": float(ttd) if ttd is not None else None,
                "window_label": window_label,
                "product_name": product_name,
                "bar_name": bar_name,
                "unit": unit,
            }

            payload = AlertCreate(
                event_id=event_id,
                bar_id=bar_id,
                product_id=product_id,
                alert_type="depletion",
                severity=severity,
                audience=audience,
                title=title,
                owner_message=owner_msg,
                manager_message=manager_msg,
                suggested_action=suggested,
                context_json=context,
            )

            try:
                await self.alerts_service.create_alert(tenant_id, payload)
                counters["fired"] += 1
                still_active_keys.add((bar_id, product_id, "depletion"))
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "depletion: create_alert failed for bar=%s product=%s: %s",
                    bar_id, product_id, e,
                )

        # Auto-resolve anything that's no longer alert-worthy. Scoped to
        # 'depletion' only — this pass has no information about whether
        # any anomaly alert's condition still holds, so it must never
        # touch those rows (see auto_resolve_missing's docstring).
        try:
            counters["auto_resolved"] = (
                await self.alerts_service.auto_resolve_missing(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    still_active_keys=still_active_keys,
                    alert_types={"depletion"},
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "depletion: auto-resolve failed for event=%s: %s",
                event_id, e,
            )

        logger.info(
            "depletion evaluator: tenant=%s event=%s %s",
            tenant_id, event_id, counters,
        )
        return counters


# ═════════════════════════════════════════════════════════════════════════════
# Orchestrator — runs all detectors in one pass, returns combined counters.
# ═════════════════════════════════════════════════════════════════════════════

class AlertsOrchestrator:
    """Runs every alerts detector for one tenant x one event.

    Current detectors:
      - DepletionEvaluator (time-based stock depletion)
      - DemandSpikeDetector (anomaly: short-window vs long-window ratio)

    Adding a new detector: import it, instantiate in __init__, call its
    evaluate() in run_all() and merge its counters. The worker doesn't
    care how many detectors exist; it just calls run_all().
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.depletion = DepletionEvaluator(db)
        # Late import avoids a circular import at module load (detectors
        # import alerts.service, which imports this module transitively).
        from app.modules.alerts.detectors.demand_spike import DemandSpikeDetector
        from app.modules.alerts.detectors.recipe_deviation import RecipeDeviationDetector
        self.demand_spike = DemandSpikeDetector(db)
        self.recipe_deviation = RecipeDeviationDetector(db)

    async def run_all(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> dict[str, int]:
        """Run every detector; return aggregated counters across detectors."""
        totals = {"checked": 0, "fired": 0, "auto_resolved": 0}

        # Depletion first — it owns the auto-resolve pass and needs to run
        # before any new alerts are created this tick.
        dep = await self.depletion.evaluate(tenant_id, event_id)
        for k, v in dep.items():
            totals[k] = totals.get(k, 0) + v

        # Load name maps ONCE and share across every detector that needs
        # them — avoids repeated round-trips for the same tenant-scoped lookup.
        name_maps = await self.depletion._load_name_maps(tenant_id, event_id)

        # Then anomaly detectors. Each increments "checked" and "fired".
        # Anomaly alerts have no auto-resolve pass of their own yet — the
        # depletion auto-resolve above is scoped to alert_type='depletion'
        # only and never touches them (see auto_resolve_missing). An
        # anomaly alert currently only clears via manual acknowledge/
        # resolve or event expiry.
        spike = await self.demand_spike.evaluate(tenant_id, event_id, name_maps=name_maps)
        for k, v in spike.items():
            totals[k] = totals.get(k, 0) + v

        deviation = await self.recipe_deviation.evaluate(tenant_id, event_id, name_maps=name_maps)
        for k, v in deviation.items():
            totals[k] = totals.get(k, 0) + v

        return totals
