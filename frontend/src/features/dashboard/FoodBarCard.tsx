/**
 * FoodBarCard — variant of BarCard for food vendor bars (bar_type === 'food').
 *
 * System design rationale (Jun 21 2026):
 * Food trucks/vendors are independent businesses invited to Sundance. They
 * bring their own staff, their own inventory, and their own operational
 * concerns. Omar's relationship with them is purely commercial: he gives
 * them a Slesh device, they sell, and he takes a percentage cut of gross
 * revenue at event end (Sundance 14 = 30%, see commit 0868449).
 *
 * As a result, the drink-card tiles (Burn Rate, Stock Level, Time to
 * Depletion) are meaningless here — Omar has no signal to act on. What he
 * DOES care about for food bars:
 *   1. Gross revenue (his cut depends on it)
 *   2. Items sold ranking (popularity insight for next event)
 *   3. Slesh device health (broken device = no sales = no cut)
 *   4. His effective take (revenue × food_share_pct)
 *
 * This card shows exactly those — no more, no less.
 */
import { useState } from 'react'

import type { BarKpi, BarRow, FoodItemCount } from '@/lib/mockData'

import { STATUS_CFG, Placeholder } from '@/features/dashboard/BarCard'
import { EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

// ── Owner's share of food-vendor gross revenue ───────────────────────────────
// Read from event.food_revenue_share_pct (carried on each BarKpi as
// food_revenue_share_pct). The DB column is an int 0-100; we convert to a
// 0-1 ratio at the use site. Wizard (Phase 4) is where Omar configures
// this per event. When NULL we fall back to 30% — matches Sundance 14
// baseline and keeps the card legible for events created before the field
// was wired through.
const FOOD_SHARE_PCT_DEFAULT = 30  // percent

interface FoodBarCardProps {
  bar: BarKpi
  criticalAlertCount?: number
  onClick: (barId: string) => void
  mergeOptions?: {
    available: BarRow[]
    suggested: string | null
    onMerge: (srcId: string, dstId: string) => void
  }
}

/** Items-sold leaderboard for food bars. Unlike the drink-card food body
 *  this OMITS the "X left" / remaining column, because Omar does not own
 *  or track food-vendor inventory — the vendor brings + manages it. */
function FoodLeaderboard({ items }: { items: FoodItemCount[] }) {
  const totalSold = items.reduce((sum, i) => sum + i.sold, 0)
  const top = items.slice(0, 6)
  return (
    <div className="mb-3" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>Items Sold</p>
        <p className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>{totalSold}</p>
      </div>
      {top.length === 0 ? (
        <EmptyState headline="No items sold yet" body="Sales will appear here once the vendor's first order lands." />
      ) : (
        <ul className="space-y-1">
          {top.map((it) => (
            <li key={it.name} className="flex items-center justify-between text-xs">
              <span className="truncate pr-2" style={{ color: 'var(--v-text)' }}>{it.name}</span>
              <span className="shrink-0 tabular-nums font-semibold" style={{ color: 'var(--v-text)' }}>
                {it.sold} sold
              </span>
            </li>
          ))}
          {items.length > top.length && (
            <li className="text-[10px] italic pt-0.5" style={{ color: 'var(--v-text-dim)' }}>
              +{items.length - top.length} more…
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

export function FoodBarCard({
  bar,
  criticalAlertCount = 0,
  onClick,
  mergeOptions,
}: FoodBarCardProps) {
  const cfg = STATUS_CFG[bar.status]
  const [pickedDstId, setPickedDstId] = useState<string>('')

  const revenueEuros  = Math.round(bar.revenue_cents / 100)
  const sharePct  = bar.food_revenue_share_pct ?? FOOD_SHARE_PCT_DEFAULT
  const omarsCutEuros = Math.round((bar.revenue_cents * sharePct) / 100 / 100)

  return (
    <button
      onClick={() => onClick(bar.id)}
      className="v-card w-full h-full text-left p-4 relative overflow-hidden"
      style={{
        borderLeft: bar.auto_created ? '2px dashed var(--v-amber)' : `2px solid ${cfg.accent}`,
      }}
    >
      {/* Header: status dot + name + alert pills + revenue */}
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

      {/* Status label */}
      <p className="text-xs font-semibold mb-3" style={{ color: cfg.accent }}>{cfg.label}</p>

      {/* NOTE: Warehouse storage line intentionally omitted. Food vendors
          bring their own inventory; nothing dispatches from Omar's storage
          pool to a food bar. */}

      {/* Slesh shop_id reference (suppressed for stubs whose name IS the shop_id) */}
      {bar.slesh_negozio_id && !bar.auto_created && (
        <p
          className="text-[10px] font-mono -mt-2 mb-3 truncate"
          style={{ color: 'var(--v-text-dim)' }}
          title={`Slesh shop_id: ${bar.slesh_negozio_id}`}
        >
          shop · {bar.slesh_negozio_id.slice(0, 8)}…{bar.slesh_negozio_id.slice(-4)}
        </p>
      )}

      {/* Merge dropdown for auto-created stubs (same behavior as BarCard) */}
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
              if (dstId) {
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

      {/* Items sold leaderboard (no "X left") */}
      <FoodLeaderboard items={bar.food_items} />

      {/* Operational tiles: Omar's Cut + Staff. Intentionally only 2 tiles —
          Burn Rate, Depletion, and Stock Level describe inventory the
          VENDOR owns, not Omar, so they're omitted entirely. */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Omar's Cut</p>
          <p className="text-sm font-medium mt-0.5" style={{ color: 'var(--v-text)' }}>
            €{omarsCutEuros.toLocaleString()}
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>
            {sharePct}% share
          </p>
        </div>

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

      {/* Alerts feed placeholder (v1.1) — same as BarCard */}
      <div className="rounded-lg px-3 py-2 text-xs" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-text-dim)' }}>
        <span className="flex items-center gap-1.5 italic">
          <span>ⓘ</span>
          <span>Alerts feed arrives in v1.1</span>
        </span>
      </div>
    </button>
  )
}
