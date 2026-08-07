/**
 * BarCard — one tile in the Dashboard's 2×2 grid, one per bar at the event.
 *
 * Step 7 wire-up (April 17 2026):
 * - Accepts BarKpi from features/dashboard/selectors.ts
 * - Real fields render normally: name, status, revenue, drinks sold,
 *   tier breakdown, stock level
 * - Placeholder fields (burn_rate, burn_trend, time_to_depletion_min,
 *   staff_count, last_alert) render as "—" with a subtle "soon" treatment.
 *   They'll become real once burn-rate computation, staff shifts, and
 *   alerts backends ship.
 */
import { useState } from 'react'

import type { BarKpi, BarRow, BarStatus, StockTransactionRow } from '@/lib/mockData'

import { BarMiniChart } from '@/features/dashboard/BarMiniChart'
import { FoodBarCard } from '@/features/dashboard/FoodBarCard'
import type { ProductLike } from '@/features/dashboard/category-resolver'
import '@/design-system/components/components.css'

interface BarCardProps {
  bar: BarKpi
  /** Number of active critical alerts for this bar (from useAlertsCountByBar).
   * When > 0, a pulsing red pill renders next to the bar name. */
  criticalAlertCount?: number
  onClick: (barId: string) => void
  /** Live event transactions across ALL bars; BarMiniChart filters by bar.id */
  transactions: StockTransactionRow[]
  /** Catalog products for category resolution */
  products: ProductLike[]
  /** Event start time (ms since epoch) — needed for adaptive time-bucketing */
  eventStartMs: number
  /** "Now" reference in ms — same value passed to all bar cards on this render */
  nowMs: number
  /** Warehouse storage dispatched to THIS bar for the current event.
   *  Reads from event_stock_bar_allocations via useBarAllocations on
   *  the DashboardPage. Optional — undefined / zero-item bars render
   *  nothing (no clutter on bars that haven't been charged yet). */
  storage?: { itemCount: number; totalUnits: number }
  /** Inline name-picker (passed only for auto-created stub cards).
   *  When present, renders "Map this shop to" select listing empty
   *  wizard bars of matching bar_type. On select, calls onMerge which
   *  fires POST /bars/{src}/merge-into/{dst} via useMergeBars. */
  mergeOptions?: {
    available: BarRow[]
    suggested: string | null
    onMerge: (srcId: string, dstId: string) => void
  }
}

export const STATUS_CFG: Record<BarStatus, { dot: string; label: string; accent: string }> = {
  healthy:  { dot: 'var(--v-green)', label: 'Healthy',   accent: 'var(--v-green)' },
  warning:  { dot: 'var(--v-amber)', label: 'Low Stock', accent: 'var(--v-amber)' },
  critical: { dot: 'var(--v-pink)',  label: 'Critical',  accent: 'var(--v-pink)' },
}

function stockBarColor(pct: number) {
  if (pct > 60) return 'var(--v-green)'
  if (pct > 30) return 'var(--v-amber)'
  return 'var(--v-pink)'
}

// ─── Small "not yet available" pill used by placeholder fields ──────────────
// Kept intentionally quiet — doesn't scream, but makes it obvious this number
// will become real once the relevant backend ships. One line, italicized, dim.

export function Placeholder({ label }: { label: string }) {
  return (
    <span className="italic" style={{ color: 'var(--v-text-dim)' }} title={`${label} — coming soon`}>
      —
    </span>
  )
}

