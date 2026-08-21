"""PDF rendering for post-event reports.

Public function: render_report_pdf(data) -> bytes

Pure function. Takes a populated ReportData (with narrative already rendered)
and returns a byte blob of the generated PDF. Does NOT touch disk, DB, or
network. ReportService persists the bytes into reports.pdf_bytes.

Stack: ReportLab 4.x + Matplotlib 3.x (Agg backend, no GUI).
Layout: A4 portrait, 2cm margins. ~3 min read time.

Sections (page order approved 2026-07-31, extends spec §3):
  0. Cover page             — event identity + hero revenue + guests (planning figure)
  1. Comparison             — this event vs. previous event / season average
  2. Executive Narrative    — now also speaks to guests + forecast accuracy
  3. Guests                 — identified-guest detail (a FLOOR, not a headcount)
  4. Revenue Breakdown      — bar chart + revenue decomposition + top/lowest products
  5. Forecast vs. Actual    — demand-model band-hit-rate detail
  6. Alerts Timeline

(Stock Reality Check was removed Day 14, matching the web view's 2026-08-10
removal: it rendered bar_stock rows, a table the live depletion system
abandoned in June for event_storage's supplier-stock model — the PDF was
presenting stale numbers with full confidence. The aggregator still stores
stock_rows in data_json; no renderer shows them.)

Every new section (1, 3, 4's decomposition/products, 5) degrades gracefully:
when its ReportData field is None (older report, feature shipped later) or
.available is False (data not populated for this event), the section
renders its heading plus a plain "not available" line — it is NEVER
omitted silently and NEVER raises. See each _*_section function.

Bilingual: ReportData.language drives every label. IT + EN labels live in
LABELS_IT and LABELS_EN dicts — picked at render time, same pattern as the
narrative engine.

Spec: docs/report-module-spec.md §3 + §11 (performance target: <500ms per PDF).
"""
from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal

import matplotlib
matplotlib.use("Agg")  # must come BEFORE pyplot import (no display server in prod)
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.modules.reports.schemas import (
    ReportAlertRow,
    ReportBarRevenue,
    ReportComparisonMetric,
    ReportData,
    ReportProductRow,
)


# ─── Bilingual labels (IT primary, EN mirror) ────────────────────────────────

