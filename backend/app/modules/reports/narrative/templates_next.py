"""Templates for the 'Cosa fare al prossimo / What To Do Next' section.

Each rendered string is ONE bullet in a list — not joined prose. The engine
returns a list[str] for this section.

Tone: advisory, concrete, numbers embedded. Never scolding ("you wasted")
or vague ("improve things"). Every bullet ties to a specific data point.

Priority range reserved:
  10-40: data-driven recommendations
  100:   baseline fallback (always fires)
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.reports.schemas import ReportData


def _stockouts(d: ReportData):
    return [s for s in d.stock_rows if s.stock_out_occurred]


def _unack_critical_alerts(d: ReportData):
    return [
        a for a in d.alerts
        if a.severity == "critical" and a.acknowledged_at is None
    ]


def _top_product_consumption_pct(d: ReportData) -> float | None:
    """Of the best-selling product, what % of its total allocation was consumed?"""
    name = d.revenue_kpis.top_product_name
    if not name:
        return None
    matches = [s for s in d.stock_rows if s.product_name == name]
    if not matches:
        return None
    allocated = sum((s.opening_qty for s in matches), start=Decimal(0))
    consumed = sum((s.consumed_qty for s in matches), start=Decimal(0))
    if allocated <= 0:
        return None
    return float(consumed / allocated * 100)


def _slow_movers(d: ReportData) -> list:
    """Products consuming <20% of their allocation, unique by product name."""
    seen = {}
    for s in d.stock_rows:
        if s.opening_qty <= 0:
            continue
        pct = float(s.consumed_qty / s.opening_qty * 100)
        if pct < 20 and s.product_name not in seen:
            seen[s.product_name] = pct
    return sorted(seen.items(), key=lambda kv: kv[1])


TEMPLATES_NEXT = [
    # ─── 1. Restock products that hit stock-out ──────────────────────────
    {
        "key": "restock_stockouts",
        "priority": 10,
        "condition": lambda d: len(_stockouts(d)) > 0,
        "it": "Aumenta lo stock di {products} del 20% — {verb} finit{ending} durante la serata.",
        "en": "Increase stock of {products} by 20% — ran out during the event.",
        "extract": lambda d: {
            "products": ", ".join(sorted({s.product_name for s in _stockouts(d)})[:3]),
            "verb": "sono" if len(_stockouts(d)) > 1 else "è",
            "ending": "i" if len(_stockouts(d)) > 1 else "o",
        },
    },

    # ─── 2. Rebalance an underperforming bar ─────────────────────────────
    {
        "key": "rebalance_inefficient_bar",
        "priority": 20,
        "condition": lambda d: (
            len(d.bar_revenues) > 3
            and d.bar_revenues[-1].revenue_pct < 10
        ),
        "it": "Il {bar} ha generato solo il {pct}% del fatturato. Valuta la posizione o l'assegnazione del personale.",
        "en": "{bar} generated only {pct}% of revenue. Review placement or staff allocation.",
        "extract": lambda d: {
            "bar": d.bar_revenues[-1].bar_name,
            "pct": round(d.bar_revenues[-1].revenue_pct, 1),
        },
    },

    # ─── 3. Top product nearly depleted ──────────────────────────────────
    {
        "key": "top_product_restock",
        "priority": 25,
        "condition": lambda d: (
            _top_product_consumption_pct(d) is not None
            and _top_product_consumption_pct(d) > 80
        ),
        "it": "Rifornisci il prodotto più venduto ({product}) — consumato al {pct}%.",
        "en": "Restock the top-selling product ({product}) — {pct}% consumed.",
        "extract": lambda d: {
            "product": d.revenue_kpis.top_product_name,
            "pct": round(_top_product_consumption_pct(d) or 0),
        },
    },

    # ─── 4. Unacknowledged critical alerts ───────────────────────────────
    {
        "key": "unack_critical_alerts",
        "priority": 30,
        "condition": lambda d: len(_unack_critical_alerts(d)) > 0,
        "it": "{n} alert critic{ending_it} {verb_it} rimast{ending_it} senza conferma — rivedi il protocollo di risposta.",
        "en": "{n} critical alert{en_s} went unacknowledged — review the response protocol.",
        "extract": lambda d: {
            "n": len(_unack_critical_alerts(d)),
            "ending_it": "i" if len(_unack_critical_alerts(d)) > 1 else "o",
            "verb_it": "sono" if len(_unack_critical_alerts(d)) > 1 else "è",
            "en_s": "s" if len(_unack_critical_alerts(d)) > 1 else "",
        },
    },

    # ─── 5. Slow-moving products (≥3 under 20% consumption) ──────────────
    {
        "key": "reduce_slow_movers",
        "priority": 35,
        "condition": lambda d: len(_slow_movers(d)) >= 3,
        "it": "Considera di ridurre lo stock dei prodotti meno richiesti: {products}.",
        "en": "Consider reducing stock for slower-moving products: {products}.",
        "extract": lambda d: {
            "products": ", ".join(name for name, _pct in _slow_movers(d)[:3]),
        },
    },

    # ─── 6. Pre-position peak-hour stock ─────────────────────────────────
    {
        "key": "peak_stock_ready",
        "priority": 40,
        "condition": lambda d: (
            d.revenue_kpis.peak_hour_revenue is not None
            and d.revenue_kpis.total_revenue > 0
            and float(d.revenue_kpis.peak_hour_revenue / d.revenue_kpis.total_revenue) > 0.30
        ),
        "it": "Pre-posiziona lo stock per il picco delle {hour} — gran parte del fatturato si concentra in quella finestra.",
        "en": "Pre-position stock before the {hour} peak — most revenue concentrates in that window.",
        "extract": lambda d: {
            "hour": d.revenue_kpis.peak_hour_start.strftime("%H:%M") if d.revenue_kpis.peak_hour_start else "—",
        },
    },

    # ─── 7. Baseline fallback (always fires) ─────────────────────────────
    {
        "key": "baseline_recommendation",
        "priority": 100,
        "condition": lambda d: True,
        "it": "Continua a monitorare i trend — ogni evento affina le previsioni per il prossimo.",
        "en": "Keep monitoring trends — each event sharpens the forecast for the next.",
        "extract": lambda d: {},
    },
]
