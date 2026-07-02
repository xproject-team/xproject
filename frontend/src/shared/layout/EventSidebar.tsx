/**
 * EventSidebar — nav shown while the Owner is inside an event
 * (/events/:id/*). Rendered by Sidebar.tsx (see EVENT_SCOPED_RE)
 * instead of the flat global nav.
 *
 * Charge Bars stays visible for every event status, including
 * COMPLETED — the page itself already renders a read-only banner and
 * disables its inputs (Chunk 3b); the sidebar doesn't need its own
 * copy of that logic.
 *
 * Chat is intentionally absent here — there's no /events/:id/chat
 * today (chat isn't event-scoped), so it stays in the global nav
 * instead of being duplicated or half-wired here.
 */
import { Link, useLocation, useParams } from 'react-router-dom'

import { ICONS } from './icons'

interface EventNavItem {
  label: string
  segment: string
  icon: React.ReactNode
}

const EVENT_NAV_ITEMS: EventNavItem[] = [
  { label: 'Overview',    segment: 'overview',    icon: ICONS.clipboardList },
  { label: 'Dashboard',   segment: 'dashboard',   icon: ICONS.grid },
  { label: 'Catalog',     segment: 'catalog',     icon: ICONS.wineGlass },
  { label: 'Charge Bars', segment: 'charge-bars', icon: ICONS.swap },
  { label: 'Inventory',   segment: 'inventory',   icon: ICONS.package },
  { label: 'Warehouse',   segment: 'warehouse',   icon: ICONS.warehouse },
  { label: 'Alerts',      segment: 'alerts',      icon: ICONS.bell },
  { label: 'Predictions', segment: 'predictions', icon: ICONS.trendingUp },
  { label: 'Reports',     segment: 'reports',     icon: ICONS.fileText },
]

export function EventSidebar() {
  const { id } = useParams<{ id: string }>()
  const { pathname } = useLocation()

  return (
    <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
      {EVENT_NAV_ITEMS.map((item) => {
        const path = `/events/${id}/${item.segment}`
        const active = pathname === path || pathname.startsWith(path + '/')
        return (
          <Link
            key={item.segment}
            to={path}
            className={[
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all',
              active
                ? 'bg-[#6C63FF] text-white shadow-sm'
                : 'text-blue-100 hover:bg-white/10 hover:text-white',
            ].join(' ')}
          >
            {item.icon}
            <span className="truncate">{item.label}</span>
          </Link>
        )
      })}
    </nav>
  )
}
