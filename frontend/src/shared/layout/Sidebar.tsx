import { Link, useLocation, useNavigate } from 'react-router-dom'
import { type ReactNode } from 'react'
import { useAuth } from '@/features/auth/useAuth'
import type { MockUser } from '@/lib/mockUsers'
import { EventSidebar } from './EventSidebar'
import { ICONS } from './icons'

// ─── Role presentation ────────────────────────────────────────────────────────

const ROLE_LABEL: Record<MockUser['role'], string> = {
  owner:     'Owner',
  manager:   'Manager',
  warehouse: 'Warehouse Staff',
  bartender: 'Bartender',
}

const ROLE_AVATAR_COLOR: Record<MockUser['role'], string> = {
  owner:     '#1ABC9C',
  manager:   '#3498DB',
  warehouse: '#D69E2E',
  bartender: '#E74C3C',
}

const ROLE_BADGE: Record<MockUser['role'], string> = {
  owner:     'bg-[#E6FBF6] text-[#1ABC9C] border-[#1ABC9C]/40',
  manager:   'bg-[#EBF5FB] text-[#3498DB] border-[#3498DB]/40',
  warehouse: 'bg-[#FEF9E7] text-[#D69E2E] border-[#D69E2E]/40',
  bartender: 'bg-[#FDEDEC] text-[#E74C3C] border-[#E74C3C]/40',
}

const ROLE_INITIAL: Record<MockUser['role'], string> = {
  owner: 'O', manager: 'M', warehouse: 'W', bartender: 'B',
}

// ─── SVG icon helper ──────────────────────────────────────────────────────────





// ─── Nav item type ────────────────────────────────────────────────────────────

interface NavItem {
  label: string
  path: string
  icon: ReactNode
  /** Match exactly — avoids /warehouse matching /warehouse/inventory */
  exact?: boolean
}

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.path
  return pathname === item.path || pathname.startsWith(item.path + '/')
}

// ─── Role nav maps ────────────────────────────────────────────────────────────
// Settings lives in the top-right avatar menu now (TopBar.tsx), not here —
// every role reaches it the same way, so it doesn't need a per-role entry.

// Owner's GLOBAL-mode nav (outside /events/:id/*): tenant-wide concerns only.
// Event-scoped concerns (Dashboard, Catalog, Inventory, Warehouse, Alerts,
// Predictions, Reports, Charge Bars) moved under /events/:id/* — see
// EventSidebar.tsx. Chat isn't event-scoped (no /events/:id/chat exists),
// so it stays here rather than disappearing from Owner's nav entirely.
const OWNER_GLOBAL_NAV: NavItem[] = [
  { label: 'Events',   path: '/events',   icon: ICONS.calendar },
  { label: 'Products', path: '/products', icon: ICONS.wineGlass },
  { label: 'Bars',     path: '/bars',     icon: ICONS.bell },
  { label: 'Chat',     path: '/chat',     icon: ICONS.messageCircle },
]

function getNavItems(role: MockUser['role']): NavItem[] {
  switch (role) {
    case 'owner':
      return OWNER_GLOBAL_NAV

    case 'manager':
      return [
        { label: 'My Bar',         path: '/dashboard',      icon: ICONS.wineGlass },
        { label: 'Inventory',      path: '/inventory',      icon: ICONS.package },
        { label: 'Scan Arrivals',  path: '/scan/arrivals',  icon: ICONS.scan },
        { label: 'Alerts',         path: '/alerts',         icon: ICONS.bell },
        { label: 'Chat',           path: '/chat',           icon: ICONS.messageCircle },
      ]

    case 'bartender':
      return [
        { label: 'My Bar',        path: '/dashboard',     icon: ICONS.wineGlass },
        { label: 'Scan Empties',  path: '/scan/empties',  icon: ICONS.scan },
        { label: 'Inventory',     path: '/inventory',     icon: ICONS.package },
        { label: 'Chat',          path: '/chat',          icon: ICONS.messageCircle },
      ]

    case 'warehouse':
      return [
        { label: 'Scan Goods', path: '/warehouse', icon: ICONS.scan, exact: true },
      ]
  }
}

// Matches /events/<uuid>(/...) — but NOT /events, /events/create, or
// /events/create-v2 (no UUID segment to match). Only the Owner role has
// an event-scoped sidebar; other roles don't navigate "into" an event.
const EVENT_SCOPED_RE = /^\/events\/([0-9a-f-]{36})(\/|$)/i

// ─── Component ──────────────────────────────────────────────────────

export function Sidebar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const role: MockUser['role'] = user?.role ?? 'owner'
  const navItems = getNavItems(role)

  // Event mode: Owner, browsing inside /events/:id/*. Every other role's
  // nav is unaffected — Manager/Bartender/Warehouse don't "enter" an
  // event, they work off whatever's currently live for their bar.
  const inEventMode = role === 'owner' && EVENT_SCOPED_RE.test(pathname)

  function handleSwitch() {
    logout()
    navigate('/login')
  }

  return (
    <aside className="w-60 bg-[#1E5A8D] text-white flex flex-col flex-shrink-0 shadow-xl">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-white/10">
        <span className="text-xl font-bold tracking-tight">XProject</span>
        <p className="text-blue-200 text-xs mt-0.5">Operations Platform</p>
      </div>

      {/* Nav */}
      {inEventMode ? (
        <EventSidebar />
      ) : (
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => {
            const active = isActive(pathname, item)
            return (
              <Link
                key={item.path + item.label}
                to={item.path}
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
      )}

      {/* Footer: role identity + switch button */}
      {user && (
        <div className="px-4 py-4 border-t border-white/10">
          <div className="flex items-center gap-3">
            {/* Avatar circle */}
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 shadow-sm"
              style={{ backgroundColor: ROLE_AVATAR_COLOR[role] }}
            >
              {ROLE_INITIAL[role]}
            </div>

            {/* Identity info */}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white leading-tight truncate">
                {user?.full_name ?? ROLE_LABEL[role]}
              </p>
              <span
                className={[
                  'inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full border mt-1',
                  ROLE_BADGE[role],
                ].join(' ')}
              >
                {ROLE_LABEL[role]}
              </span>
            </div>

            {/* Sign out — was mislabeled 'Switch user' but only ever logged out */}
            <button
              onClick={handleSwitch}
              title="Sign out"
              aria-label="Sign out"
              className="w-7 h-7 flex items-center justify-center rounded-lg text-blue-300 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}