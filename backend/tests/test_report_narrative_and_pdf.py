"""Pure-function tests for the Reports feature extension's narrative
templates (narrative/templates_*.py) and PDF renderer (pdf.py).

Both are pure: ReportData in, string/bytes out — no DB, no network. This
is the project's first coverage for the narrative engine and PDF
renderer at all; the reports module's existing test file
(test_reports_flow.py) covers only the HTTP/auth layer.

Every assertion here also doubles as regression coverage for graceful
degradation: a None section (older report, predates this feature) or an
available=False section (data not populated for this event) must never
raise and must never silently vanish from the "next steps" bullet list
or PDF page — see each test's docstring.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.modules.reports.narrative.engine import render_narrative
from app.modules.reports.pdf import render_report_pdf
from app.modules.reports.schemas import (
    ReportComparison,
    ReportComparisonMetric,
    ReportData,
    ReportEventInfo,
    ReportForecastAccuracy,
    ReportForecastHourRow,
    ReportGuestKpis,
    ReportNarrative,
    ReportProductPerformance,
    ReportProductRow,
    ReportRevenueDecomposition,
    ReportRevenueKpis,
)


def _base_report_data(**overrides) -> ReportData:
    defaults = dict(
        report_id=uuid4(), version=1, language="it", generated_at=datetime.now(timezone.utc),
        event=ReportEventInfo(
            event_id=uuid4(), event_name="Sundance 19Jul", venue_name="Test Venue",
            started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
            duration_hours=8.0, bars_count=5, expected_guest_count=1600,
        ),
        revenue_kpis=ReportRevenueKpis(
            total_revenue=Decimal("24350.00"), revenue_per_hour=Decimal("3000"),
            revenue_per_bar_avg=Decimal("4870"),
        ),
        narrative=ReportNarrative(what_happened="", what_worked="", what_next=[]),
        guests=None,
        forecast_accuracy=None,
        comparison=None,
        revenue_decomposition=None,
        product_performance=None,
    )
    defaults.update(overrides)
    return ReportData(**defaults)


def _guests(**overrides) -> ReportGuestKpis:
    defaults = dict(
        available=True, identified_total=980, registered_count=600, guest_count=300,
        unknown_count=80, whale_count=50, regular_count=800, light_count=130,
        returning_count=350, new_count=630,
    )
    defaults.update(overrides)
    return ReportGuestKpis(**defaults)


def _forecast(**overrides) -> ReportForecastAccuracy:
    defaults = dict(
        available=True, predicted_final_total=900.0, actual_final_total=950.0,
        hours=[ReportForecastHourRow(hour_of_event=1, predicted=100, actual=110, lower=80, upper=120, within_band=True)],
        band_hits=7, band_hours_total=9,
    )
    defaults.update(overrides)
    return ReportForecastAccuracy(**defaults)


def _comparison(**overrides) -> ReportComparison:
    defaults = dict(
        available=True, previous_event_name="Sundance 5Jul", season_avg_n_events=3,
        metrics=[ReportComparisonMetric(
            label="Total Revenue", current_value=24350.0, previous_event_value=20000.0,
            previous_event_delta_pct=21.75,
        )],
        guest_metrics_available_from="August 2026",
    )
    defaults.update(overrides)
    return ReportComparison(**defaults)


def _decomposition(**overrides) -> ReportRevenueDecomposition:
    defaults = dict(
        available=True, estimated_attendance=1600, purchasers=980, purchase_rate_pct=61.25,
        orders_per_purchaser=2.1, average_order_value_cents=1250,
        implied_revenue_cents=2400000, actual_revenue_cents=2435000,
    )
    defaults.update(overrides)
    return ReportRevenueDecomposition(**defaults)


def _products(**overrides) -> ReportProductPerformance:
    defaults = dict(
        top_products=[ReportProductRow(
            product_id=uuid4(), product_name="Spritz", category="cocktail",
            units_sold=500, revenue_cents=250000,
        )],
        lowest_selling_products=[ReportProductRow(
            product_id=uuid4(), product_name="Rare Wine", category="wine",
            units_sold=3, revenue_cents=4500,
        )],
    )
    defaults.update(overrides)
    return ReportProductPerformance(**defaults)


# ─── Narrative: graceful degradation on older-shaped reports ─────────────────

def test_narrative_renders_fallback_prose_when_all_new_sections_absent():
    """An older report (predates this feature) has guests/forecast_accuracy/
    comparison/revenue_decomposition/product_performance all None — the
    engine must render the same as before this feature shipped, never
    raise, never leave a section blank."""
    data = _base_report_data()
    for lang in ("it", "en"):
        narrative = render_narrative(data, lang)
        assert narrative.what_happened
        assert narrative.what_worked
        assert narrative.what_next


# ─── Narrative: new templates actually fire with plan-approved wording ───────

def test_guest_floor_template_uses_floor_language_not_headcount_language():
    data = _base_report_data(guests=_guests())
    narrative = render_narrative(data, "it")
    assert "almeno 980 ospiti" in narrative.what_happened
    assert "non il conteggio totale" in narrative.what_happened


def test_estimated_purchase_rate_puts_uncertainty_inside_the_sentence():
    """CAVEAT 2: must read 'of an estimated N attendees', never state the
    purchase rate as a measured fact."""
    data = _base_report_data(revenue_decomposition=_decomposition())
    narrative_en = render_narrative(data, "en")
    assert "Of an estimated 1600 attendees" in narrative_en.what_happened
    assert "not a measurement" in narrative_en.what_happened


def test_forecast_band_hit_rate_is_stated_as_a_ratio_not_an_error_pct():
    data = _base_report_data(forecast_accuracy=_forecast(band_hits=7, band_hours_total=9))
    narrative = render_narrative(data, "en")
    assert "7 of 9 monitored hours" in narrative.what_happened


def test_lowest_selling_product_is_framed_as_a_question_not_a_verdict():
    data = _base_report_data(product_performance=_products())
    narrative = render_narrative(data, "en")
    bullets = " ".join(narrative.what_next)
    assert "Rare Wine sold only 3 units" in bullets
    assert "worth asking" in bullets
    # Never a verdict word.
    assert "underperform" not in bullets.lower()
    assert "bottom" not in bullets.lower()


def test_revenue_vs_previous_event_direction_word_matches_language():
    data = _base_report_data(comparison=_comparison())
    it = render_narrative(data, "it")
    en = render_narrative(data, "en")
    assert "aumentato" in it.what_happened
    assert "increased" in en.what_happened
    assert "aumentato" not in en.what_happened  # the EN cross-language bug this test guards against


def test_forecast_poorly_calibrated_bullet_fires_when_band_hits_below_half():
    data = _base_report_data(forecast_accuracy=_forecast(band_hits=2, band_hours_total=9))
    narrative = render_narrative(data, "en")
    assert any("missed the predicted range" in b for b in narrative.what_next)


def test_forecast_fully_calibrated_praise_fires_only_when_all_hours_hit():
    all_hit = _base_report_data(forecast_accuracy=_forecast(band_hits=9, band_hours_total=9))
    narrative = render_narrative(all_hit, "en")
    assert "stayed within the predicted range all night" in narrative.what_worked

    partial = _base_report_data(forecast_accuracy=_forecast(band_hits=7, band_hours_total=9))
    narrative_partial = render_narrative(partial, "en")
    assert "stayed within the predicted range all night" not in narrative_partial.what_worked


# ─── PDF: renders for both fully-populated and fully-degraded reports ────────

def test_pdf_renders_with_all_new_sections_populated():
    data = _base_report_data(
        guests=_guests(), forecast_accuracy=_forecast(), comparison=_comparison(),
        revenue_decomposition=_decomposition(), product_performance=_products(),
        narrative=ReportNarrative(what_happened="x", what_worked="y", what_next=["z"]),
    )
    pdf_bytes = render_report_pdf(data)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_pdf_renders_when_all_new_sections_are_none():
    """The exact shape of a report generated before this feature shipped —
    must render without raising (graceful degradation, not a crash)."""
    data = _base_report_data(
        narrative=ReportNarrative(what_happened="x", what_worked="y", what_next=["z"]),
    )
    pdf_bytes = render_report_pdf(data)
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_renders_when_new_sections_present_but_unavailable():
    """A newer report where the feature ran but found nothing (e.g.
    customer-feature population hasn't finished yet) — available=False,
    not None. Also must never raise."""
    data = _base_report_data(
        guests=_guests(available=False, unavailable_reason="not populated yet"),
        forecast_accuracy=_forecast(available=False, unavailable_reason="no model trained", hours=[]),
        comparison=_comparison(available=False, metrics=[]),
        revenue_decomposition=_decomposition(available=False),
        product_performance=ReportProductPerformance(),
        narrative=ReportNarrative(what_happened="x", what_worked="y", what_next=["z"]),
    )
    pdf_bytes = render_report_pdf(data)
    assert pdf_bytes.startswith(b"%PDF")