LABELS_IT = {
    "cover_subtitle": "Report Post-Evento",
    "total_revenue": "Fatturato Totale",
    "bars": "Bar",
    "duration": "Durata",
    "guests": "Ospiti",
    "prepared_for": "Preparato per Omar Bouznad · Noma Group",
    "executive_summary": "Sintesi Esecutiva",
    "what_happened": "Cosa è successo",
    "what_worked": "Cosa ha funzionato",
    "what_next": "Cosa fare al prossimo",
    "revenue_breakdown": "Fatturato per Bar",
    "no_revenue": "Nessun dato di fatturato registrato.",
    "revenue_per_hour": "per ora",
    "revenue_per_bar_avg": "media bar",
    "top_product": "Prodotto top",
    "unmapped_revenue_note": "Include {amount} da ordini non ancora associati a un bar.",
    "product": "Prodotto",
    "alerts_section": "Cronologia Alert",
    "alerts_empty": "Nessun alert registrato — la serata è filata liscia.",
    "time": "Ora",
    "severity": "Gravità",
    "bar": "Bar",
    "title": "Titolo",
    "acknowledged_by": "Confermato da",
    "unack": "Non confermato",
    "generated": "Generato",
    "version": "Versione",

    # Comparison (Section C)
    "comparison_section": "Confronto con gli Eventi Precedenti",
    "comparison_empty": "Nessun evento precedente disponibile per il confronto.",
    "metric": "Metrica",
    "current": "Attuale",
    "vs_previous": "vs. Evento Precedente",
    "vs_season": "vs. Media Stagione",
    "guest_metrics_note": "Il confronto sugli ospiti è disponibile a partire da {date}.",
    "mixed_revenue_note": "Il fatturato degli eventi precedenti è stato misurato con il metodo precedente (movimenti di magazzino) — piccole differenze sono di natura definitoria.",

    # Guests (Section A)
    "guests_section": "Ospiti",
    "guests_empty": "Dati sugli ospiti non ancora disponibili per questo evento.",
    "estimated_attendance": "Affluenza stimata (dato di pianificazione)",
    "identified_floor_note": "Totale identificato tramite acquisti registrati — un valore minimo, non il conteggio totale dei partecipanti.",
    "identified_total": "Ospiti Identificati",
    "registered": "Registrati",
    "unknown": "Sconosciuti",
    "whale": "Whale",
    "regular": "Regolari",
    "light": "Leggeri",
    "returning": "Di Ritorno",
    "new_guests": "Nuovi",

    # Revenue decomposition (Section D)
    "decomposition_section": "Scomposizione del Fatturato",
    "decomposition_empty": "Dati insufficienti per la scomposizione del fatturato.",
    "purchase_rate_note": "Tasso di acquisto stimato — calcolato su un'affluenza pianificata, non misurata.",
    "purchasers": "Acquirenti",
    "purchase_rate": "Tasso di Acquisto (stimato)",
    "orders_per_purchaser": "Ordini per Acquirente",
    "aov": "Scontrino Medio",

    # Top / lowest-selling products (Section E)
    "top_products_section": "Prodotti Più Venduti",
    "lowest_products_section": "Prodotti Meno Venduti",
    "lowest_products_note": "Vendite basse possono indicare un prodotto nuovo, un prezzo elevato o una postazione poco frequentata — non necessariamente un problema.",
    "units_sold": "Unità",
    "revenue_col": "Fatturato",

    # Forecast vs. actual (Section B)
    "forecast_section": "Previsione vs. Consuntivo",
    "forecast_empty": "Nessun modello di previsione disponibile per questo evento.",
    "band_hit_rate": "La domanda reale è rientrata nella fascia prevista in {hits} delle {total} ore monitorate.",
    "hour_col": "Ora",
    "predicted": "Previsto",
    "actual": "Consuntivo",
    "band": "Fascia",
    "in_band": "Sì",
    "out_of_band": "No",
}

LABELS_EN = {
    "cover_subtitle": "Post-Event Report",
    "total_revenue": "Total Revenue",
    "bars": "Bars",
    "duration": "Duration",
    "guests": "Guests",
    "prepared_for": "Prepared for Omar Bouznad · Noma Group",
    "executive_summary": "Executive Summary",
    "what_happened": "What Happened",
    "what_worked": "What Worked",
    "what_next": "What To Do Next",
    "revenue_breakdown": "Revenue by Bar",
    "no_revenue": "No revenue data recorded.",
    "revenue_per_hour": "per hour",
    "revenue_per_bar_avg": "bar average",
    "top_product": "Top product",
    "unmapped_revenue_note": "Includes {amount} from orders not yet mapped to a bar.",
    "product": "Product",
    "alerts_section": "Alerts Timeline",
    "alerts_empty": "No alerts recorded — the night ran smoothly.",
    "time": "Time",
    "severity": "Severity",
    "bar": "Bar",
    "title": "Title",
    "acknowledged_by": "Acknowledged by",
    "unack": "Unacknowledged",
    "generated": "Generated",
    "version": "Version",

    # Comparison (Section C)
    "comparison_section": "Comparison with Previous Events",
    "comparison_empty": "No previous event available for comparison.",
    "metric": "Metric",
    "current": "Current",
    "vs_previous": "vs. Previous Event",
    "vs_season": "vs. Season Average",
    "guest_metrics_note": "Guest comparison is available from {date} onward.",
    "mixed_revenue_note": "Earlier events' revenue was measured with the previous method (stock movements) — small differences are definitional.",

    # Guests (Section A)
    "guests_section": "Guests",
    "guests_empty": "Guest data not yet available for this event.",
    "estimated_attendance": "Estimated attendance (planning figure)",
    "identified_floor_note": "Total identified through recorded purchases — a floor, not a total attendance count.",
    "identified_total": "Identified Guests",
    "registered": "Registered",
    "unknown": "Unknown",
    "whale": "Whale",
    "regular": "Regular",
    "light": "Light",
    "returning": "Returning",
    "new_guests": "New",

    # Revenue decomposition (Section D)
    "decomposition_section": "Revenue Decomposition",
    "decomposition_empty": "Insufficient data for revenue decomposition.",
    "purchase_rate_note": "Estimated purchase rate — computed against a planned, not measured, attendance figure.",
    "purchasers": "Purchasers",
    "purchase_rate": "Purchase Rate (estimated)",
    "orders_per_purchaser": "Orders per Purchaser",
    "aov": "Average Order Value",

    # Top / lowest-selling products (Section E)
    "top_products_section": "Top-Selling Products",
    "lowest_products_section": "Lowest-Selling Products",
    "lowest_products_note": "Low sales may reflect a new item, a high price, or a quiet bar placement — not necessarily a problem.",
    "units_sold": "Units",
    "revenue_col": "Revenue",

    # Forecast vs. actual (Section B)
    "forecast_section": "Forecast vs. Actual",
    "forecast_empty": "No demand forecast model available for this event.",
    "band_hit_rate": "Actual demand fell within the predicted range in {hits} of {total} monitored hours.",
    "hour_col": "Hour",
    "predicted": "Predicted",
    "actual": "Actual",
    "band": "Band",
    "in_band": "Yes",
    "out_of_band": "No",
}