// ─── Food-bar middle section (Phase D-bis) ──────────────────────────────────
// Food bars don't have drink categories or a burn chart; they show per-item
// counts (sold + remaining). Same card wrapper, name, alert pill, overlay.
export function BarCard({
  bar,
  criticalAlertCount = 0,
  onClick,
  transactions,
  products,
  eventStartMs,
  nowMs,
  mergeOptions,
  storage,
}: BarCardProps) {
  const cfg      = STATUS_CFG[bar.status]
  const stockPct = bar.stock_pct
  // Track the picked destination once the dropdown fires merge — locks
  // the select so a fast double-tap can't issue a second mutation in
  // the ~1s window before mapping-state refetches and the stub unmounts.
  const [pickedDstId, setPickedDstId] = useState<string>('')

  // ── Food vendor bars get a different card variant ──
  // Food trucks/vendors are independent businesses Omar invites to the
  // event — they bring their own staff + inventory. Burn-rate / depletion /
  // stock-level tiles describe inventory the VENDOR owns, not Omar, so they
  // don't apply here. Delegate to FoodBarCard which shows the things Omar
  // actually cares about for food bars: revenue, his cut, items sold, and
  // device health. See FoodBarCard.tsx for the full rationale.
  if (bar.bar_type === 'food') {
    return (
      <FoodBarCard
        bar={bar}
        criticalAlertCount={criticalAlertCount}
        onClick={onClick}
        mergeOptions={mergeOptions}
      />
    )
  }

  const revenueEuros = Math.round(bar.revenue_cents / 100)

  return (
    <button
      onClick={() => onClick(bar.id)}
      className="v-card w-full h-full text-left p-4 relative overflow-hidden"
      style={{
        borderLeft: bar.auto_created ? '2px dashed var(--v-amber)' : `2px solid ${cfg.accent}`,
      }}
    >
      {/* 1+3 — Bar name + status dot + revenue */}
      <div className="flex items-start justify-between mb-1">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: cfg.dot }} />
          <h3 className="font-medium text-base leading-tight" style={{ color: 'var(--v-text)' }}>{bar.name}</h3>
          {criticalAlertCount > 0 && (
            <span
              className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
              style={{ background: 'rgba(255, 61, 113, 0.12)', color: 'var(--v-pink)', border: '0.5px solid var(--v-pink)' }}
              title={`${criticalAlertCount} active critical alert${criticalAlertCount === 1 ? '' : 's'}`}
            >
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--v-pink)' }} />
              {criticalAlertCount}
            </span>
          )}
          {bar.auto_created && (
            <span
              className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
              style={{ background: 'rgba(255, 216, 77, 0.12)', color: 'var(--v-amber)', border: '0.5px solid var(--v-amber)' }}
              title="Auto-created from an unmapped Slesh shop_id — open this card to merge it into a properly named bar"
            >
              <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              NEEDS REVIEW
            </span>
          )}
        </div>
        <div className="text-right shrink-0 ml-3">
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Revenue</p>
          <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>€{revenueEuros.toLocaleString()}</p>
        </div>
      </div>

      {/* 2 — Status label */}
      <p className="text-xs font-semibold mb-3" style={{ color: cfg.accent }}>{cfg.label}</p>

      {/* Warehouse storage line — shows what's been dispatched from the
          event's storage pool to this bar. Only renders when at least
          one item has been dispatched, to keep empty bars clean. */}
      {storage && storage.itemCount > 0 && (
        <div className="flex items-center gap-1.5 mb-3 text-[11px]" style={{ color: 'var(--v-text-muted)' }}>
          <svg className="w-3 h-3 shrink-0" style={{ color: 'var(--v-cyan)' }} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          </svg>
          <span>
            <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{storage.itemCount}</span>{' '}
            {storage.itemCount === 1 ? 'item' : 'items'}
            {' · '}
            <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{storage.totalUnits}</span>{' '}
            units in warehouse
          </span>
        </div>
      )}
      {/* Shop_id suffix on mapped cards — gives alert cross-reference.
          Stubs already show the truncated shop_id as their name, so this
          line is suppressed for them. */}
      {bar.slesh_negozio_id && !bar.auto_created && (
        <p
          className="text-[10px] font-mono -mt-2 mb-3 truncate"
          style={{ color: 'var(--v-text-dim)' }}
          title={`Slesh shop_id: ${bar.slesh_negozio_id}`}
        >
          shop · {bar.slesh_negozio_id.slice(0, 8)}…{bar.slesh_negozio_id.slice(-4)}
        </p>
      )}

      {/* Inline name-picker (Phase 1) — shows only on stub cards where
          mergeOptions was passed by the DashboardPage. Picking one of the
          empty wizard bars fires POST /bars/{src}/merge-into/{dst} which
          transfers the stub's transactions + shop_id onto the wizard bar
          and deletes the stub. Wrapped in stopPropagation so the dropdown
          doesn't trigger the card-level BarDetailOverlay underneath. */}
      {bar.auto_created && mergeOptions && mergeOptions.available.length > 0 && (
        <div className="mb-3" onClick={(e) => e.stopPropagation()}>
          <label className="text-[10px] font-semibold uppercase tracking-wide block mb-1" style={{ color: 'var(--v-amber)' }}>
            Map this shop to
          </label>
          <select
            className="w-full text-sm rounded-lg px-2 py-1.5 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
            style={{ background: 'var(--v-surface-raised)', border: '1px solid var(--v-amber)', color: 'var(--v-text)' }}
            value={pickedDstId}
            onChange={(e) => {
              const dstId = e.target.value
              if (dstId && !pickedDstId) {
                setPickedDstId(dstId)
                mergeOptions.onMerge(bar.id, dstId)
              }
            }}
            disabled={Boolean(pickedDstId)}
          >
            <option value="" disabled>
              {mergeOptions.suggested
                ? `Suggested: ${mergeOptions.available.find((b) => b.id === mergeOptions.suggested)?.name ?? '—'}`
                : '— pick a bar —'}
            </option>
            {mergeOptions.available.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
                {b.id === mergeOptions.suggested ? ' (suggested)' : ''}
                {b.device_count ? ` · ${b.device_count} devices` : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* 4 — Revenue by category over time (5 lines: 4 categories + total)
            Replaces the old tier B/S/P/U chips. Locked May 27 2026: bars
            display multi-line per-category chart for live-sale-crash
            detection. Categories: beer / cocktails / premium_cocktails / wine. */}
      {/* Drinks-sold chart. Food bars short-circuit to FoodBarCard at the
          top of this function, so this block is drinks-only. */}
      <div className="mb-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>Drinks Sold</p>
          <p className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>{bar.drinks_sold}</p>
        </div>
        <BarMiniChart
          barId={bar.id}
          transactions={transactions}
          products={products}
          eventStartMs={eventStartMs}
          nowMs={nowMs}
          height={120}
        />
      </div>

      {/* 5 — Stock Level (REAL) */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>Stock Level</p>
          <p className="text-xs font-semibold" style={{ color: 'var(--v-text)' }}>
            {bar.current_stock}/{bar.initial_stock} units
          </p>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--v-border)' }}>
          <div
            className="h-full rounded-full"
            style={{ width: `${stockPct}%`, background: stockBarColor(stockPct) }}
          />
        </div>
        <p className="text-[10px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>{stockPct}% remaining</p>
      </div>

      {/* 6+7+8 — Burn Rate / Time to Depletion / Staff — PLACEHOLDERS (v1.1) */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Burn Rate</p>
          <p className="text-sm font-medium mt-0.5" style={{ color: 'var(--v-text)' }}>
            {bar.burn_rate === null ? <Placeholder label="Burn rate — no recent sales" /> : bar.burn_rate.toFixed(1)}
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>btl/hr</p>
        </div>

        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Depletion</p>
          <p className="text-sm font-medium mt-0.5" style={{ color: 'var(--v-text)' }}>
            {bar.time_to_depletion_min === null ? <Placeholder label="Depletion — needs data" /> : bar.time_to_depletion_min < 60 ? Math.round(bar.time_to_depletion_min) + "m" : Math.floor(bar.time_to_depletion_min / 60) + "h" + (Math.round(bar.time_to_depletion_min % 60)) + "m"}
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>remaining</p>
        </div>

        {/* Staff tile — Phase 2 (Jun 21 2026): real device data.
             Format: {active}/{total}, e.g. "7/9" — one Slesh device per bartender.
             Active goes green when any device is logged in; subtitle adapts. */}
        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Staff</p>
          <p className="text-sm font-medium mt-0.5 flex items-center justify-center gap-0.5" style={{ color: 'var(--v-text)' }}>
            <svg className="w-3.5 h-3.5" style={{ color: 'var(--v-text-dim)' }} fill="currentColor" viewBox="0 0 20 20">
              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
            </svg>
            {bar.devices_total === 0 ? (
              <Placeholder label="No devices configured" />
            ) : (
              <span>
                <span style={{ color: bar.devices_active > 0 ? 'var(--v-green)' : 'var(--v-text-dim)' }}>
                  {bar.devices_active}
                </span>
                <span style={{ color: 'var(--v-text-dim)' }}>/</span>
                {bar.devices_total}
              </span>
            )}
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>
            {bar.devices_total === 0 ? 'unconfigured' : 'active'}
          </p>
        </div>
      </div>

    </button>
  )
}
