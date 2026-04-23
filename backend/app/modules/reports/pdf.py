"""PDF rendering for post-event reports.

Public function: render_report_pdf(data) -> bytes

Pure function. Takes a populated ReportData (with narrative already rendered)
and returns a byte blob of the generated PDF. Does NOT touch disk, DB, or
network. ReportService persists the bytes into reports.pdf_bytes.

Stack: ReportLab 4.x + Matplotlib 3.x (Agg backend, no GUI).
Layout: 5 pages on A4 portrait, 2cm margins. ~3 min read time.

Sections (mirror spec §3):
  0. Cover page       — event identity + hero revenue
  1. Executive Narrative
  2. Revenue Breakdown (includes a PNG bar chart)
  3. Stock Reality Check (per-bar tables)
  4. Alerts Timeline

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
    ReportData,
    ReportStockRow,
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
    "stock_section": "Stato delle Scorte",
    "stock_empty": "Nessun dato di scorta disponibile.",
    "product": "Prodotto",
    "opening": "Iniziali",
    "closing": "Finali",
    "consumed": "Consumati",
    "burn_rate": "Consumo/h",
    "stockout": "ESAURITO",
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
    "stock_section": "Stock Reality Check",
    "stock_empty": "No stock data available.",
    "product": "Product",
    "opening": "Opening",
    "closing": "Closing",
    "consumed": "Consumed",
    "burn_rate": "Burn/h",
    "stockout": "STOCK-OUT",
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
}


# ─── Design tokens (match frontend Tailwind palette) ─────────────────────────

COLOR_PRIMARY      = colors.HexColor("#1E5A8D")
COLOR_PRIMARY_DARK = colors.HexColor("#0F3254")
COLOR_TEXT         = colors.HexColor("#1A202C")
COLOR_TEXT_MUTED   = colors.HexColor("#4A5568")
COLOR_TEXT_LIGHT   = colors.HexColor("#718096")
COLOR_BORDER       = colors.HexColor("#E2E8F0")
COLOR_BG_LIGHT     = colors.HexColor("#F7FAFC")
COLOR_STOCKOUT_BG  = colors.HexColor("#FFF5F5")
COLOR_STOCKOUT     = colors.HexColor("#742A2A")
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

    return out


def _stock_section(data: ReportData, styles, labels):
    out = [Paragraph(labels["stock_section"].upper(), styles["SectionHeading"])]

    if not data.stock_rows:
        out.append(Paragraph(labels["stock_empty"], styles["BodyMuted"]))
        return out

    # Group by bar
    grouped: dict[str, list[ReportStockRow]] = {}
    for row in data.stock_rows:
        grouped.setdefault(row.bar_name, []).append(row)

    for bar_name, rows in grouped.items():
        out.append(Paragraph(f"<b>{bar_name}</b>", styles["Subheading"]))

        table_data = [[
            labels["product"], labels["opening"], labels["closing"],
            labels["consumed"], labels["burn_rate"], "",
        ]]
        for r in rows:
            stockout_badge = labels["stockout"] if r.stock_out_occurred else ""
            table_data.append([
                r.product_name,
                _fmt_num(r.opening_qty, 0),
                _fmt_num(r.closing_qty, 0),
                _fmt_num(r.consumed_qty, 0),
                _fmt_num(r.burn_rate_per_hour, 1),
                stockout_badge,
            ])

        t = Table(table_data, colWidths=[5.5 * cm, 2 * cm, 2 * cm, 2 * cm, 2.5 * cm, 3 * cm])
        style_cmds = [
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
            ("ALIGN", (1, 0), (4, -1), "RIGHT"),
            ("ALIGN", (5, 0), (5, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ]
        # Tint stock-out rows
        for i, r in enumerate(rows, start=1):
            if r.stock_out_occurred:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), COLOR_STOCKOUT_BG))
                style_cmds.append(("TEXTCOLOR", (5, i), (5, i), COLOR_STOCKOUT))
                style_cmds.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
                style_cmds.append(("FONTSIZE", (5, i), (5, i), 7))

        t.setStyle(TableStyle(style_cmds))
        out.append(t)
        out.append(Spacer(1, 10))

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
    story.extend(_narrative_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_revenue_section(data, styles, labels))
    story.append(PageBreak())
    story.extend(_stock_section(data, styles, labels))
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