# ─── Design tokens (match frontend Tailwind palette) ─────────────────────────

COLOR_PRIMARY      = colors.HexColor("#1E5A8D")
COLOR_PRIMARY_DARK = colors.HexColor("#0F3254")
COLOR_TEXT         = colors.HexColor("#1A202C")
COLOR_TEXT_MUTED   = colors.HexColor("#4A5568")
COLOR_TEXT_LIGHT   = colors.HexColor("#718096")
COLOR_BORDER       = colors.HexColor("#E2E8F0")
COLOR_BG_LIGHT     = colors.HexColor("#F7FAFC")
COLOR_STOCKOUT     = colors.HexColor("#742A2A")  # also the out-of-band accent in Forecast
COLOR_WHITE        = colors.white

SEVERITY_COLORS = {
    "info":     (colors.HexColor("#BEE3F8"), colors.HexColor("#2C5282")),
    "warning":  (colors.HexColor("#FEEBC8"), colors.HexColor("#744210")),
    "critical": (colors.HexColor("#FED7D7"), colors.HexColor("#742A2A")),
    "anomaly":  (colors.HexColor("#E9D8FD"), colors.HexColor("#44337A")),
}


# ─── Paragraph styles ────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["CoverTitle"] = ParagraphStyle(
        "CoverTitle", parent=base["Title"],
        fontSize=28, leading=32, textColor=COLOR_WHITE,
        alignment=TA_LEFT, spaceAfter=0,
    )
    styles["CoverSub"] = ParagraphStyle(
        "CoverSub", parent=base["Normal"],
        fontSize=10, textColor=COLOR_WHITE, alignment=TA_LEFT,
    )
    styles["CoverLabel"] = ParagraphStyle(
        "CoverLabel", parent=base["Normal"],
        fontSize=8, textColor=COLOR_WHITE, alignment=TA_LEFT,
    )
    styles["CoverValue"] = ParagraphStyle(
        "CoverValue", parent=base["Normal"],
        fontSize=24, leading=28, textColor=COLOR_WHITE,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
    )
    styles["SectionHeading"] = ParagraphStyle(
        "SectionHeading", parent=base["Heading2"],
        fontSize=9, textColor=COLOR_TEXT_LIGHT,
        fontName="Helvetica-Bold", spaceAfter=8,
    )
    styles["Subheading"] = ParagraphStyle(
        "Subheading", parent=base["Heading3"],
        fontSize=12, textColor=COLOR_TEXT,
        fontName="Helvetica-Bold", spaceAfter=4,
    )
    styles["Body"] = ParagraphStyle(
        "Body", parent=base["Normal"],
        fontSize=10, leading=14, textColor=COLOR_TEXT,
        alignment=TA_LEFT, spaceAfter=8,
    )
    styles["BodyMuted"] = ParagraphStyle(
        "BodyMuted", parent=base["Normal"],
        fontSize=9, leading=12, textColor=COLOR_TEXT_MUTED,
        alignment=TA_LEFT, spaceAfter=6,
    )
    styles["BulletRow"] = ParagraphStyle(
        "BulletRow", parent=base["Normal"],
        fontSize=10, leading=14, textColor=COLOR_TEXT,
        leftIndent=12, spaceAfter=4,
    )
    styles["Footer"] = ParagraphStyle(
        "Footer", parent=base["Normal"],
        fontSize=8, textColor=COLOR_TEXT_LIGHT, alignment=TA_LEFT,
    )
    return styles


