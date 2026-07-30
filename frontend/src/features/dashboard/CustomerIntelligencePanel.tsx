/**
 * CustomerIntelligencePanel — Day 4 Customer Intelligence panel.
 *
 * Sits below RechargeDeskCard and above the bar-card grid on the
 * Dashboard (see DashboardPage.tsx) — same "top-down: KPIs -> live
 * trend -> money -> per-bar detail" reading order the page already
 * follows. Visual language matches RevenueForecastPanel exactly (same
 * card shell, label/value type scale, Divider rhythm, tier colors) —
 * no new visual system introduced.
 *
 * SCOPE (locked by Day 3's validation, do not expand):
 *   SHIPS: venue-total next-hour forecast + band, category breakdown
 *     (cocktail/spritz marked lower-confidence), live guest count +
 *     projected final, registered/guest split, spend segments,
 *     returning guests, predicted-vs-actual per hour, hot-night toggle.
 *   DOES NOT SHIP: per-bar forecast (263% MAPE — not defensible on
 *     screen, see the Day 3 closeout report).
 *
 * Degrades independently per the backend's contract: an untrained
 * demand model shows a muted "Forecast unavailable" block but every
 * other section (guests/spend/returning) still renders from live data.
 * Renders nothing (returns null) before the event has any orders yet —
 * see EmptyState below — and for events with no identity data at all
 * (0 identified guests), which covers both "before doors open" and
 * "an event without identity extraction" per the Day 4 empty-state spec.
 */
import { useState } from 'react'

import type {
  CategoryForecast,
  CustomerIntelligenceResponse,
  HourlyPredictedVsActual,
} from '@/features/customer-intelligence/useCustomerIntelligence'
import { useSetHotNightOverride } from '@/features/customer-intelligence/useCustomerIntelligence'

export interface CustomerIntelligencePanelProps {
  eventId: string | null | undefined
  data:    CustomerIntelligenceResponse | null
  loading: boolean
  error:   Error | null
}

type Tier = 'early' | 'directional' | 'trustworthy'

const TIER_COLOR: Record<Tier, string> = {
  early:       '#A0AEC0',
  directional: '#DD8B3B',
  trustworthy: '#38A169',
}

const TIER_BADGE_BG: Record<Tier, string> = {
  early:       'bg-[#A0AEC0]/15',
  directional: 'bg-[#DD8B3B]/15',
  trustworthy: 'bg-[#38A169]/15',
}

function confidenceTier(confidence: number): Tier {
  if (confidence < 0.5) return 'early'
  if (confidence < 0.8) return 'directional'
  return 'trustworthy'
}

function Divider() {
  return <div className="h-px bg-[#E2E8F0] my-3" />
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] text-[#A0AEC0]">{children}</div>
}

const CATEGORY_DISPLAY: Record<string, string> = {
  beer: 'Beer', cocktail: 'Cocktail', spritz: 'Spritz',
  wine: 'Wine', premium: 'Premium', other: 'Other',
}

function CategoryRow({ cat }: { cat: CategoryForecast }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-xs text-[#4A5568] flex items-center gap-1">
        {CATEGORY_DISPLAY[cat.category] ?? cat.category}
        {cat.low_confidence && (
          <span
            title="Model does not beat baseline on this category (Day 3 validation) — heat-sensitive, treat as indicative."
            className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#DD8B3B]/15 text-[#DD8B3B] text-[9px] font-bold cursor-help"
          >
            !
          </span>
        )}
      </span>
      <span className="text-xs font-semibold tabular-nums text-[#2E4B7A]">
        {cat.predicted_count.toFixed(0)}
      </span>
    </div>
  )
}

function PredictedVsActualRow({ row }: { row: HourlyPredictedVsActual }) {
  const max = Math.max(row.predicted, row.actual, 1)
  const beatForecast = row.actual >= row.predicted
  return (
    <div className="mb-1.5">
      <div className="flex items-center justify-between text-[11px] text-[#A0AEC0] mb-0.5">
        <span>Hour {row.hour_of_event.toFixed(0)}</span>
        <span className="tabular-nums">
          {row.actual.toFixed(0)} actual / {row.predicted.toFixed(0)} predicted
        </span>
      </div>
      <div className="relative h-2.5 rounded-full bg-[#E2E8F0] overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-[#A0AEC0]/60"
          style={{ width: `${(row.predicted / max) * 100}%` }}
        />
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width:           `${(row.actual / max) * 100}%`,
            backgroundColor: beatForecast ? '#38A169' : '#DD8B3B',
            opacity:         0.85,
          }}
        />
      </div>
    </div>
  )
}

