import type { ReactNode } from 'react'
import './components.css'

interface EmptyStateProps {
  icon?: ReactNode
  headline: string
  body: string
  action?: ReactNode
}

export function EmptyState({ icon, headline, body, action }: EmptyStateProps) {
  return (
    <div className="v-empty-state">
      {icon && <div className="v-empty-state__icon">{icon}</div>}
      <div className="v-empty-state__headline">{headline}</div>
      <div className="v-empty-state__body">{body}</div>
      {action && <div className="v-empty-state__action">{action}</div>}
    </div>
  )
}