# ─── Formatting helpers ──────────────────────────────────────────────────────

def _fmt_eur(value) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"€{n:,.0f}".replace(",", ".")


def _fmt_dt(iso: datetime | None, locale: str = "it") -> str:
    if iso is None:
        return "—"
    if locale == "it":
        return iso.strftime("%d %b %Y, %H:%M")
    return iso.strftime("%d %b %Y, %H:%M")


def _fmt_time(iso: datetime | None) -> str:
    if iso is None:
        return "—"
    return iso.strftime("%H:%M")


def _fmt_num(value, decimals: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value, decimals: int = 1, signed: bool = False) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and n > 0 else ""
    return f"{sign}{n:.{decimals}f}%"


def _fmt_cents(value) -> str:
    if value is None:
        return "—"
    try:
        return _fmt_eur(float(value) / 100.0)
    except (TypeError, ValueError):
        return "—"


def _fmt_metric_value(value, unit: str | None) -> str:
    """Comparison-table value, formatted by the metric's declared unit.

    'eur' → currency, 'count' → whole number. None (a report generated
    before units were stored) keeps the legacy one-decimal rendering so
    frozen snapshots re-render exactly as they always did.
    """
    if unit == "eur":
        return _fmt_eur(value)
    if unit == "count":
        return _fmt_num(value, 0)
    return _fmt_num(value, 1)


# ─── Revenue chart (matplotlib -> PNG bytes) ─────────────────────────────────

def _render_revenue_chart(bar_revenues: list[ReportBarRevenue]) -> bytes | None:
    """Horizontal bar chart, returns PNG bytes or None if no data."""
    if not bar_revenues:
        return None

    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.5 * len(bar_revenues) + 1)), dpi=110)
    names = [b.bar_name for b in bar_revenues]
    values = [float(b.revenue) for b in bar_revenues]

    # Reverse so the top-earner is at the top of the chart
    ax.barh(names[::-1], values[::-1], color="#1E5A8D", height=0.6)
    ax.set_xlabel("€", fontsize=9, color="#4A5568")
    ax.tick_params(axis="y", labelsize=9, colors="#1A202C")
    ax.tick_params(axis="x", labelsize=8, colors="#4A5568")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E2E8F0")
    ax.spines["bottom"].set_color("#E2E8F0")
    ax.grid(axis="x", linestyle=":", color="#E2E8F0", alpha=0.8)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ─── Section builders ────────────────────────────────────────────────────────

