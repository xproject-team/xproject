import { Link, useLocation, useNavigate } from 'react-router-dom'
import { type ReactNode } from 'react'
import { useAuth } from '@/features/auth/useAuth'
import type { MockUser } from '@/lib/mockUsers'
import '@/design-system/components/components.css'

// ─── Role presentation ────────────────────────────────────────────────────────
// Two-role model. Lookups fall back rather than assuming the role string is
// one of ours — a stale token can still carry a retired role at runtime.

const ROLE_LABEL: Record<MockUser['role'], string> = {
  owner:   'Owner',
  manager: 'Manager',
}

const ROLE_AVATAR_COLOR: Record<MockUser['role'], string> = {
  owner:   '#1ABC9C',
  manager: '#3498DB',
}

const ROLE_BADGE: Record<MockUser['role'], string> = {
  owner:   'bg-[#E6FBF6] text-[#1ABC9C] border-[#1ABC9C]/40',
  manager: 'bg-[#EBF5FB] text-[#3498DB] border-[#3498DB]/40',
}

const ROLE_INITIAL: Record<MockUser['role'], string> = {
  owner: 'O', manager: 'M',
}

function roleLabel(role: string): string {
  return (ROLE_LABEL as Record<string, string>)[role] ?? role
}

// ─── SVG icon helper ──────────────────────────────────────────────────────────

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

const ICONS = {
  grid: (
    <Icon>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </Icon>
  ),
  calendar: (
    <Icon>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </Icon>
  ),
  package: (
    <Icon>
      <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
      <path d="M3.27 6.96L12 12l8.73-5.04M12 22V12" />
    </Icon>
  ),
  bell: (
    <Icon>
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </Icon>
  ),
  warehouse: (
    <Icon>
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
      <polyline points="9,22 9,12 15,12 15,22" />
    </Icon>
  ),
  trendingUp: (
    <Icon>
      <polyline points="23,6 13.5,15.5 8.5,10.5 1,18" />
      <polyline points="17,6 23,6 23,12" />
    </Icon>
  ),
  gear: (
    <Icon>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
    </Icon>
  ),
  fileText: (
    <Icon>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14,2 14,8 20,8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <line x1="10" y1="9" x2="8" y2="9" />
    </Icon>
  ),
  wineGlass: (
    <Icon>
      <path d="M8 22h8M12 11v11" />
      <path d="M6 2l1.5 7h9L18 2H6z" />
      <path d="M7.5 9a4.5 4.5 0 009 0" />
    </Icon>
  ),
  scan: (
    <Icon>
      <path d="M3 7V5a2 2 0 012-2h2M17 3h2a2 2 0 012 2v2M21 17v2a2 2 0 01-2 2h-2M7 21H5a2 2 0 01-2-2v-2" />
      <line x1="8" y1="12" x2="16" y2="12" />
      <line x1="12" y1="8" x2="12" y2="16" />
    </Icon>
  ),
  messageCircle: (
    <Icon>
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </Icon>
  ),
  clipboardList: (
    <Icon>
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <line x1="9" y1="12" x2="15" y2="12" />
      <line x1="9" y1="16" x2="13" y2="16" />
    </Icon>
  ),
  swap: (
    <Icon>
      <path d="M8 7h12m0 0l-4-4m4 4l-4 4M16 17H4m0 0l4 4m-4-4l4-4" />
    </Icon>
  ),
}

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

