"""Templates for the 'Cosa è successo / What Happened' section.

Read order: priority ascending. Conditions are mutually tolerant — several
may fire in the same report, producing a naturally-flowing paragraph.

Tone for Omar: direct, warm, numbers embedded naturally. Never robotic.
Italian is primary (Omar's native language); English must match the tone,
not translate literally.
"""
from __future__ import annotations

from app.modules.reports.schemas import ReportData


def _fmt_eur(value, digits: int = 0) -> str:
    """Italian-locale euro formatting.

    digits=0 (default) — round to whole euros: 24350.49 → '24.350'
    digits=2           — keep cents:           13.751   → '13,75'

    Italian convention: '.' is the thousands separator, ',' is the decimal.
    Used for narrative templates where integer euros read cleanly for big
    aggregates (total revenue, peak-hour revenue) but cents matter for
    small per-unit values (per-guest spend, unit prices).
    """
    n = float(value or 0)
    if digits == 0:
        return f"{int(round(n)):,}".replace(",", ".")
    # Format with English locale first (12,345.67), then swap separators
    # to Italian (12.345,67). The double-swap via a placeholder avoids
    # accidentally translating the comma we just inserted.
    formatted = f"{n:,.{digits}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_hm(dt) -> str:
    """datetime → 'HH:MM' in 24h format."""
    return dt.strftime("%H:%M") if dt else "—"


def _revenue_delta_pct(d: ReportData) -> float | None:
    """previous_event_delta_pct off the "Total Revenue" comparison row, or
    None if comparison data / that row isn't available. Computed once so
    condition and extract never risk disagreeing on which row they mean."""
    if d.comparison is None or not d.comparison.available:
        return None
    for m in d.comparison.metrics:
        if m.label == "Total Revenue":
            return m.previous_event_delta_pct
    return None


