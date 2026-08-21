/**
 * EmptyBarCard — muted placeholder card for wizard-defined bars that
 * haven't yet been bound to a Slesh shop_id. Renders in the "Awaiting
 * activity" region of the dashboard (Phase 1 — bar-mapping redesign).
 *
 * Once a Slesh order arrives and the ingester auto-creates a stub
 * with this bar's name (via the inline name-picker merge), this card
 * is replaced by the normal/stub BarCard variant on next refetch of
 * /bars/mapping-state.
 */
import type { BarRow } from '@/lib/mockData'
import '@/design-system/components/components.css'

interface EmptyBarCardProps {
  bar: BarRow
}

export function EmptyBarCard({ bar }: EmptyBarCardProps) {
  const isFood = bar.bar_type === 'food'
  return (
    <div
      className="rounded-[var(--v-radius)] p-4 text-left h-full"
      style={{ border: '2px dashed var(--v-border)', background: 'var(--v-surface)' }}
      title={`${bar.name} — awaiting first transaction from Slesh`}
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: 'var(--v-text-dim)' }} />
        <h3 className="font-medium text-base leading-tight truncate" style={{ color: 'var(--v-text-dim)' }}>
          {bar.name}
        </h3>
      </div>
      <p className="text-xs italic mb-6" style={{ color: 'var(--v-text-dim)' }}>Awaiting activity</p>
      <div className="flex items-center justify-between text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-dim)' }}>
        <span>{isFood ? 'Food truck' : 'Bar'}</span>
        {(bar.device_count ?? 0) > 0 && (
          <span className="tabular-nums">{bar.device_count} devices</span>
        )}
      </div>
    </div>
  )
}
