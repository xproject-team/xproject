/**
 * ReportDetailPage — full post-event report view at /reports/:reportId.
 *
 * Day 14: converted to the Vera dark design system (Card, Badge, Button,
 * dark tables) and migrated content to the event_orders revenue basis:
 *   - unmapped-order revenue line under the KPI strip (part of the total,
 *     attributable to no bar — shown, never redistributed)
 *   - Comparison table gained the Current column (unit-aware formatting,
 *     matching the PDF) + the mixed-measurement footnote
 *
 * Renders a ReportResponse from GET /reports/{id}. Page order approved
 * 2026-07-31 (extends spec §3):
 *   0. Cover block            — event identity + hero revenue + guests (planning figure)
 *   1. Comparison             — this event vs. previous event / season average
 *   2. Executive Narrative    — Italian/English prose (What Happened/Worked/Next)
 *   3. Guests                 — identified-guest detail (a FLOOR, not a headcount)
 *   4. Revenue Breakdown      — per-bar bars + KPI row + decomposition + top/lowest products
 *   5. Forecast vs. Actual    — demand-model band-hit-rate detail
 *   6. Alerts Timeline        — chronological with severity badges
 *
 * (Stock Reality Check was removed from this view 2026-08-10 — it read a
 * table that stopped being written in June. The PDF dropped it Day 14 for
 * the same reason; `data.stock_rows` is still stored, rendered nowhere.)
 *
 * Sections 1, 3, 4's decomposition/products, and 5 all degrade gracefully:
 * a null field (older report, predates this feature) or available=false
 * renders as a plain "not available" line, never omitted silently and
 * never a crash.
 *
 * Spec: docs/report-module-spec.md §3 + §8.2.
 */
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge, Button, Card } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
import {
  downloadReportPdf,
  useRegenerateReport,
  useReport,
  type ReportAlertRow,
  type ReportComparisonMetric,
  type ReportData,
  type ReportLanguage,
  type ReportProductRow,
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

/** Comparison-table value by the metric's declared unit — mirrors the
 *  PDF's _fmt_metric_value so web and PDF can never disagree. null unit
 *  (pre-migration report) keeps the legacy one-decimal rendering. */
function fmtMetricValue(value: number | null, unit: 'eur' | 'count' | null): string {
  if (unit === 'eur') return fmtEur(value)
  if (unit === 'count') return fmtNumber(value, 0)
  return fmtNumber(value, 1)
}

function deltaColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'var(--v-text-dim)'
  return value < 0 ? 'var(--v-pink)' : 'var(--v-green)'
}

// ─── Shared table cell styles (dark table idiom, per PredictionPage) ─────────

const TH = 'text-[10px] font-bold uppercase tracking-[0.06em] py-2'
const thStyle = { color: 'var(--v-text-muted)' } as const
const rowBorder = { borderBottom: '0.5px solid var(--v-border)' } as const

function SectionCard({ children }: { children: React.ReactNode }) {
  return <Card className="mb-6">{children}</Card>
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="v-label block mb-4">{children}</h2>
}

// ─── Section 0: Cover block ──────────────────────────────────────────────────