TEMPLATES_HAPPENED = [
    # ─── 1. Opening summary (always fires) ────────────────────────────────
    {
        "key": "opening_summary",
        "priority": 0,
        "condition": lambda d: True,
        "it": "{event_name} ha generato €{revenue} in {bars} bar, nell'arco di {hours} ore.",
        "en": "{event_name} generated €{revenue} across {bars} bars over {hours} hours.",
        "extract": lambda d: {
            "event_name": d.event.event_name,
            "revenue": _fmt_eur(d.revenue_kpis.total_revenue),
            "bars": d.event.bars_count,
            "hours": f"{d.event.duration_hours:.1f}".rstrip("0").rstrip("."),
        },
    },

    # ─── 2. Revenue leader (when one bar dominates) ──────────────────────
    {
        "key": "revenue_leader",
        "priority": 10,
        "condition": lambda d: (
            len(d.bar_revenues) > 0
            and d.bar_revenues[0].revenue_pct >= 35
        ),
        "it": "{bar} ha guidato la serata, generando il {pct}% del fatturato totale.",
        "en": "{bar} led the night, generating {pct}% of total revenue.",
        "extract": lambda d: {
            "bar": d.bar_revenues[0].bar_name,
            "pct": int(round(d.bar_revenues[0].revenue_pct)),
        },
    },

    # ─── 3. Balanced bars (when no bar dominates) ────────────────────────
    {
        "key": "balanced_bars",
        "priority": 10,
        "condition": lambda d: (
            len(d.bar_revenues) >= 3
            and d.bar_revenues[0].revenue_pct < 35
        ),
        "it": "I bar hanno lavorato in equilibrio — nessuna singola postazione ha dominato la serata.",
        "en": "The bars worked in balance — no single station dominated the night.",
        "extract": lambda d: {},
    },

    # ─── 4. Peak hour ─────────────────────────────────────────────────────
    {
        "key": "peak_hour",
        "priority": 20,
        "condition": lambda d: (
            d.revenue_kpis.peak_hour_start is not None
            and d.revenue_kpis.peak_hour_revenue is not None
        ),
        "it": "Il picco è arrivato alle {hour}, con €{peak_rev} in un'ora.",
        "en": "Peak consumption hit at {hour}, generating €{peak_rev} in one hour.",
        "extract": lambda d: {
            "hour": _fmt_hm(d.revenue_kpis.peak_hour_start),
            "peak_rev": _fmt_eur(d.revenue_kpis.peak_hour_revenue),
        },
    },

    # ─── 5. Top product ───────────────────────────────────────────────────
    {
        "key": "top_product",
        "priority": 30,
        "condition": lambda d: (
            d.revenue_kpis.top_product_name is not None
            and d.revenue_kpis.top_product_units is not None
            and d.revenue_kpis.top_product_units > 0
        ),
        "it": "Il prodotto più venduto è stato {product}, con {units} unità.",
        "en": "The best-selling product was {product}, with {units} units sold.",
        "extract": lambda d: {
            "product": d.revenue_kpis.top_product_name,
            "units": d.revenue_kpis.top_product_units,
        },
    },

    # ─── 6. Guest throughput (v1.2+: needs ticketing data) ───────────────
    {
        "key": "guest_throughput",
        "priority": 40,
        "condition": lambda d: (
            d.event.guests_served is not None
            and d.event.guests_served > 0
        ),
        "it": "{guests} ospiti serviti, per una media di €{per_guest} a persona.",
        "en": "{guests} guests served, averaging €{per_guest} per head.",
        "extract": lambda d: {
            "guests": d.event.guests_served,
            "per_guest": _fmt_eur(
                float(d.revenue_kpis.total_revenue) / d.event.guests_served
                if d.event.guests_served > 0
                else 0,
                digits=2,
            ),
        },
    },

    # ─── 6a. Event-over-event revenue comparison (Section C) ─────────────
    # Placed early (right after the opening summary) so the headline
    # comparison reads before the play-by-play detail. Only fires when a
    # previous event's revenue figure is available — comparison.available
    # is False for a tenant's very first event, and revenue is the one
    # comparison metric that has always been in every historical
    # data_json (see ReportComparison's docstring).
    {
        "key": "revenue_vs_previous_event",
        "priority": 5,
        "condition": lambda d: _revenue_delta_pct(d) is not None,
        "it": "Rispetto a {prev_name}, il fatturato è {direction_it} del {pct}%.",
        "en": "Compared to {prev_name}, revenue {direction_en} {pct}%.",
        "extract": lambda d: {
            "prev_name": d.comparison.previous_event_name or "—",
            "direction_it": "aumentato" if _revenue_delta_pct(d) >= 0 else "diminuito",
            "direction_en": "increased" if _revenue_delta_pct(d) >= 0 else "decreased",
            "pct": abs(round(_revenue_delta_pct(d), 1)),
        },
    },

    # ─── 6b. Guest floor (Section A) ──────────────────────────────────────
    # identified_total is explicitly framed as a FLOOR, never as "how many
    # people were here" — see ReportGuestKpis docstring and CAVEAT 2.
    {
        "key": "guest_floor",
        "priority": 42,
        "condition": lambda d: (
            d.guests is not None and d.guests.available and d.guests.identified_total > 0
        ),
        "it": "Sono stati identificati almeno {n} ospiti tramite gli acquisti registrati — un valore minimo, non il conteggio totale dei partecipanti.",
        "en": "At least {n} guests were identified through recorded purchases — a floor, not a total attendance count.",
        "extract": lambda d: {"n": d.guests.identified_total},
    },

    # ─── 6c. Estimated purchase rate (Section D) ──────────────────────────
    # CAVEAT 2: the uncertainty must live IN the sentence ("of an estimated
    # N attendees"), never stated as a measured conversion rate.
    {
        "key": "estimated_purchase_rate",
        "priority": 44,
        "condition": lambda d: (
            d.revenue_decomposition is not None
            and d.revenue_decomposition.available
            and d.revenue_decomposition.purchase_rate_pct is not None
        ),
        "it": "Di una stima di {attendance} partecipanti, il {pct}% ha effettuato almeno un acquisto — una cifra derivata da una stima di pianificazione, non da una misurazione.",
        "en": "Of an estimated {attendance} attendees, {pct}% made at least one purchase — a figure derived from a planning estimate, not a measurement.",
        "extract": lambda d: {
            "attendance": d.revenue_decomposition.estimated_attendance,
            "pct": round(d.revenue_decomposition.purchase_rate_pct, 1),
        },
    },

    # ─── 6d. Forecast band hit rate (Section B) ───────────────────────────
    # "Actual fell within the predicted range in N of M hours" — the
    # single honest forecast-quality statement, deliberately not an error
    # percentage (per plan approval).
    {
        "key": "forecast_band_hit_rate",
        "priority": 46,
        "condition": lambda d: (
            d.forecast_accuracy is not None
            and d.forecast_accuracy.available
            and d.forecast_accuracy.band_hours_total
        ),
        "it": "Le previsioni di consumo hanno azzeccato la fascia attesa in {hits} delle {total} ore monitorate.",
        "en": "Demand forecasts landed within the predicted range in {hits} of {total} monitored hours.",
        "extract": lambda d: {
            "hits": d.forecast_accuracy.band_hits,
            "total": d.forecast_accuracy.band_hours_total,
        },
    },

    # ─── 7. Closing wrap (always fires, trails the section) ──────────────
    {
        "key": "closing_wrap",
        "priority": 100,
        "condition": lambda d: True,
        "it": "La serata si è conclusa alle {end_time}.",
        "en": "The night wrapped up at {end_time}.",
        "extract": lambda d: {
            "end_time": _fmt_hm(d.event.ended_at),
        },
    },
]
