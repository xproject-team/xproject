"""DemandSpikeDetector — anomaly alerts for sudden consumption spikes.

Owner-only alert class. Managers never see these alerts by construction
(audience=owner_only in AlertsService). The design intent: when unusual
consumption happens, the Owner gets a silent heads-up to investigate
quietly — without alerting the staff.

Algorithm (ratio-based, historical-data-free):

    if burn_rate(last_15min) >= SPIKE_FACTOR * burn_rate(last_60min)
       and burn_rate(last_15min) >= MIN_ABSOLUTE_FLOOR:
        fire ANOMALY alert

This is deliberately simple. It doesn't need multi-event history, it's
self-normalizing for crowded vs quiet events, and it catches the thing
Omar actually cares about: *sudden* spikes (sustained high demand is
just "a good night", not an anomaly).

Thresholds are tunable at the module level so Omar can adjust later
based on observed false-positive rates.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import AlertsService
from app.modules.stock_transactions.service import StockTransactionService

logger = logging.getLogger(__name__)


# ─── Tunable thresholds ─────────────────────────────────────────────────────

SPIKE_FACTOR_WARNING = Decimal("2.0")   # 15min rate >= 2x 60min → warning
SPIKE_FACTOR_CRITICAL = Decimal("3.0")  # 15min rate >= 3x 60min → critical
MIN_ABSOLUTE_FLOOR = Decimal("1.0")     # Ignore products consuming <1/hr
SHORT_WINDOW_MIN = 15
LONG_WINDOW_MIN = 60


class DemandSpikeDetector:
    """Anomaly detector: fires when short-window consumption outpaces
    long-window consumption by a configurable ratio.

    Owner-only. Stateless; instantiate one per evaluator tick.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.stock_tx_service = StockTransactionService(db)
        self.alerts_service = AlertsService(db)

    async def evaluate(
        self,
        tenant_id: UUID,
        event_id: UUID,
        name_maps: tuple[dict[UUID, tuple[str, str]], dict[UUID, str]] | None = None,
    ) -> dict[str, int]:
        """Run one demand-spike pass. Returns {'checked', 'fired'} counters.

        Reuses name_maps from the orchestrator if provided (to avoid
        redundant DB round-trips across detectors). If not provided,
        falls back to a minimal lookup.
        """
        counters = {"checked": 0, "fired": 0}

        # Pull the two fixed-window rate snapshots
        try:
            short_rows = await self.stock_tx_service.compute_burn_rate_fixed_window(
                tenant_id=tenant_id,
                event_id=event_id,
                window_minutes=SHORT_WINDOW_MIN,
                bar_id=None,
            )
            long_rows = await self.stock_tx_service.compute_burn_rate_fixed_window(
                tenant_id=tenant_id,
                event_id=event_id,
                window_minutes=LONG_WINDOW_MIN,
                bar_id=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "demand-spike: burn-rate fetch failed tenant=%s event=%s: %s",
                tenant_id, event_id, e,
            )
            return counters

        # Index long-window rates by (product_id, bar_id) for fast lookup
        long_rate_map: dict[tuple[UUID, UUID], Decimal] = {
            (row["product_id"], row["bar_id"]): row["burn_rate_per_hour"]
            for row in long_rows
        }

        # Name maps (optional; lazy default)
        if name_maps is None:
            products, bars = {}, {}
        else:
            products, bars = name_maps

        for row in short_rows:
            counters["checked"] += 1
            pid: UUID = row["product_id"]
            bid: UUID = row["bar_id"]
            short_rate: Decimal = row["burn_rate_per_hour"]
            long_rate: Decimal = long_rate_map.get((pid, bid), Decimal("0"))

            # Skip low-volume products (noise filter)
            if short_rate < MIN_ABSOLUTE_FLOOR:
                continue

            # Denominator floor: if long_rate is effectively zero, the ratio
            # is undefined. Only fire if short_rate is well above the floor
            # AND long_rate is truly zero (brand-new spike on a quiet product).
            if long_rate <= Decimal("0.1"):
                if short_rate >= MIN_ABSOLUTE_FLOOR * Decimal("3"):
                    severity = "critical"
                else:
                    continue
            else:
                ratio = short_rate / long_rate
                if ratio >= SPIKE_FACTOR_CRITICAL:
                    severity = "critical"
                elif ratio >= SPIKE_FACTOR_WARNING:
                    severity = "warning"
                else:
                    continue

            # Build the alert
            product_name, unit = products.get(pid, (f"product {pid}", "unit"))
            bar_name = bars.get(bid, f"bar {bid}")
            title = f"Demand spike: {product_name} at {bar_name}"
            owner_message = (
                f"Unusual consumption pattern detected. {product_name} at "
                f"{bar_name} is currently running at {short_rate} {unit}/h "
                f"(15-min window) vs {long_rate} {unit}/h (60-min baseline). "
                f"This is {severity}-level deviation. Investigate privately "
                f"before confronting staff."
            )
            suggested_action = (
                f"Ask the bar manager for a quiet manual stock count of "
                f"{product_name} at {bar_name}. Do not reference the "
                f"anomaly directly."
            )

            payload = AlertCreate(
                event_id=event_id,
                bar_id=bid,
                product_id=pid,
                alert_type="anomaly",
                severity=severity,
                audience="owner_only",
                title=title,
                owner_message=owner_message,
                manager_message=None,  # never reaches managers by design
                suggested_action=suggested_action,
                context_json={
                    "bar_name": bar_name,
                    "product_name": product_name,
                    "unit": unit,
                    "short_window_minutes": SHORT_WINDOW_MIN,
                    "long_window_minutes": LONG_WINDOW_MIN,
                    "short_rate_per_hour": str(short_rate),
                    "long_rate_per_hour": str(long_rate),
                    "ratio": str(
                        (short_rate / long_rate).quantize(Decimal("0.01"))
                        if long_rate > 0 else Decimal("0")
                    ),
                },
            )
            try:
                await self.alerts_service.create_alert(tenant_id, payload)
                counters["fired"] += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "demand-spike: create_alert failed for pid=%s bid=%s: %s",
                    pid, bid, e,
                )

        return counters