function getNavItems(role: MockUser['role']): NavItem[] {
  switch (role) {
    case 'owner':
      return [
        { label: 'Dashboard',   path: '/dashboard',   icon: ICONS.grid },
        { label: 'Events',      path: '/events',       icon: ICONS.calendar },
        { label: 'Bars',       path: '/bars',         icon: ICONS.bell },
        { label: 'Catalog',    path: '/catalog',      icon: ICONS.bell },
        { label: 'Inventory',   path: '/inventory',    icon: ICONS.package },
        { label: 'Alerts',      path: '/alerts',       icon: ICONS.bell },
        { label: 'Warehouse',   path: '/warehouse',    icon: ICONS.warehouse },
        { label: 'Predictions', path: '/predictions',  icon: ICONS.trendingUp },
        { label: 'Reports',     path: '/reports',      icon: ICONS.fileText },
        { label: 'Chat',        path: '/chat',         icon: ICONS.messageCircle },
        { label: 'Settings',    path: '/settings',     icon: ICONS.gear },
      ]

    case 'manager':
      // Scan Empties (CONSUMED) and Warehouse were absorbed from the
      // retired Bartender / Warehouse roles in the two-role model.
      return [
        { label: 'My Bar',         path: '/dashboard',      icon: ICONS.wineGlass },
        { label: 'Inventory',      path: '/inventory',      icon: ICONS.package },
        { label: 'Scan Arrivals',  path: '/scan/arrivals',  icon: ICONS.scan },
        { label: 'Scan Empties',   path: '/scan/empties',   icon: ICONS.scan },
        { label: 'Warehouse',      path: '/warehouse',      icon: ICONS.warehouse },
        { label: 'Alerts',         path: '/alerts',         icon: ICONS.bell },
        { label: 'Chat',           path: '/chat',           icon: ICONS.messageCircle },
        { label: 'Settings',       path: '/settings',       icon: ICONS.gear },
      ]

    default:
      // Unknown/retired role at runtime (stale token): degrade to a
      // minimal nav instead of crashing on an undefined item list.
      return [
        { label: 'Settings', path: '/settings', icon: ICONS.gear },
      ]
  }
}

// ─── Component ──────────────────────────────────────────────────────

export function Sidebar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const role: MockUser['role'] = user?.role ?? 'owner'
  const navItems = getNavItems(role)

  function handleSwitch() {
    logout()
    navigate('/login')
  }

  return (
    <aside className="v-glass w-60 text-[var(--v-text)] flex flex-col flex-shrink-0 relative z-10">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-white/10">
        <span className="text-xl font-bold tracking-tight text-[var(--v-text)]">Vera Event</span>
        <p className="text-[10px] tracking-[0.14em] mt-0.5 text-[var(--v-cyan)]">LIVE OPS</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const active = isActive(pathname, item)
          return (
            <Link
              key={item.path + item.label}
              to={item.path}
              className={[
                'flex items-center gap-3 px-3 py-2.5 rounded-[var(--v-radius-sm)] text-sm font-medium transition-all border-l-2',
                active
                  ? 'text-[var(--v-cyan)] bg-[rgba(0,229,212,0.12)] border-l-[var(--v-cyan)]'
                  : 'text-[var(--v-text-muted)] hover:text-[var(--v-text)] hover:bg-white/[0.04] border-l-transparent',
              ].join(' ')}
            >
              {item.icon}
              <span className="truncate">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer: role identity + switch button */}
      {user && (
        <div className="px-4 py-4 border-t border-white/10">
          <div className="flex items-center gap-3">
            {/* Avatar circle */}
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 shadow-sm"
              style={{ backgroundColor: ROLE_AVATAR_COLOR[role] ?? '#4A5568' }}
            >
              {ROLE_INITIAL[role] ?? '?'}
            </div>

            {/* Identity info */}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-[var(--v-text)] leading-tight truncate">
                {user?.full_name ?? roleLabel(role)}
              </p>
              <span
                className={[
                  'inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full border mt-1',
                  ROLE_BADGE[role] ?? 'bg-white/[0.06] text-[var(--v-text-muted)] border-white/20',
                ].join(' ')}
              >
                {roleLabel(role)}
              </span>
            </div>

            {/* Sign out — was mislabeled 'Switch user' but only ever logged out */}
            <button
              onClick={handleSwitch}
              title="Sign out"
              aria-label="Sign out"
              className="w-7 h-7 flex items-center justify-center rounded-lg text-[var(--v-text-dim)] hover:text-[var(--v-text)] hover:bg-white/[0.04] transition-colors shrink-0"
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