function HotNightToggle({ eventId, enabled }: { eventId: string; enabled: boolean }) {
  const mutation = useSetHotNightOverride(eventId)
  return (
    <button
      type="button"
      onClick={() => mutation.mutate(!enabled)}
      disabled={mutation.isPending}
      title="Manual heat adjustment: boosts spritz share for hours 1-5 on a hot night (Day 3 finding: +12-19pp spritz on the one >=33C event observed). Indicative, never automatic."
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium border transition-colors ${
        enabled
          ? 'bg-[#DD8B3B]/15 border-[#DD8B3B]/40 text-[#DD8B3B]'
          : 'bg-white border-[#E2E8F0] text-[#A0AEC0]'
      }`}
    >
      <span>🔥</span>
      Hot night {enabled ? 'ON' : 'off'}
    </button>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="border border-[#E2E8F0] rounded-lg bg-white p-4 shadow-sm mb-4">
      <span className="text-[11px] font-semibold tracking-wide text-[#A0AEC0] uppercase">
        Customer Intelligence
      </span>
      <div className="mt-3 text-xs text-[#A0AEC0] italic">{message}</div>
    </div>
  )
}

export function CustomerIntelligencePanel({
  eventId, data, loading, error,
}: CustomerIntelligencePanelProps) {
  const [showAllHours, setShowAllHours] = useState(false)

  if (loading && !data) {
    return <EmptyState message="Loading customer intelligence…" />
  }
  if (error || !data) {
    // Never breaks the surrounding dashboard — same contract as
    // RevenueForecastPanel's error/empty path.
    return <EmptyState message="Customer intelligence unavailable" />
  }
  if (data.hour_offset_from_start === null) {
    return <EmptyState message="Before doors open — stats will appear once the first order lands." />
  }
  if (data.guests.live_identified_count === 0 && !data.demand_forecast.available) {
    return <EmptyState message="No customer identity data for this event yet." />
  }

  const { demand_forecast: forecast, guests, spend_segments: spend, returning_guests: returning } = data
  const nextHour = forecast.available ? forecast.next_hour : null
  const tier = forecast.confidence != null ? confidenceTier(forecast.confidence) : 'early'

  const rowsToShow = showAllHours
    ? data.predicted_vs_actual
    : data.predicted_vs_actual.slice(-4)

  return (
    <div className="border border-[#E2E8F0] rounded-lg bg-white p-4 shadow-sm mb-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-semibold tracking-wide text-[#A0AEC0] uppercase">
          Customer Intelligence
        </span>
        {eventId && <HotNightToggle eventId={eventId} enabled={data.hot_night_override} />}
      </div>

      <div className="grid grid-cols-1 min-[640px]:grid-cols-2 min-[1100px]:grid-cols-4 gap-4 mt-3">
        {/* Next-hour forecast + band — the honest part, made obvious */}
        <div>
          <Label>Next hour forecast</Label>
          {!forecast.available ? (
            <div className="text-xs text-[#A0AEC0] italic mt-1">
              {forecast.unavailable_reason ?? 'Forecast unavailable'}
            </div>
          ) : !nextHour ? (
            <div className="text-xs text-[#A0AEC0] italic mt-1">No further hours to forecast.</div>
          ) : (
            <>
              <div className="text-xl font-bold text-[#1E5A8D]">
                {nextHour.predicted_total.toFixed(0)} drinks
              </div>
              <div
                className="text-xs font-semibold mt-0.5"
                style={{ color: TIER_COLOR[tier] }}
              >
                {nextHour.confidence_interval.lower.toFixed(0)}–{nextHour.confidence_interval.upper.toFixed(0)}
                {' '}({nextHour.confidence_interval.half_width_pct.toFixed(0)}% band)
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-[#E2E8F0] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width:           `${Math.round((forecast.confidence ?? 0) * 100)}%`,
                      backgroundColor: TIER_COLOR[tier],
                    }}
                  />
                </div>
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${TIER_BADGE_BG[tier]}`}
                  style={{ color: TIER_COLOR[tier] }}
                >
                  {tier}
                </span>
              </div>
              {forecast.hot_night_applied && (
                <div className="text-[10px] text-[#DD8B3B] mt-1">
                  🔥 hot-night adjustment applied — indicative
                </div>
              )}
            </>
          )}
        </div>

        {/* Category breakdown */}
        <div>
          <Label>Category breakdown (next hour)</Label>
          <div className="mt-1">
            {nextHour ? (
              nextHour.category_breakdown.map((cat) => (
                <CategoryRow key={cat.category} cat={cat} />
              ))
            ) : (
              <div className="text-xs text-[#A0AEC0] italic mt-1">—</div>
            )}
          </div>
        </div>

        {/* Guests */}
        <div>
          <Label>Guests identified</Label>
          <div className="text-xl font-bold text-[#2E4B7A]">{guests.live_identified_count}</div>
          {guests.projected_final != null && (
            <div className="text-[11px] text-[#A0AEC0]">
              projected final ≈ {guests.projected_final.toFixed(0)}
            </div>
          )}
          <Divider />
          <Label>Registered vs guest</Label>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#38A169]">{guests.registered_count}</span> registered
            </span>
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#A0AEC0]">{guests.guest_count}</span> guest
            </span>
            {guests.unknown_count > 0 && (
              <span className="text-xs text-[#4A5568]">
                <span className="font-semibold text-[#A0AEC0]">{guests.unknown_count}</span> unknown
              </span>
            )}
          </div>
        </div>

        {/* Spend segments + returning guests */}
        <div>
          <Label>Spend segments</Label>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#1E5A8D]">{spend.whale_count}</span> whale
            </span>
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#2E4B7A]">{spend.regular_count}</span> regular
            </span>
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#A0AEC0]">{spend.light_count}</span> light
            </span>
          </div>
          <Divider />
          <Label>Returning guests</Label>
          <div className="text-base font-semibold text-[#2E4B7A]">
            {returning.returning_count} <span className="text-[11px] font-normal text-[#A0AEC0]">/ {returning.identified_total} identified</span>
          </div>
          <div className="text-[11px] text-[#A0AEC0]">from Jun-14 / Jul-5 / Jul-19</div>
        </div>
      </div>

      {data.predicted_vs_actual.length > 0 && (
        <>
          <Divider />
          <div className="flex items-center justify-between mb-1">
            <Label>Predicted vs actual, per hour</Label>
            {data.predicted_vs_actual.length > 4 && (
              <button
                type="button"
                onClick={() => setShowAllHours((v) => !v)}
                className="text-[11px] text-[#1E5A8D] hover:underline"
              >
                {showAllHours ? 'show recent' : `show all ${data.predicted_vs_actual.length}`}
              </button>
            )}
          </div>
          <div className="mt-1">
            {rowsToShow.map((row) => (
              <PredictedVsActualRow key={row.hour_of_event} row={row} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