function CoverBlock({ data }: { data: ReportData }) {
  const it = data.language === 'it'
  return (
    <Card className="relative overflow-hidden mb-6 !p-8">
      <span
        className="absolute top-0 left-0 bottom-0 w-[2px]"
        style={{ background: 'var(--v-cyan)' }}
      />
      <p className="v-label mb-2">{it ? 'Report Post-Evento' : 'Post-Event Report'}</p>
      <h1 className="text-3xl font-medium mb-1" style={{ color: 'var(--v-text)' }}>
        {data.event.event_name}
      </h1>
      <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>
        {data.event.venue_name} ·{' '}
        {fmtDateTime(data.event.started_at, it ? 'it-IT' : 'en-GB')}
      </p>

      <div className="flex items-end gap-8 mt-8 flex-wrap">
        <div>
          <p className="v-label mb-1">{it ? 'Fatturato Totale' : 'Total Revenue'}</p>
          <p className="text-4xl font-medium" style={{ color: 'var(--v-text)' }}>
            {fmtEur(data.revenue_kpis.total_revenue)}
          </p>
        </div>

        <div className="flex gap-6 text-sm">
          <div>
            <p className="v-label">{it ? 'Bar' : 'Bars'}</p>
            <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
              {data.event.bars_count}
            </p>
          </div>
          <div>
            <p className="v-label">{it ? 'Durata' : 'Duration'}</p>
            <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
              {fmtNumber(data.event.duration_hours)}h
            </p>
          </div>
          {data.event.guests_served !== null ? (
            <div>
              <p className="v-label">{it ? 'Ospiti' : 'Guests'}</p>
              <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
                {data.event.guests_served}
              </p>
            </div>
          ) : (
            data.event.expected_guest_count !== null && (
              // No measured headcount (guests_served is a v1.2/ticketing
              // field) — show the planning estimate instead, but the
              // label itself carries the caveat: never presented as a
              // measured fact anywhere it appears (CAVEAT 2).
              <div>
                <p className="v-label">
                  {it
                    ? 'Affluenza stimata (dato di pianificazione)'
                    : 'Estimated attendance (planning figure)'}
                </p>
                <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
                  {data.event.expected_guest_count}
                </p>
              </div>
            )
          )}
        </div>
      </div>
    </Card>
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
          current: 'Attuale',
          vsPrev: 'vs. Evento Precedente',
          vsSeason: 'vs. Media Stagione',
          guestNote: (date: string) => `Il confronto sugli ospiti è disponibile a partire da ${date}.`,
          mixedNote:
            'Il fatturato degli eventi precedenti è stato misurato con il metodo precedente (movimenti di magazzino) — piccole differenze sono di natura definitoria.',
        }
      : {
          heading: 'Comparison with Previous Events',
          empty: 'No previous event available for comparison.',
          metric: 'Metric',
          current: 'Current',
          vsPrev: 'vs. Previous Event',
          vsSeason: 'vs. Season Average',
          guestNote: (date: string) => `Guest comparison is available from ${date} onward.`,
          mixedNote:
            "Earlier events' revenue was measured with the previous method (stock movements) — small differences are definitional.",
        }

  const comparison = data.comparison
  if (!comparison || !comparison.available || comparison.metrics.length === 0) {
    return (
      <SectionCard>
        <SectionHeading>{labels.heading}</SectionHeading>
        <p className="text-sm italic py-4" style={{ color: 'var(--v-text-dim)' }}>
          {labels.empty}
        </p>
      </SectionCard>
    )
  }

  const hasGuestMetrics = comparison.metrics.some((m) => m.label === 'Identified Guests')

  return (
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={rowBorder}>
              <th className={`${TH} text-left pr-3`} style={thStyle}>{labels.metric}</th>
              <th className={`${TH} text-right px-3`} style={thStyle}>{labels.current}</th>
              <th className={`${TH} text-right px-3`} style={thStyle}>{labels.vsPrev}</th>
              <th className={`${TH} text-right pl-3`} style={thStyle}>{labels.vsSeason}</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metrics.map((m: ReportComparisonMetric) => (
              <tr key={m.label} style={rowBorder}>
                <td className="py-2 pr-3" style={{ color: 'var(--v-text)' }}>{m.label}</td>
                <td className="py-2 px-3 text-right" style={{ color: 'var(--v-text)' }}>
                  {fmtMetricValue(m.current_value, m.unit)}
                </td>
                <td
                  className="py-2 px-3 text-right font-medium"
                  style={{ color: deltaColor(m.previous_event_delta_pct) }}
                >
                  {fmtPct(m.previous_event_delta_pct, true)}
                </td>
                <td
                  className="py-2 pl-3 text-right font-medium"
                  style={{ color: deltaColor(m.season_avg_delta_pct) }}
                >
                  {fmtPct(m.season_avg_delta_pct, true)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {comparison.previous_event_name && (
        <p className="text-xs mt-3" style={{ color: 'var(--v-text-muted)' }}>
          {labels.vsPrev}: {comparison.previous_event_name}
        </p>
      )}
      {/* NOT backfilled onto older reports — say so plainly rather than
          silently omit rows (plan approval, Section C). */}
      {comparison.guest_metrics_available_from && !hasGuestMetrics && (
        <p className="text-xs italic mt-1" style={{ color: 'var(--v-text-dim)' }}>
          {labels.guestNote(comparison.guest_metrics_available_from)}
        </p>
      )}
      {/* Mixed measurement basis (Day 14 migration) — the delta carries a
          definitional component; say so under the table. */}
      {comparison.mixed_revenue_sources && (
        <p className="text-xs italic mt-1" style={{ color: 'var(--v-text-dim)' }}>
          {labels.mixedNote}
        </p>
      )}
    </SectionCard>
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
      <SectionCard>
        <SectionHeading>{labels.heading}</SectionHeading>
        <p className="text-sm italic py-4" style={{ color: 'var(--v-text-dim)' }}>
          {labels.empty}
        </p>
      </SectionCard>
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
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>
      <p className="text-3xl font-medium" style={{ color: 'var(--v-text)' }}>
        {guests.identified_total}
      </p>
      <p className="text-xs italic mb-4" style={{ color: 'var(--v-text-dim)' }}>
        {labels.floorNote}
      </p>
      <div className="grid grid-cols-4 gap-4">
        {tiles.map(([label, value]) => (
          <div key={label}>
            <p className="v-label">{label}</p>
            <p className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>
              {value}
            </p>
          </div>
        ))}
      </div>
    </SectionCard>
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
      <SectionCard>
        <SectionHeading>{labels.heading}</SectionHeading>
        <p className="text-sm italic py-4" style={{ color: 'var(--v-text-dim)' }}>
          {labels.empty}
        </p>
      </SectionCard>
    )
  }

  return (
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>
      {/* The single honest forecast-quality statement — deliberately not
          an error percentage (plan approval, Section B). */}
      {forecast.band_hours_total !== null && forecast.band_hits !== null && (
        <p className="text-base font-medium mb-4" style={{ color: 'var(--v-text)' }}>
          {labels.bandHitRate(forecast.band_hits, forecast.band_hours_total)}
        </p>
      )}
      {forecast.hours.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={rowBorder}>
                <th className={`${TH} text-left pr-3`} style={thStyle}>{labels.hour}</th>
                <th className={`${TH} text-right px-3`} style={thStyle}>{labels.predicted}</th>
                <th className={`${TH} text-right px-3`} style={thStyle}>{labels.actual}</th>
                <th className={`${TH} text-right pl-3`} style={thStyle}>{labels.band}</th>
              </tr>
            </thead>
            <tbody>
              {forecast.hours.map((h) => (
                <tr key={h.hour_of_event} style={rowBorder}>
                  <td className="py-2 pr-3" style={{ color: 'var(--v-text)' }}>
                    {fmtNumber(h.hour_of_event, 0)}
                  </td>
                  <td className="py-2 px-3 text-right" style={{ color: 'var(--v-text-muted)' }}>
                    {fmtNumber(h.predicted, 0)}
                  </td>
                  <td className="py-2 px-3 text-right" style={{ color: 'var(--v-text-muted)' }}>
                    {fmtNumber(h.actual, 0)}
                  </td>
                  <td
                    className="py-2 pl-3 text-right font-medium"
                    style={{ color: h.within_band ? 'var(--v-green)' : 'var(--v-pink)' }}
                  >
                    {h.within_band ? labels.inBand : labels.outOfBand}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
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
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>

      <div className="space-y-5">
        <div>
          <h3 className="text-base font-medium mb-2" style={{ color: 'var(--v-text)' }}>
            {labels.happened}
          </h3>
          <p className="text-[15px] leading-relaxed" style={{ color: 'var(--v-text-muted)' }}>
            {data.narrative.what_happened}
          </p>
        </div>

        <div>
          <h3 className="text-base font-medium mb-2" style={{ color: 'var(--v-text)' }}>
            {labels.worked}
          </h3>
          <p className="text-[15px] leading-relaxed" style={{ color: 'var(--v-text-muted)' }}>
            {data.narrative.what_worked}
          </p>
        </div>

        <div>
          <h3 className="text-base font-medium mb-2" style={{ color: 'var(--v-text)' }}>
            {labels.next}
          </h3>
          <ul className="space-y-2">
            {data.narrative.what_next.map((bullet, i) => (
              <li
                key={i}
                className="text-[15px] leading-relaxed flex gap-2"
                style={{ color: 'var(--v-text-muted)' }}
              >
                <span className="font-bold mt-0.5" style={{ color: 'var(--v-cyan)' }}>→</span>
                <span>{bullet}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </SectionCard>
  )
}

// ─── Section 2: Revenue breakdown ────────────────────────────────────────────

function BarRevenueList({ data }: { data: ReportData }) {
  const max = Math.max(...data.bar_revenues.map((b) => Number(b.revenue)), 0)
  if (max <= 0) return null
  return (
    <div className="space-y-2">
      {data.bar_revenues.map((b) => (
        <div key={b.bar_id} className="flex items-center gap-3">
          <span
            className="w-36 shrink-0 truncate text-sm"
            style={{ color: 'var(--v-text)' }}
            title={b.bar_name}
          >
            {b.bar_name}
          </span>
          <div
            className="flex-1 h-2 rounded-full overflow-hidden"
            style={{ background: 'var(--v-surface-raised)' }}
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${(Number(b.revenue) / max) * 100}%`,
                background: 'var(--v-cyan)',
              }}
            />
          </div>
          <span
            className="w-20 shrink-0 text-right text-sm tabular-nums"
            style={{ color: 'var(--v-text)' }}
          >
            {fmtEur(b.revenue)}
          </span>
          <span
            className="w-12 shrink-0 text-right text-xs tabular-nums"
            style={{ color: 'var(--v-text-dim)' }}
          >
            {b.revenue_pct.toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  )
}

function RevenueSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? {
          heading: 'Fatturato per Bar',
          none: 'Nessun dato di fatturato registrato.',
          perHour: 'per ora',
          avgBar: 'media bar',
          top: 'Prodotto top',
          unmapped: (amount: string) =>
            `Include ${amount} da ordini non ancora associati a un bar.`,
        }
      : {
          heading: 'Revenue by Bar',
          none: 'No revenue data recorded.',
          perHour: 'per hour',
          avgBar: 'bar average',
          top: 'Top product',
          unmapped: (amount: string) =>
            `Includes ${amount} from orders not yet mapped to a bar.`,
        }

  const unmapped = Number(data.revenue_kpis.unmapped_revenue ?? 0)

  return (
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>

      {data.bar_revenues.length > 0 ? (
        <BarRevenueList data={data} />
      ) : (
        <p className="text-sm italic py-4" style={{ color: 'var(--v-text-dim)' }}>
          {labels.none}
        </p>
      )}

      <div
        className="grid grid-cols-3 gap-4 mt-6 pt-5"
        style={{ borderTop: '0.5px solid var(--v-border)' }}
      >
        <div>
          <p className="v-label">{labels.perHour}</p>
          <p className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>
            {fmtEur(data.revenue_kpis.revenue_per_hour)}
          </p>
        </div>
        <div>
          <p className="v-label">{labels.avgBar}</p>
          <p className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>
            {fmtEur(data.revenue_kpis.revenue_per_bar_avg)}
          </p>
        </div>
        <div>
          <p className="v-label">{labels.top}</p>
          <p className="text-lg font-medium truncate" style={{ color: 'var(--v-text)' }}>
            {data.revenue_kpis.top_product_name ?? '—'}
            {data.revenue_kpis.top_product_units !== null && (
              <span
                className="text-xs ml-1 font-normal"
                style={{ color: 'var(--v-text-muted)' }}
              >
                ({data.revenue_kpis.top_product_units})
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Unmapped-order money: part of the total, attributable to no bar —
          shown explicitly rather than letting the bar list appear to
          account for everything (Day 14 migration; dashboard precedent). */}
      {unmapped > 0 && (
        <p className="text-xs italic mt-3" style={{ color: 'var(--v-text-dim)' }}>
          {labels.unmapped(fmtEur(unmapped))}
        </p>
      )}

      <RevenueDecomposition data={data} />
      <ProductPerformance data={data} />
    </SectionCard>
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
    <div className="mt-6 pt-5" style={{ borderTop: '0.5px solid var(--v-border)' }}>
      <h3 className="v-label block mb-3">{labels.heading}</h3>
      {!rd || !rd.available ? (
        <p className="text-sm italic" style={{ color: 'var(--v-text-dim)' }}>
          {labels.empty}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {(
              [
                [labels.attendance, rd.estimated_attendance ?? '—'],
                [labels.purchasers, rd.purchasers ?? '—'],
                [labels.rate, fmtPct(rd.purchase_rate_pct)],
                [labels.perPurchaser, fmtNumber(rd.orders_per_purchaser, 1)],
                [labels.aov, fmtCents(rd.average_order_value_cents)],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <p className="text-[10px] font-medium uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>
                  {label}
                </p>
                <p className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>
                  {value}
                </p>
              </div>
            ))}
          </div>
          {/* CAVEAT 2 footnote — mandatory on every surface this number
              appears, never left implicit. */}
          <p className="text-xs italic mt-3" style={{ color: 'var(--v-text-dim)' }}>
            {labels.note}
          </p>
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
        <tr style={rowBorder}>
          <th className={`${TH} text-left pr-3`} style={thStyle}>{labels.product}</th>
          <th className={`${TH} text-right px-3`} style={thStyle}>{labels.units}</th>
          <th className={`${TH} text-right pl-3`} style={thStyle}>{labels.revenue}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.product_id} style={rowBorder}>
            <td className="py-2 pr-3" style={{ color: 'var(--v-text)' }}>{r.product_name}</td>
            <td className="py-2 px-3 text-right" style={{ color: 'var(--v-text-muted)' }}>
              {r.units_sold}
            </td>
            <td className="py-2 pl-3 text-right" style={{ color: 'var(--v-text-muted)' }}>
              {fmtCents(r.revenue_cents)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <div
      className="mt-6 pt-5 grid grid-cols-1 md:grid-cols-2 gap-6"
      style={{ borderTop: '0.5px solid var(--v-border)' }}
    >
      {pp.top_products.length > 0 && (
        <div>
          <h3 className="v-label block mb-3">{labels.top}</h3>
          {productTable(pp.top_products)}
        </div>
      )}
      {pp.lowest_selling_products.length > 0 && (
        <div>
          <h3 className="v-label block mb-3">{labels.lowest}</h3>
          {productTable(pp.lowest_selling_products)}
          {/* A question, not a verdict (plan approval, Section E). */}
          <p className="text-xs italic mt-2" style={{ color: 'var(--v-text-dim)' }}>
            {labels.lowestNote}
          </p>
        </div>
      )}
    </div>
  )
}

// ─── Section 4: Alerts timeline ──────────────────────────────────────────────

const SEVERITY_BADGE: Record<ReportAlertRow['severity'], { variant: BadgeVariant; label: string }> = {
  info:     { variant: 'info',    label: 'INFO' },
  warning:  { variant: 'warning', label: 'WARNING' },
  critical: { variant: 'danger',  label: 'CRITICAL' },
  anomaly:  { variant: 'violet',  label: 'ANOMALY' },
}

function AlertsSection({ data }: { data: ReportData }) {
  const lang = data.language
  const labels =
    lang === 'it'
      ? { heading: 'Cronologia Alert', empty: 'Nessun alert registrato — la serata è filata liscia.', unack: 'Non confermato' }
      : { heading: 'Alerts Timeline', empty: 'No alerts recorded — the night ran smoothly.', unack: 'Unacknowledged' }

  if (data.alerts.length === 0) {
    return (
      <SectionCard>
        <SectionHeading>{labels.heading}</SectionHeading>
        <p className="text-sm py-4 flex items-center gap-2" style={{ color: 'var(--v-green)' }}>
          <span className="text-lg">✓</span> {labels.empty}
        </p>
      </SectionCard>
    )
  }

  return (
    <SectionCard>
      <SectionHeading>{labels.heading}</SectionHeading>

      <div className="space-y-3">
        {data.alerts.map((a: ReportAlertRow) => {
          const cfg = SEVERITY_BADGE[a.severity]
          return (
            <div
              key={a.alert_id}
              className="flex gap-3 pb-3 last:border-0"
              style={rowBorder}
            >
              <div
                className="text-xs font-mono pt-0.5 w-12 shrink-0"
                style={{ color: 'var(--v-text-dim)' }}
              >
                {fmtTime(a.fired_at)}
              </div>
              <div className="shrink-0">
                <Badge variant={cfg.variant}>{cfg.label}</Badge>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
                  {a.title}
                  {a.bar_name && (
                    <span className="font-normal" style={{ color: 'var(--v-text-muted)' }}>
                      {' '}· {a.bar_name}
                    </span>
                  )}
                </p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
                  {a.owner_message}
                </p>
                <p className="text-[11px] mt-1" style={{ color: 'var(--v-text-dim)' }}>
                  {a.acknowledged_at
                    ? `✓ ${fmtTime(a.acknowledged_at)}${a.acknowledged_by_name ? ` · ${a.acknowledged_by_name}` : ''}`
                    : labels.unack}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [language, setLanguage] = useState<ReportLanguage | null>(null)

  const { data: report, isLoading, isError } = useReport(reportId ?? null, language ?? undefined)
  const regenerate = useRegenerateReport(reportId ?? '')

  // If a language toggle was set, show that one; otherwise the backend's.
  const activeLang: ReportLanguage = language ?? report?.language ?? 'it'

  const handleRegenerate = async () => {
    try {
      const newReport = await regenerate.mutateAsync({})
      navigate(`/reports/${newReport.id}`)
    } catch {
      alert(
        activeLang === 'it'
          ? 'Impossibile rigenerare il report. Riprova.'
          : 'Failed to regenerate the report. Please try again.',
      )
    }
  }

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
    <div className="p-6 max-w-4xl mx-auto">
      {/* Breadcrumb */}
      <Link
        to="/reports"
        className="inline-flex items-center gap-1 text-sm mb-4 transition-colors hover:text-[var(--v-text)]"
        style={{ color: 'var(--v-text-muted)' }}
      >
        ← {activeLang === 'it' ? 'Torna ai report' : 'Back to reports'}
      </Link>

      {/* Loading */}
      {isLoading && (
        <div className="text-center py-12 text-sm" style={{ color: 'var(--v-text-dim)' }}>
          {activeLang === 'it' ? 'Caricamento…' : 'Loading…'}
        </div>
      )}

      {/* Error */}
      {isError && (
        <Card>
          <p className="text-sm" style={{ color: 'var(--v-pink)' }}>
            {activeLang === 'it'
              ? "Report non trovato. Potrebbe essere stato eliminato, o l'ID non è valido."
              : 'Report not found. It may have been deleted, or the ID is invalid.'}
          </p>
        </Card>
      )}

      {/* Not ready yet */}
      {report && report.status !== 'ready' && (
        <Card>
          <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>
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
            <div
              className="flex rounded-[var(--v-radius-sm)] overflow-hidden"
              style={{ border: '0.5px solid var(--v-border)' }}
            >
              {(['it', 'en'] as const).map((lang) => (
                <button
                  key={lang}
                  onClick={() => setLanguage(lang)}
                  className="px-3 py-1.5 text-xs font-medium transition-colors"
                  style={
                    activeLang === lang
                      ? { background: 'var(--v-cyan)', color: '#04121a' }
                      : { background: 'transparent', color: 'var(--v-text-muted)' }
                  }
                >
                  {lang === 'it' ? '🇮🇹 IT' : '🇬🇧 EN'}
                </button>
              ))}
            </div>
            <div className="flex-1" />
            <Button variant="secondary" onClick={handleDownloadPdf}>
              {activeLang === 'it' ? 'Scarica PDF' : 'Download PDF'}
            </Button>
            <Button
              variant="secondary"
              onClick={handleRegenerate}
              disabled={regenerate.isPending}
            >
              {regenerate.isPending
                ? activeLang === 'it' ? 'Rigenerando…' : 'Regenerating…'
                : activeLang === 'it' ? 'Rigenera' : 'Regenerate'}
            </Button>
          </div>

          <CoverBlock data={report.data} />
          <ComparisonSection data={report.data} />
          <NarrativeSection data={report.data} />
          <GuestsSection data={report.data} />
          <RevenueSection data={report.data} />
          <ForecastSection data={report.data} />
          <AlertsSection data={report.data} />

          {/* Footer: version + generated_at */}
          <p className="text-[11px] text-center mt-6" style={{ color: 'var(--v-text-dim)' }}>
            v{report.version} · {fmtDateTime(report.generated_at)}
            {report.superseded_by && (
              <span className="ml-2" style={{ color: 'var(--v-pink)' }}>
                · {activeLang === 'it' ? 'sostituito' : 'superseded'}
              </span>
            )}
          </p>
        </>
      )}
    </div>
  )
}
