import type { ReactNode } from 'react'
import './components.css'

interface PageHeaderProps {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="v-page-header">
      <div>
        <h1 className="v-page-header__title">{title}</h1>
        {subtitle && <p className="v-page-header__subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="v-page-header__actions">{actions}</div>}
    </div>
  )
}