def _cover_page(data: ReportData, styles, labels):
    """Blue hero block on page 1 — mirrors the frontend CoverBlock."""
    hero_cell_contents = [
        [
            Paragraph(labels["cover_subtitle"].upper(), styles["CoverLabel"]),
        ],
        [
            Paragraph(data.event.event_name, styles["CoverTitle"]),
        ],
        [
            Paragraph(
                f"{data.event.venue_name} · {_fmt_dt(data.event.started_at, data.language)}",
                styles["CoverSub"],
            ),
        ],
        [Spacer(1, 12)],
        [
            Paragraph(labels["total_revenue"].upper(), styles["CoverLabel"]),
        ],
        [
            Paragraph(_fmt_eur(data.revenue_kpis.total_revenue), styles["CoverValue"]),
        ],
    ]

    hero = Table(hero_cell_contents, colWidths=[17 * cm])
    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (0, 0), 24),
        ("BOTTOMPADDING", (0, -1), (0, -1), 24),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    # KPIs row: bars, duration, maybe guests
    kpi_cells = [
        [Paragraph(labels["bars"].upper(), styles["CoverLabel"]),
         Paragraph(labels["duration"].upper(), styles["CoverLabel"])],
        [Paragraph(f"<b>{data.event.bars_count}</b>", styles["CoverSub"]),
         Paragraph(f"<b>{_fmt_num(data.event.duration_hours, 1)}h</b>", styles["CoverSub"])],
    ]
    if data.event.guests_served is not None:
        kpi_cells[0].append(Paragraph(labels["guests"].upper(), styles["CoverLabel"]))
        kpi_cells[1].append(Paragraph(f"<b>{data.event.guests_served}</b>", styles["CoverSub"]))
    elif data.event.expected_guest_count is not None:
        # No measured headcount yet (guests_served is a v1.2/ticketing
        # field) — show the planning estimate instead, but the label
        # itself must carry the caveat (CAVEAT 2): never presented as a
        # measured fact anywhere it appears, including here.
        kpi_cells[0].append(Paragraph(labels["estimated_attendance"].upper(), styles["CoverLabel"]))
        kpi_cells[1].append(Paragraph(f"<b>{data.event.expected_guest_count}</b>", styles["CoverSub"]))

    col_count = len(kpi_cells[0])
    kpi_table = Table(kpi_cells, colWidths=[17 * cm / col_count] * col_count)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 24),
    ]))

    footer = Paragraph(labels["prepared_for"], styles["Footer"])

    return [hero, kpi_table, Spacer(1, 18), footer]


def _comparison_section(data: ReportData, styles, labels):
    """Section C — this event vs. previous event / season average.

    available=False (or comparison is None on an older report) is the
    normal state for a tenant's very first event — rendered as a plain
    "not available" line, never an error or a missing page.
    """
    out = [Paragraph(labels["comparison_section"].upper(), styles["SectionHeading"])]

    if data.comparison is None or not data.comparison.available or not data.comparison.metrics:
        out.append(Paragraph(labels["comparison_empty"], styles["BodyMuted"]))
        return out

    table_data = [[
        labels["metric"], labels["current"], labels["vs_previous"], labels["vs_season"],
    ]]
    metric: ReportComparisonMetric
    for metric in data.comparison.metrics:
        table_data.append([
            metric.label,
            _fmt_metric_value(metric.current_value, metric.unit),
            _fmt_pct(metric.previous_event_delta_pct, signed=True),
            _fmt_pct(metric.season_avg_delta_pct, signed=True),
        ])

    t = Table(table_data, colWidths=[5.5 * cm, 3.5 * cm, 4 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))
    out.append(t)

    if data.comparison.previous_event_name:
        out.append(Spacer(1, 4))
        out.append(Paragraph(
            f"{labels['vs_previous']}: {data.comparison.previous_event_name}",
            styles["BodyMuted"],
        ))

    # NOT backfilled onto older reports (see ReportComparison docstring) —
    # say so plainly rather than silently showing fewer rows.
    if data.comparison.guest_metrics_available_from and not any(
        m.label == "Identified Guests" for m in data.comparison.metrics
    ):
        out.append(Paragraph(
            labels["guest_metrics_note"].format(date=data.comparison.guest_metrics_available_from),
            styles["BodyMuted"],
        ))

    # Mixed measurement basis (Day 14 migration): earlier events'
    # figures came from the old stock-movement method — the delta
    # carries a definitional component, so say so under the table.
    if data.comparison.mixed_revenue_sources:
        out.append(Paragraph(labels["mixed_revenue_note"], styles["BodyMuted"]))

    return out


