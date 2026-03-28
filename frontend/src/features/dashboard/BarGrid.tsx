/**
 * BarGrid — responsive grid of BarCard components for the dashboard overview.
 */
import { BarCard, type BarSummary } from './BarCard'

interface BarGridProps {
  bars?: BarSummary[]
}

export function BarGrid({ bars = [] }: BarGridProps) {
  if (bars.length === 0) {
    return <p className="text-[#4A5568] text-sm">No bars configured for this event.</p>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
      {bars.map((bar) => (
        <BarCard key={bar.id} bar={bar} />
      ))}
    </div>
  )
}
