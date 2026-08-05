import type { ReactNode } from 'react'
import './components.css'

export type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
}

export function Badge({ children, variant = 'neutral' }: BadgeProps) {
  return <span className={`v-badge v-badge--${variant}`}>{children}</span>
}