def _guests_section(data: ReportData, styles, labels):
    """Section A — identified-guest detail.

    CAVEAT 2: identified_total is a FLOOR on attendance, not attendance
    itself — the note is rendered directly under the headline number,
    not left to a code comment.
    """
    out = [Paragraph(labels["guests_section"].upper(), styles["SectionHeading"])]

    if data.guests is None or not data.guests.available:
        out.append(Paragraph(labels["guests_empty"], styles["BodyMuted"]))
        return out

    g = data.guests
    out.append(Paragraph(f"<b>{g.identified_total}</b>  {labels['identified_total']}", styles["Subheading"]))
    out.append(Paragraph(labels["identified_floor_note"], styles["BodyMuted"]))
    out.append(Spacer(1, 6))

    rows = [
        (labels["registered"], g.registered_count),
        (labels["guests"], g.guest_count),
        (labels["unknown"], g.unknown_count),
        (labels["whale"], g.whale_count),
        (labels["regular"], g.regular_count),
        (labels["light"], g.light_count),
        (labels["returning"], g.returning_count),
        (labels["new_guests"], g.new_count),
    ]
    table_data = [[label for label, _ in rows], [str(value) for _, value in rows]]
    t = Table(table_data, colWidths=[17 * cm / len(rows)] * len(rows))
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, 1), COLOR_TEXT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    out.append(t)

    return out


def _forecast_section(data: ReportData, styles, labels):
    """Section B — demand-model forecast vs. actual, hour by hour.

    The band-hit-rate headline ("actual fell within the predicted range
    in N of M hours") is the single honest forecast-quality statement —
    deliberately not an error percentage (plan approval, Section B).
    """
    out = [Paragraph(labels["forecast_section"].upper(), styles["SectionHeading"])]

    if data.forecast_accuracy is None or not data.forecast_accuracy.available:
        out.append(Paragraph(labels["forecast_empty"], styles["BodyMuted"]))
        return out

    fc = data.forecast_accuracy
    if fc.band_hours_total:
        out.append(Paragraph(
            labels["band_hit_rate"].format(hits=fc.band_hits, total=fc.band_hours_total),
            styles["Subheading"],
        ))
        out.append(Spacer(1, 6))

    if not fc.hours:
        return out

    table_data = [[
        labels["hour_col"], labels["predicted"], labels["actual"], labels["band"],
    ]]
    for h in fc.hours:
        table_data.append([
            _fmt_num(h.hour_of_event, 0),
            _fmt_num(h.predicted, 0),
            _fmt_num(h.actual, 0),
            labels["in_band"] if h.within_band else labels["out_of_band"],
        ])

    t = Table(table_data, colWidths=[3 * cm, 4 * cm, 4 * cm, 3 * cm])
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]
    for i, h in enumerate(fc.hours, start=1):
        if not h.within_band:
            style_cmds.append(("TEXTCOLOR", (3, i), (3, i), COLOR_STOCKOUT))
            style_cmds.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style_cmds))
    out.append(t)

    return out


def _narrative_section(data: ReportData, styles, labels):
    out = [Paragraph(labels["executive_summary"].upper(), styles["SectionHeading"])]

    out.append(Paragraph(labels["what_happened"], styles["Subheading"]))
    out.append(Paragraph(data.narrative.what_happened or "—", styles["Body"]))

    out.append(Paragraph(labels["what_worked"], styles["Subheading"]))
    out.append(Paragraph(data.narrative.what_worked or "—", styles["Body"]))

    out.append(Paragraph(labels["what_next"], styles["Subheading"]))
    if data.narrative.what_next:
        for bullet in data.narrative.what_next:
            out.append(Paragraph(f"→  {bullet}", styles["BulletRow"]))
    else:
        out.append(Paragraph("—", styles["Body"]))

    return out


