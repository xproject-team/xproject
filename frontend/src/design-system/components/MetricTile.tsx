import './components.css'

export type VeraRole = 'cyan' | 'violet' | 'pink' | 'amber' | 'green'

const ROLE_VAR: Record<VeraRole, string> = {
  cyan: 'var(--v-cyan)',
  violet: 'var(--v-violet)',
  pink: 'var(--v-pink)',
  amber: 'var(--v-amber)',
  green: 'var(--v-green)',
}

interface MetricTileProps {
  label: string
  value: string
  /** Optional 2px left accent bar in a role color. */
  accent?: VeraRole
  className?: string
}

/**
 * Label + value tile. Values render in plain --v-text at weight 500 —
 * never glowing or tinted; accent colors live only on the optional left
 * bar, never on the number itself.
 */
export function MetricTile({ label, value, accent, className = '' }: MetricTileProps) {
  return (
    <div
      className={`v-metric-tile ${accent ? 'v-metric-tile--accented' : ''} ${className}`.trim()}
    >
      {accent && (
        <span className="v-metric-tile__accent" style={{ backgroundColor: ROLE_VAR[accent] }} />
      )}
      <span className="v-label">{label}</span>
      <span className="v-value">{value}</span>
    </div>
  )
}
