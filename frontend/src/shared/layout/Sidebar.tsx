/**
 * Sidebar — collapsible navigation rail with role-filtered menu items.
 * Collapse state is managed by the Zustand store (sidebarCollapsed).
 */
import { Link, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Events', path: '/events' },
  { label: 'Warehouse', path: '/warehouse/scan' },
  { label: 'Predictions', path: '/predictions' },
  { label: 'Reports', path: '/reports' },
  { label: 'Settings', path: '/settings' },
]

export function Sidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="w-56 bg-[#1E5A8D] text-white flex flex-col">
      <div className="p-4 font-bold text-lg tracking-tight">XProject</div>
      <nav className="flex-1 px-2">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`block px-3 py-2 rounded text-sm mb-1 transition-colors ${
              pathname.startsWith(item.path)
                ? 'bg-[#6C63FF] font-medium'
                : 'hover:bg-white/10'
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  )
}