def _revenue_section(data: ReportData, styles, labels):
    out = [Paragraph(labels["revenue_breakdown"].upper(), styles["SectionHeading"])]

    chart_bytes = _render_revenue_chart(data.bar_revenues)
    if chart_bytes:
        img = Image(io.BytesIO(chart_bytes), width=16 * cm, height=None)
        img._restrictSize(16 * cm, 10 * cm)
        out.append(img)
    else:
        out.append(Paragraph(labels["no_revenue"], styles["BodyMuted"]))

    # KPI strip
    kpi_data = [
        [
            Paragraph(f"<b>{labels['revenue_per_hour'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['revenue_per_bar_avg'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['top_product'].upper()}</b>", styles["Footer"]),
        ],
        [
            Paragraph(f"<b>{_fmt_eur(data.revenue_kpis.revenue_per_hour)}</b>", styles["Body"]),
            Paragraph(f"<b>{_fmt_eur(data.revenue_kpis.revenue_per_bar_avg)}</b>", styles["Body"]),
            Paragraph(
                f"<b>{data.revenue_kpis.top_product_name or '—'}</b>"
                + (f" ({data.revenue_kpis.top_product_units})"
                   if data.revenue_kpis.top_product_units else ""),
                styles["Body"],
            ),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[5.67 * cm] * 3)
    kpi_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    out.append(Spacer(1, 6))
    out.append(kpi_table)

    # Unmapped-order money: part of the total, attributable to no bar.
    # Shown explicitly rather than letting the bar chart appear to
    # account for everything (Day 14 migration; dashboard precedent).
    unmapped = getattr(data.revenue_kpis, "unmapped_revenue", None)
    if unmapped:
        out.append(Paragraph(
            labels["unmapped_revenue_note"].format(amount=_fmt_eur(unmapped)),
            styles["BodyMuted"],
        ))

    out.extend(_decomposition_subsection(data, styles, labels))
    out.extend(_products_subsection(data, styles, labels))

    return out


def _decomposition_subsection(data: ReportData, styles, labels):
    """Section D — attendance x purchase rate x orders/purchaser x AOV.

    CAVEAT 2: purchase_rate_pct is derived from expected_guest_count, a
    planning estimate — the footnote is mandatory, not optional, on
    every surface that renders this number.
    """
    out = [Spacer(1, 12), Paragraph(labels["decomposition_section"].upper(), styles["SectionHeading"])]

    rd = data.revenue_decomposition
    if rd is None or not rd.available:
        out.append(Paragraph(labels["decomposition_empty"], styles["BodyMuted"]))
        return out

    table_data = [
        [
            Paragraph(f"<b>{labels['estimated_attendance'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['purchasers'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['purchase_rate'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['orders_per_purchaser'].upper()}</b>", styles["Footer"]),
            Paragraph(f"<b>{labels['aov'].upper()}</b>", styles["Footer"]),
        ],
        [
            Paragraph(f"<b>{rd.estimated_attendance if rd.estimated_attendance is not None else '—'}</b>", styles["Body"]),
            Paragraph(f"<b>{rd.purchasers if rd.purchasers is not None else '—'}</b>", styles["Body"]),
            Paragraph(f"<b>{_fmt_pct(rd.purchase_rate_pct)}</b>", styles["Body"]),
            Paragraph(f"<b>{_fmt_num(rd.orders_per_purchaser, 1)}</b>", styles["Body"]),
            Paragraph(f"<b>{_fmt_cents(rd.average_order_value_cents)}</b>", styles["Body"]),
        ],
    ]
    t = Table(table_data, colWidths=[3.4 * cm] * 5)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    out.append(t)
    out.append(Paragraph(labels["purchase_rate_note"], styles["BodyMuted"]))

    return out


def _products_subsection(data: ReportData, styles, labels):
    """Section E — top and lowest-selling products.

    "lowest_selling", never "bottom"/"worst" — the note underneath
    frames it as a question (new item? priced high? quiet bar?), never
    a verdict (plan approval, Section E).
    """
    out = [Spacer(1, 12)]

    pp = data.product_performance
    if pp is None or (not pp.top_products and not pp.lowest_selling_products):
        return out

    def _product_table(rows: list[ReportProductRow]) -> Table:
        table_data = [[labels["product"], labels["units_sold"], labels["revenue_col"]]]
        for r in rows:
            table_data.append([r.product_name, str(r.units_sold), _fmt_cents(r.revenue_cents)])
        t = Table(table_data, colWidths=[9 * cm, 4 * cm, 4 * cm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ]))
        return t

    if pp.top_products:
        out.append(Paragraph(labels["top_products_section"], styles["Subheading"]))
        out.append(_product_table(pp.top_products))
        out.append(Spacer(1, 10))

    if pp.lowest_selling_products:
        out.append(Paragraph(labels["lowest_products_section"], styles["Subheading"]))
        out.append(_product_table(pp.lowest_selling_products))
        out.append(Paragraph(labels["lowest_products_note"], styles["BodyMuted"]))

    return out


