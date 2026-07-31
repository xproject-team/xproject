"""Templates for the 'Cosa ha funzionato / What Worked' section.

Focuses on operational wins: no stock-outs, fast alert acknowledgement,
balanced performance. These are the sentences that tell Omar where his
team or his systems performed well.

Tone: congratulatory without being sycophantic. Specific, not generic.
"""
from __future__ import annotations

from statistics import median

from app.modules.reports.schemas import ReportData


def _ack_times_minutes(d: ReportData) -> list[float]:
    """Seconds-to-acknowledge per alert that was actually acknowledged."""
    out = []
    for a in d.alerts:
        if a.acknowledged_at is not None:
            delta = (a.acknowledged_at - a.fired_at).total_seconds() / 60.0
            if delta >= 0:
                out.append(delta)
    return out


def _stockout_count(d: ReportData) -> int:
    return sum(1 for s in d.stock_rows if s.stock_out_occurred)


TEMPLATES_WORKED = [
    # ─── 1. No stock-outs at all (best case) ──────────────────────────────
    {
        "key": "no_stockouts",
        "priority": 10,
        "condition": lambda d: (
            len(d.stock_rows) > 0
            and _stockout_count(d) == 0
        ),
        "it": "La gestione delle scorte è stata impeccabile — nessun prodotto è finito durante la serata.",
        "en": "Stock management was on point — no product ran out during the event.",
        "extract": lambda d: {},
    },

    # ─── 2. Minor stock-outs (1–2 only) ───────────────────────────────────
    # Pluralization is language-specific: IT has noun + adjective agreement,
    # EN just needs an "s" on the noun. Extract supplies both sets of suffixes
    # so each template string references only the ones it needs.
    {
        "key": "minor_stockouts",
        "priority": 15,
        "condition": lambda d: 1 <= _stockout_count(d) <= 2,
        "it": "Solo {n} esauriment{it_noun} di scorta registrat{it_adj} — nel complesso, il team ha gestito bene l'inventario.",
        "en": "Only {n} stock-out{en_s} recorded — overall, the team handled inventory well.",
        "extract": lambda d: {
            "n": _stockout_count(d),
            "it_noun": "i" if _stockout_count(d) > 1 else "o",  # esaurimento/esaurimenti
            "it_adj":  "i" if _stockout_count(d) > 1 else "o",  # registrato/registrati
            "en_s":    "s" if _stockout_count(d) > 1 else "",
        },
    },

    # ─── 3. Fast median acknowledgement time ─────────────────────────────
    {
        "key": "fast_ack_median",
        "priority": 20,
        "condition": lambda d: (
            len(_ack_times_minutes(d)) > 0
            and median(_ack_times_minutes(d)) < 5.0
        ),
        "it": "Gli alert sono stati gestiti con prontezza — tempo mediano di risposta sotto i 5 minuti.",
        "en": "Alerts were handled promptly — median response time under 5 minutes.",
        "extract": lambda d: {},
    },

    # ─── 4. 100% alert acknowledgement ───────────────────────────────────
    {
        "key": "all_alerts_ack",
        "priority": 30,
        "condition": lambda d: (
            len(d.alerts) > 0
            and all(a.acknowledged_at is not None for a in d.alerts)
        ),
        "it": "Ogni alert è stato preso in carico — nessuna segnalazione è rimasta ignorata.",
        "en": "Every alert was acknowledged — no warning went unaddressed.",
        "extract": lambda d: {},
    },

    # ─── 5. Balanced performance across bars ─────────────────────────────
    {
        "key": "high_per_bar_efficiency",
        "priority": 40,
        "condition": lambda d: (
            len(d.bar_revenues) >= 3
            and d.bar_revenues[0].transactions_count
            < 3 * (sum(b.transactions_count for b in d.bar_revenues) / len(d.bar_revenues))
        ),
        "it": "Le prestazioni dei bar sono state omogenee — nessuna singola postazione è stata sovraccaricata.",
        "en": "Performance was even across the bars — no single station was overwhelmed.",
        "extract": lambda d: {},
    },

    # ─── 6. Silent night — no alerts fired at all ────────────────────────
    {
        "key": "no_alerts",
        "priority": 50,
        "condition": lambda d: len(d.alerts) == 0,
        "it": "Serata silenziosa — nessun intervento del sistema è stato necessario.",
        "en": "A silent night — no system interventions required.",
        "extract": lambda d: {},
    },

    # ─── 7. Perfect forecast calibration (Section B) ──────────────────────
    {
        "key": "forecast_fully_calibrated",
        "priority": 60,
        "condition": lambda d: (
            d.forecast_accuracy is not None
            and d.forecast_accuracy.available
            and d.forecast_accuracy.band_hours_total
            and d.forecast_accuracy.band_hits == d.forecast_accuracy.band_hours_total
        ),
        "it": "Il modello di previsione della domanda è stato preciso — il consumo reale è rimasto nella fascia attesa per tutta la serata.",
        "en": "The demand forecast held up well — actual consumption stayed within the predicted range all night.",
        "extract": lambda d: {},
    },

    # ─── 8. Loyal returning audience (Section A) ──────────────────────────
    {
        "key": "loyal_returning_guests",
        "priority": 65,
        "condition": lambda d: (
            d.guests is not None
            and d.guests.available
            and d.guests.identified_total > 0
            and (d.guests.returning_count / d.guests.identified_total) >= 0.3
        ),
        "it": "Il {pct}% degli ospiti identificati aveva già partecipato a un evento precedente — un pubblico fedele.",
        "en": "{pct}% of identified guests had attended a previous event — a loyal audience.",
        "extract": lambda d: {
            "pct": round(100 * d.guests.returning_count / d.guests.identified_total),
        },
    },
]
