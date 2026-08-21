import type { CSSProperties, ReactNode } from 'react'
import './components.css'

interface CardProps {
  children: ReactNode
  className?: string
  style?: CSSProperties
  padded?: boolean
}

/**
 * Solid surface (--v-surface) card. This is the default container for any
 * data — metrics, tables, charts, list rows. Never uses backdrop-filter:
 * that's reserved for GlassPanel (sidebar/header/modals/dropdowns) only.
 */
export function Card({ children, className = '', style, padded = true }: CardProps) {
  return (
    <div
      className={`v-card ${padded ? 'v-card--padded' : ''} ${className}`.trim()}
      style={style}
    >
      {children}
    </div>
  )
}
