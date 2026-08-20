import type { CSSProperties, ReactNode } from 'react'
import './components.css'

interface GlassPanelProps {
  children: ReactNode
  className?: string
  style?: CSSProperties
}

/**
 * Frosted surface (backdrop-filter blur) for chrome that sits still and
 * doesn't repeat: sidebar, top header, modals, dropdowns.
 *
 * Do NOT use for data cards, list rows, or anything that scrolls or
 * repeats — use Card instead. backdrop-filter is expensive and hurts
 * legibility on repeated numeric content.
 */
export function GlassPanel({ children, className = '', style }: GlassPanelProps) {
  return (
    <div className={`v-glass ${className}`.trim()} style={style}>
      {children}
    </div>
  )
}
