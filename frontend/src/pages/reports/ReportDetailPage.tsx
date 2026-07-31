/**
 * ReportDetailPage — full post-event report view at /reports/:reportId.
 *
 * Renders a ReportResponse from GET /reports/{id}. Page order approved
 * 2026-07-31 (extends spec §3):
 *   0. Cover block            — event identity + hero revenue + guests (planning figure)
 *   1. Comparison             — this event vs. previous event / season average
 *   2. Executive Narrative    — Italian/English prose (What Happened/Worked/Next)
 *   3. Guests                 — identified-guest detail (a FLOOR, not a headcount)
 *   4. Revenue Breakdown      — per-bar bar chart + KPI row + decomposition + top/lowest products
 *   5. Forecast vs. Actual    — demand-model band-hit-rate detail
 *   6. Stock Reality Check    — table per bar, stock-out highlighted
 *   7. Alerts Timeline        — chronological with severity pills
 *
 * Sections 1, 3, 4's decomposition/products, and 5 all degrade gracefully:
 * a null field (older report, predates this feature) or available=false
 * (data not populated for this event) renders as a plain "not available"
 * line, never omitted silently and never a crash.
 *
 * Top toolbar:
 *   - Language toggle IT ↔ EN (triggers refetch via language param)
 *   - Download PDF button (backend renders pdf_bytes synchronously at
 *     generation time — see downloadReportPdf's docstring)
 *   - Regenerate button (creates v+1, admin only)
 *
 * Spec: docs/report-module-spec.md §3 + §8.2.
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { BarChart } from '@/shared/charts/BarChart'
import { Button } from '@/shared/ui/Button'
import { Card } from '@/shared/ui/Card'
import {
  downloadReportPdf,
  useRegenerateReport,
  useReport,
  type ReportAlertRow,
  type ReportBarRevenue,
  type ReportComparisonMetric,
  type ReportData,
  type ReportLanguage,
  type ReportProductRow,
  type ReportStockRow,
} from '@/features/reports/useReports'

// ─── Formatting helpers ──────────────────────────────────────────────────────

function fmtEur(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return `€${n.toLocaleString('it-IT', { maximumFractionDigits: 0 })}`
}

function fmtDateTime(iso: string | null | undefined, locale = 'it-IT'): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtNumber(value: string | number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return n.toFixed(decimals)
}

function fmtPct(value: number | null | undefined, signed = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = signed && value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

function fmtCents(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return fmtEur(value / 100)
}

// ─── Section 0: Cover block ──────────────────────────────────────────────────

function CoverBlock({ data }: { data: ReportData }) {
  return (
    <div className="bg-gradient-to-br from-[#1E5A8D] to-[#0F3254] text-white rounded-xl p-8 mb-8">
      <p className="text-[11px] uppercase tracking-widest opacity-70 mb-2">
        {data.language === 'it' ? 'Report Post-Evento' : 'Post-Event Report'}
      </p>
      <h1 className="text-3xl font-bold mb-1">{data.event.event_name}</h1>
      <p className="text-sm opacity-80">
        {data.event.venue_name} ·{' '}
        {fmtDateTime(data.event.started_at, data.language === 'it' ? 'it-IT' : 'en-GB')}
      </p>

      <div className="flex items-end gap-8 mt-8 flex-wrap">
        <div>
          <p className="text-[11px] uppercase tracking-widest opacity-70 mb-1">
            {data.language === 'it' ? 'Fatturato Totale' : 'Total Revenue'}
          </p>
          <p className="text-4xl font-bold">
            {fmtEur(data.revenue_kpis.total_revenue)}
          </p>
        </div>

        <div className="flex gap-6 text-sm opacity-90">
          <div>
            <p className="text-[11px] uppercase tracking-widest opacity-70">
              {data.language === 'it' ? 'Bar' : 'Bars'}
            </p>
            <p className="text-xl font-semibold">{data.event.bars_count}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-widest opacity-70">
              {data.language === 'it' ? 'Durata' : 'Duration'}
            </p>
            <p className="text-xl font-semibold">
              {fmtNumber(data.event.duration_hours)}h
            </p>
          </div>
          {data.event.guests_served !== null ? (
            <div>
              <p className="text-[11px] uppercase tracking-widest opacity-70">
                {data.language === 'it' ? 'Ospiti' : 'Guests'}
              </p>
              <p className="text-xl font-semibold">{data.event.guests_served}</p>
            </div>
          ) : (
            data.event.expected_guest_count !== null && (
              // No measured headcount (guests_served is a v1.2/ticketing
              // field) — show the planning estimate instead, but the
              // label itself carries the caveat: never presented as a
              // measured fact anywhere it appears (CAVEAT 2).
              <div>
                <p className="text-[11px] uppercase tracking-widest opacity-70">
                  {data.language === 'it'
                    ? 'Affluenza stimata (dato di pianificazione)'
                    : 'Estimated attendance (planning figure)'}
                </p>
                <p className="text-xl font-semibold">{data.event.expected_guest_count}</p>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Section: Event-over-Event Comparison ────────────────────────────────────

function ComparisonSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Confronto con gli Eventi Precedenti',
          empty: 'Nessun evento precedente disponibile per il confronto.',
          metric: 'Metrica',
          vsPrev: 'vs. Evento Precedente',
          vsSeason: 'vs. Media Stagione',
          guestNote: (date: string) => `Il confronto sugli ospiti è disponibile a partire da ${date}.`,
        }
      : {
          heading: 'Comparison with Previous Events',
          empty: 'No previous event available for comparison.',
          metric: 'Metric',
          vsPrev: 'vs. Previous Event',
          vsSeason: 'vs. Season Average',
          guestNote: (date: string) => `Guest comparison is available from ${date} onward.`,
        }

  const comparison = data.comparison
  if (!comparison || !comparison.available || comparison.metrics.length === 0) {
    return (
      <Card className="mb-8">
        <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
          {labels.heading}
        </h2>
        <p className="text-sm text-[#A0AEC0] italic py-4">{labels.empty}</p>
      </Card>
    )
  }

  const hasGuestMetrics = comparison.metrics.some((m) => m.label === 'Identified Guests')

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#E2E8F0]">
              <th className="text-left py-2 pr-3">{labels.metric}</th>
              <th className="text-right py-2 px-3">{labels.vsPrev}</th>
              <th className="text-right py-2 pl-3">{labels.vsSeason}</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metrics.map((m: ReportComparisonMetric) => (
              <tr key={m.label} className="border-b border-[#F1F5F9]">
                <td className="py-2 pr-3 text-[#1A202C]">{m.label}</td>
                <td
                  className={`py-2 px-3 text-right font-semibold ${
                    (m.previous_event_delta_pct ?? 0) < 0 ? 'text-[#742A2A]' : 'text-[#22543D]'
                  }`}
                >
                  {fmtPct(m.previous_event_delta_pct, true)}
                </td>
                <td
                  className={`py-2 pl-3 text-right font-semibold ${
                    (m.season_avg_delta_pct ?? 0) < 0 ? 'text-[#742A2A]' : 'text-[#22543D]'
                  }`}
                >
                  {fmtPct(m.season_avg_delta_pct, true)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {comparison.previous_event_name && (
        <p className="text-xs text-[#718096] mt-3">
          {labels.vsPrev}: {comparison.previous_event_name}
        </p>
      )}
      {/* NOT backfilled onto older reports — say so plainly rather than
          silently omit rows (plan approval, Section C). */}
      {comparison.guest_metrics_available_from && !hasGuestMetrics && (
        <p className="text-xs text-[#A0AEC0] italic mt-1">
          {labels.guestNote(comparison.guest_metrics_available_from)}
        </p>
      )}
    </Card>
  )
}