def _alerts_section(data: ReportData, styles, labels):
    out = [Paragraph(labels["alerts_section"].upper(), styles["SectionHeading"])]

    if not data.alerts:
        out.append(Paragraph(f"✓  {labels['alerts_empty']}", styles["BodyMuted"]))
        return out

    # Header row
    table_data = [[
        labels["time"],
        labels["severity"],
        labels["bar"],
        labels["title"],
        labels["acknowledged_by"],
    ]]
    for a in data.alerts:
        ack = (f"{_fmt_time(a.acknowledged_at)} · {a.acknowledged_by_name or ''}".strip(" ·")
               if a.acknowledged_at else labels["unack"])
        table_data.append([
            _fmt_time(a.fired_at),
            a.severity.upper(),
            a.bar_name or "—",
            a.title,
            ack,
        ])

    t = Table(table_data, colWidths=[1.8 * cm, 2.2 * cm, 3 * cm, 6.5 * cm, 3.5 * cm])
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]
    # Severity pill styling
    for i, a in enumerate(data.alerts, start=1):
        bg, fg = SEVERITY_COLORS.get(a.severity, (COLOR_BG_LIGHT, COLOR_TEXT_MUTED))
        style_cmds.append(("BACKGROUND", (1, i), (1, i), bg))
        style_cmds.append(("TEXTCOLOR", (1, i), (1, i), fg))
        style_cmds.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
        style_cmds.append(("ALIGN", (1, i), (1, i), "CENTER"))

    t.setStyle(TableStyle(style_cmds))
    out.append(t)
    return out


# ─── Public entry point ──────────────────────────────────────────────────────

def render_report_pdf(data: ReportData) -> bytes:
    """Render a full ReportData snapshot into a PDF byte blob.

    Caller stores the return value in reports.pdf_bytes. Does not touch
    disk, DB, network. Fails loudly — exceptions propagate up to the
    service layer which marks the row failed.
    """
    labels = LABELS_IT if data.language == "it" else LABELS_EN
    styles = _build_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"{data.event.event_name} — {labels['cover_subtitle']}",
        author="XProject",
    )

    story = []
    story.extend(_cover_page(data, styles, labels))
    story.append(PageBreak())
    story.extend(_comparison_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_narrative_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_guests_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_revenue_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_forecast_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_alerts_section(data, styles, labels))

    # Trailing footer with version + timestamp
    story.append(Spacer(1, 18))
    footer_text = (
        f"{labels['version']} {data.version} · "
        f"{labels['generated']} {_fmt_dt(data.generated_at, data.language)}"
    )
    story.append(Paragraph(footer_text, styles["Footer"]))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
