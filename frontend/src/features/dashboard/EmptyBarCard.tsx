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

interface EmptyBarCardProps {
  bar: BarRow
}

export function EmptyBarCard({ bar }: EmptyBarCardProps) {
  const isFood = bar.bar_type === 'food'
  return (
    <div
      className="rounded-xl p-5 border-2 border-dashed border-[#CBD5E0] bg-[#F7FAFC] text-left"
      title={`${bar.name} — awaiting first transaction from Slesh`}
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-2.5 h-2.5 rounded-full shrink-0 bg-[#A0AEC0]" />
        <h3 className="font-bold text-[#4A5568] text-base leading-tight truncate">
          {bar.name}
        </h3>
      </div>
      <p className="text-xs italic text-[#A0AEC0] mb-6">Awaiting activity</p>
      <div className="flex items-center justify-between text-[10px] text-[#A0AEC0] uppercase tracking-wide">
        <span>{isFood ? 'Food truck' : 'Bar'}</span>
        {(bar.device_count ?? 0) > 0 && (
          <span className="tabular-nums">{bar.device_count} devices</span>
        )}
      </div>
    </div>
  )
}