// ─── Section: Guests ──────────────────────────────────────────────────────────

function GuestsSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Ospiti',
          empty: 'Dati sugli ospiti non ancora disponibili per questo evento.',
          identifiedTotal: 'Ospiti Identificati',
          floorNote:
            'Totale identificato tramite acquisti registrati — un valore minimo, non il conteggio totale dei partecipanti.',
          registered: 'Registrati',
          guest: 'Ospiti',
          unknown: 'Sconosciuti',
          whale: 'Whale',
          regular: 'Regolari',
          light: 'Leggeri',
          returning: 'Di Ritorno',
          newGuests: 'Nuovi',
        }
      : {
          heading: 'Guests',
          empty: 'Guest data not yet available for this event.',
          identifiedTotal: 'Identified Guests',
          floorNote:
            'Total identified through recorded purchases — a floor, not a total attendance count.',
          registered: 'Registered',
          guest: 'Guests',
          unknown: 'Unknown',
          whale: 'Whale',
          regular: 'Regular',
          light: 'Light',
          returning: 'Returning',
          newGuests: 'New',
        }

  const guests = data.guests
  if (!guests || !guests.available) {
    return (
      <Card className="mb-8">
        <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
          {labels.heading}
        </h2>
        <p className="text-sm text-[#A0AEC0] italic py-4">{labels.empty}</p>
      </Card>
    )
  }

  const tiles = [
    [labels.registered, guests.registered_count],
    [labels.guest, guests.guest_count],
    [labels.unknown, guests.unknown_count],
    [labels.whale, guests.whale_count],
    [labels.regular, guests.regular_count],
    [labels.light, guests.light_count],
    [labels.returning, guests.returning_count],
    [labels.newGuests, guests.new_count],
  ] as const

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>
      <p className="text-3xl font-bold text-[#1A202C]">{guests.identified_total}</p>
      <p className="text-xs text-[#A0AEC0] italic mb-4">{labels.floorNote}</p>
      <div className="grid grid-cols-4 gap-4">
        {tiles.map(([label, value]) => (
          <div key={label}>
            <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
              {label}
            </p>
            <p className="text-lg font-bold text-[#1A202C]">{value}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ─── Section: Forecast vs. Actual ─────────────────────────────────────────────

function ForecastSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Previsione vs. Consuntivo',
          empty: 'Nessun modello di previsione disponibile per questo evento.',
          bandHitRate: (hits: number, total: number) =>
            `La domanda reale è rientrata nella fascia prevista in ${hits} delle ${total} ore monitorate.`,
          hour: 'Ora',
          predicted: 'Previsto',
          actual: 'Consuntivo',
          band: 'Fascia',
          inBand: 'Sì',
          outOfBand: 'No',
        }
      : {
          heading: 'Forecast vs. Actual',
          empty: 'No demand forecast model available for this event.',
          bandHitRate: (hits: number, total: number) =>
            `Actual demand fell within the predicted range in ${hits} of ${total} monitored hours.`,
          hour: 'Hour',
          predicted: 'Predicted',
          actual: 'Actual',
          band: 'Band',
          inBand: 'Yes',
          outOfBand: 'No',
        }

  const forecast = data.forecast_accuracy
  if (!forecast || !forecast.available) {
    return (
      <Card className="mb-8">
        <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
          {labels.heading}
        </h2>
        <p className="text-sm text-[#A0AEC0] italic py-4">{labels.empty}</p>
      </Card>
    )
  }

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>
      {/* The single honest forecast-quality statement — deliberately not
          an error percentage (plan approval, Section B). */}
      {forecast.band_hours_total !== null && forecast.band_hits !== null && (
        <p className="text-base font-semibold text-[#1A202C] mb-4">
          {labels.bandHitRate(forecast.band_hits, forecast.band_hours_total)}
        </p>
      )}
      {forecast.hours.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#E2E8F0]">
                <th className="text-left py-2 pr-3">{labels.hour}</th>
                <th className="text-right py-2 px-3">{labels.predicted}</th>
                <th className="text-right py-2 px-3">{labels.actual}</th>
                <th className="text-right py-2 pl-3">{labels.band}</th>
              </tr>
            </thead>
            <tbody>
              {forecast.hours.map((h) => (
                <tr key={h.hour_of_event} className="border-b border-[#F1F5F9]">
                  <td className="py-2 pr-3 text-[#1A202C]">{fmtNumber(h.hour_of_event, 0)}</td>
                  <td className="py-2 px-3 text-right text-[#4A5568]">{fmtNumber(h.predicted, 0)}</td>
                  <td className="py-2 px-3 text-right text-[#4A5568]">{fmtNumber(h.actual, 0)}</td>
                  <td
                    className={`py-2 pl-3 text-right font-semibold ${
                      h.within_band ? 'text-[#22543D]' : 'text-[#742A2A]'
                    }`}
                  >
                    {h.within_band ? labels.inBand : labels.outOfBand}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

// ─── Section 1: Narrative ────────────────────────────────────────────────────

function NarrativeSection({ data }: { data: ReportData }) {
  const labels =
    data.language === 'it'
      ? {
          heading: 'Sintesi Esecutiva',
          happened: 'Cosa è successo',
          worked: 'Cosa ha funzionato',
          next: 'Cosa fare al prossimo',
        }
      : {
          heading: 'Executive Summary',
          happened: 'What Happened',
          worked: 'What Worked',
          next: 'What To Do Next',
        }

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>

      <div className="space-y-5">
        <div>
          <h3 className="text-base font-semibold text-[#1A202C] mb-2">{labels.happened}</h3>
          <p className="text-[15px] leading-relaxed text-[#2D3748]">
            {data.narrative.what_happened}
          </p>
        </div>

        <div>
          <h3 className="text-base font-semibold text-[#1A202C] mb-2">{labels.worked}</h3>
          <p className="text-[15px] leading-relaxed text-[#2D3748]">
            {data.narrative.what_worked}
          </p>
        </div>

        <div>
          <h3 className="text-base font-semibold text-[#1A202C] mb-2">{labels.next}</h3>
          <ul className="space-y-2">
            {data.narrative.what_next.map((bullet, i) => (
              <li key={i} className="text-[15px] leading-relaxed text-[#2D3748] flex gap-2">
                <span className="text-[#1E5A8D] font-bold mt-0.5">→</span>
                <span>{bullet}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  )
}

// ─── Section 2: Revenue breakdown ────────────────────────────────────────────

function RevenueSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? { heading: 'Fatturato per Bar', perHour: 'per ora', avgBar: 'media bar', top: 'Prodotto top' }
      : { heading: 'Revenue by Bar', perHour: 'per hour', avgBar: 'bar average', top: 'Top product' }

  const chartData = data.bar_revenues.map((b: ReportBarRevenue) => ({
    label: b.bar_name,
    value: Number(b.revenue),
  }))

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>

      {chartData.length > 0 ? (
        <BarChart data={chartData} height={220} />
      ) : (
        <p className="text-sm text-[#A0AEC0] italic py-4">
          {lang === 'it' ? 'Nessun dato di fatturato registrato.' : 'No revenue data recorded.'}
        </p>
      )}

      <div className="grid grid-cols-3 gap-4 mt-6 pt-5 border-t border-[#E2E8F0]">
        <div>
          <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
            {labels.perHour}
          </p>
          <p className="text-lg font-bold text-[#1A202C]">
            {fmtEur(data.revenue_kpis.revenue_per_hour)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
            {labels.avgBar}
          </p>
          <p className="text-lg font-bold text-[#1A202C]">
            {fmtEur(data.revenue_kpis.revenue_per_bar_avg)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
            {labels.top}
          </p>
          <p className="text-lg font-bold text-[#1A202C] truncate">
            {data.revenue_kpis.top_product_name ?? '—'}
            {data.revenue_kpis.top_product_units !== null && (
              <span className="text-xs text-[#718096] ml-1 font-normal">
                ({data.revenue_kpis.top_product_units})
              </span>
            )}
          </p>
        </div>
      </div>

      <RevenueDecomposition data={data} />
      <ProductPerformance data={data} />
    </Card>
  )
}

// ─── Section 4d: Revenue Decomposition (Section D) ────────────────────────────

function RevenueDecomposition({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Scomposizione del Fatturato',
          empty: 'Dati insufficienti per la scomposizione del fatturato.',
          note: "Tasso di acquisto stimato — calcolato su un'affluenza pianificata, non misurata.",
          attendance: 'Affluenza stimata (dato di pianificazione)',
          purchasers: 'Acquirenti',
          rate: 'Tasso di Acquisto (stimato)',
          perPurchaser: 'Ordini per Acquirente',
          aov: 'Scontrino Medio',
        }
      : {
          heading: 'Revenue Decomposition',
          empty: 'Insufficient data for revenue decomposition.',
          note: 'Estimated purchase rate — computed against a planned, not measured, attendance figure.',
          attendance: 'Estimated attendance (planning figure)',
          purchasers: 'Purchasers',
          rate: 'Purchase Rate (estimated)',
          perPurchaser: 'Orders per Purchaser',
          aov: 'Average Order Value',
        }

  const rd = data.revenue_decomposition
  return (
    <div className="mt-6 pt-5 border-t border-[#E2E8F0]">
      <h3 className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
        {labels.heading}
      </h3>
      {!rd || !rd.available ? (
        <p className="text-sm text-[#A0AEC0] italic">{labels.empty}</p>
      ) : (
        <>
          <div className="grid grid-cols-5 gap-4">
            <div>
              <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-widest">
                {labels.attendance}
              </p>
              <p className="text-lg font-bold text-[#1A202C]">{rd.estimated_attendance ?? '—'}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-widest">
                {labels.purchasers}
              </p>
              <p className="text-lg font-bold text-[#1A202C]">{rd.purchasers ?? '—'}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-widest">
                {labels.rate}
              </p>
              <p className="text-lg font-bold text-[#1A202C]">{fmtPct(rd.purchase_rate_pct)}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-widest">
                {labels.perPurchaser}
              </p>
              <p className="text-lg font-bold text-[#1A202C]">
                {fmtNumber(rd.orders_per_purchaser, 1)}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-widest">
                {labels.aov}
              </p>
              <p className="text-lg font-bold text-[#1A202C]">
                {fmtCents(rd.average_order_value_cents)}
              </p>
            </div>
          </div>
          {/* CAVEAT 2 footnote — mandatory on every surface this number
              appears, never left implicit. */}
          <p className="text-xs text-[#A0AEC0] italic mt-3">{labels.note}</p>
        </>
      )}
    </div>
  )
}

// ─── Section 4e: Top / Lowest-Selling Products (Section E) ───────────────────

function ProductPerformance({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          top: 'Prodotti Più Venduti',
          lowest: 'Prodotti Meno Venduti',
          lowestNote:
            'Vendite basse possono indicare un prodotto nuovo, un prezzo elevato o una postazione poco frequentata — non necessariamente un problema.',
          product: 'Prodotto',
          units: 'Unità',
          revenue: 'Fatturato',
        }
      : {
          top: 'Top-Selling Products',
          lowest: 'Lowest-Selling Products',
          lowestNote:
            'Low sales may reflect a new item, a high price, or a quiet bar placement — not necessarily a problem.',
          product: 'Product',
          units: 'Units',
          revenue: 'Revenue',
        }

  const pp = data.product_performance
  if (!pp || (pp.top_products.length === 0 && pp.lowest_selling_products.length === 0)) {
    return null
  }

  const productTable = (rows: ReportProductRow[]) => (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#E2E8F0]">
          <th className="text-left py-2 pr-3">{labels.product}</th>
          <th className="text-right py-2 px-3">{labels.units}</th>
          <th className="text-right py-2 pl-3">{labels.revenue}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.product_id} className="border-b border-[#F1F5F9]">
            <td className="py-2 pr-3 text-[#1A202C]">{r.product_name}</td>
            <td className="py-2 px-3 text-right text-[#4A5568]">{r.units_sold}</td>
            <td className="py-2 pl-3 text-right text-[#4A5568]">{fmtCents(r.revenue_cents)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <div className="mt-6 pt-5 border-t border-[#E2E8F0] grid grid-cols-1 md:grid-cols-2 gap-6">
      {pp.top_products.length > 0 && (
        <div>
          <h3 className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
            {labels.top}
          </h3>
          {productTable(pp.top_products)}
        </div>
      )}
      {pp.lowest_selling_products.length > 0 && (
        <div>
          <h3 className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
            {labels.lowest}
          </h3>
          {productTable(pp.lowest_selling_products)}
          {/* A question, not a verdict (plan approval, Section E). */}
          <p className="text-xs text-[#A0AEC0] italic mt-2">{labels.lowestNote}</p>
        </div>
      )}
    </div>
  )
}

// ─── Section 3: Stock Reality Check ──────────────────────────────────────────

function StockSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Stato delle Scorte',
          product: 'Prodotto',
          opening: 'Iniziali',
          closing: 'Finali',
          consumed: 'Consumati',
          burn: 'Consumo/ora',
          stockout: 'ESAURITO',
          empty: 'Nessun dato di scorta disponibile.',
        }
      : {
          heading: 'Stock Reality Check',
          product: 'Product',
          opening: 'Opening',
          closing: 'Closing',
          consumed: 'Consumed',
          burn: 'Burn/h',
          stockout: 'STOCK-OUT',
          empty: 'No stock data available.',
        }

  // Group stock rows by bar
  const grouped: Record<string, ReportStockRow[]> = {}
  for (const row of data.stock_rows) {
    if (!grouped[row.bar_name]) grouped[row.bar_name] = []
    grouped[row.bar_name].push(row)
  }

  if (data.stock_rows.length === 0) {
    return (
      <Card className="mb-8">
        <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
          {labels.heading}
        </h2>
        <p className="text-sm text-[#A0AEC0] italic py-4">{labels.empty}</p>
      </Card>
    )
  }

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>

      <div className="space-y-5">
        {Object.entries(grouped).map(([barName, rows]) => (
          <div key={barName}>
            <h3 className="text-sm font-semibold text-[#1A202C] mb-2">{barName}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#E2E8F0]">
                    <th className="text-left py-2 pr-3">{labels.product}</th>
                    <th className="text-right py-2 px-3">{labels.opening}</th>
                    <th className="text-right py-2 px-3">{labels.closing}</th>
                    <th className="text-right py-2 px-3">{labels.consumed}</th>
                    <th className="text-right py-2 px-3">{labels.burn}</th>
                    <th className="text-right py-2 pl-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={`${r.bar_id}-${r.product_id}`}
                      className={`border-b border-[#F1F5F9] ${r.stock_out_occurred ? 'bg-[#FFF5F5]' : ''}`}
                    >
                      <td className="py-2 pr-3 text-[#1A202C]">{r.product_name}</td>
                      <td className="py-2 px-3 text-right text-[#4A5568]">
                        {fmtNumber(r.opening_qty, 0)}
                      </td>
                      <td className="py-2 px-3 text-right text-[#4A5568]">
                        {fmtNumber(r.closing_qty, 0)}
                      </td>
                      <td className="py-2 px-3 text-right text-[#4A5568]">
                        {fmtNumber(r.consumed_qty, 0)}
                      </td>
                      <td className="py-2 px-3 text-right text-[#4A5568]">
                        {fmtNumber(r.burn_rate_per_hour, 1)}
                      </td>
                      <td className="py-2 pl-3 text-right">
                        {r.stock_out_occurred && (
                          <span className="inline-block px-2 py-0.5 bg-[#FED7D7] text-[#742A2A] text-[10px] font-semibold rounded-full">
                            {labels.stockout}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ─── Section 4: Alerts timeline ──────────────────────────────────────────────

const SEVERITY_CONFIG = {
  info:     { bg: '#BEE3F8', text: '#2C5282', label: 'INFO' },
  warning:  { bg: '#FEEBC8', text: '#744210', label: 'WARNING' },
  critical: { bg: '#FED7D7', text: '#742A2A', label: 'CRITICAL' },
  anomaly:  { bg: '#E9D8FD', text: '#44337A', label: 'ANOMALY' },
}

function AlertsSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? { heading: 'Cronologia Alert', empty: 'Nessun alert registrato — la serata è filata liscia.', unack: 'Non confermato' }
      : { heading: 'Alerts Timeline', empty: 'No alerts recorded — the night ran smoothly.', unack: 'Unacknowledged' }

  if (data.alerts.length === 0) {
    return (
      <Card className="mb-8">
        <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
          {labels.heading}
        </h2>
        <p className="text-sm text-[#38A169] py-4 flex items-center gap-2">
          <span className="text-lg">✓</span> {labels.empty}
        </p>
      </Card>
    )
  }

  return (
    <Card className="mb-8">
      <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-4">
        {labels.heading}
      </h2>

      <div className="space-y-3">
        {data.alerts.map((a: ReportAlertRow) => {
          const cfg = SEVERITY_CONFIG[a.severity]
          return (
            <div key={a.alert_id} className="flex gap-3 border-b border-[#F1F5F9] pb-3 last:border-0">
              <div className="text-xs font-mono text-[#A0AEC0] pt-0.5 w-12 shrink-0">
                {fmtTime(a.fired_at)}
              </div>
              <div
                className="px-2 py-0.5 text-[10px] font-bold rounded h-fit shrink-0"
                style={{ backgroundColor: cfg.bg, color: cfg.text }}
              >
                {cfg.label}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-[#1A202C]">
                  {a.title}
                  {a.bar_name && <span className="text-[#718096] font-normal"> · {a.bar_name}</span>}
                </p>
                <p className="text-xs text-[#4A5568] mt-0.5">{a.owner_message}</p>
                <p className="text-[11px] text-[#A0AEC0] mt-1">
                  {a.acknowledged_at
                    ? `✓ ${fmtTime(a.acknowledged_at)}${a.acknowledged_by_name ? ` · ${a.acknowledged_by_name}` : ''}`
                    : labels.unack}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const [language, setLanguage] = useState<ReportLanguage | null>(null)

  const { data: report, isLoading, isError } = useReport(reportId ?? null, language ?? undefined)
  const regenerate = useRegenerateReport(reportId ?? '')

  // If a language toggle was set, show that one; otherwise the backend's.
  const activeLang: ReportLanguage = language ?? report?.language ?? 'it'

  const handleDownloadPdf = async () => {
    if (!reportId) return
    try {
      const blob = await downloadReportPdf(reportId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${reportId}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // The backend renders pdf_bytes synchronously at generation time — a
      // 'ready' report always has one. A failure here is a genuine error
      // (network, report not found), not a missing feature — see
      // downloadReportPdf's docstring.
      alert(
        activeLang === 'it'
          ? 'Impossibile scaricare il PDF. Riprova.'
          : 'Failed to download PDF. Please try again.',
      )
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <Link
        to="/reports"
        className="inline-flex items-center gap-1 text-sm text-[#4A5568] hover:text-[#1A202C] mb-4"
      >
        ← {activeLang === 'it' ? 'Torna ai report' : 'Back to reports'}
      </Link>

      {/* Loading */}
      {isLoading && (
        <div className="text-center py-12 text-sm text-[#A0AEC0]">
          {activeLang === 'it' ? 'Caricamento…' : 'Loading…'}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="bg-[#FED7D7] text-[#742A2A] text-sm rounded-xl p-4">
          {activeLang === 'it'
            ? 'Report non trovato. Potrebbe essere stato eliminato, o l\'ID non è valido.'
            : 'Report not found. It may have been deleted, or the ID is invalid.'}
        </div>
      )}

      {/* Not ready yet */}
      {report && report.status !== 'ready' && (
        <Card>
          <p className="text-sm text-[#4A5568]">
            {activeLang === 'it'
              ? `Il report è in stato: ${report.status}. Ricarica tra qualche secondo.`
              : `Report status: ${report.status}. Refresh in a moment.`}
          </p>
        </Card>
      )}

      {/* Ready — render the full report */}
      {report?.status === 'ready' && report.data && (
        <>
          {/* Toolbar */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <div className="flex rounded-lg border border-[#E2E8F0] overflow-hidden">
              {(['it', 'en'] as const).map((lang) => (
                <button
                  key={lang}
                  onClick={() => setLanguage(lang)}
                  className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeLang === lang
                      ? 'bg-[#1E5A8D] text-white'
                      : 'bg-white text-[#4A5568] hover:bg-[#F7FAFC]'
                  }`}
                >
                  {lang === 'it' ? '🇮🇹 IT' : '🇬🇧 EN'}
                </button>
              ))}
            </div>
            <div className="flex-1" />
            <Button variant="secondary" size="sm" onClick={handleDownloadPdf}>
              📄 {activeLang === 'it' ? 'Scarica PDF' : 'Download PDF'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => regenerate.mutate({})}
              disabled={regenerate.isPending}
            >
              🔄 {regenerate.isPending
                ? (activeLang === 'it' ? 'Rigenerando…' : 'Regenerating…')
                : (activeLang === 'it' ? 'Rigenera' : 'Regenerate')}
            </Button>
          </div>

          <CoverBlock data={report.data} />
          <ComparisonSection data={report.data} />
          <NarrativeSection data={report.data} />
          <GuestsSection data={report.data} />
          <RevenueSection data={report.data} />
          <ForecastSection data={report.data} />
          <StockSection data={report.data} />
          <AlertsSection data={report.data} />

          {/* Footer: version + generated_at */}
          <p className="text-[11px] text-[#A0AEC0] text-center mt-6">
            v{report.version} · {fmtDateTime(report.generated_at)}
            {report.superseded_by && (
              <span className="text-[#E53E3E] ml-2">
                · {activeLang === 'it' ? 'sostituito' : 'superseded'}
              </span>
            )}
          </p>
        </>
      )}
    </div>
  )
}
