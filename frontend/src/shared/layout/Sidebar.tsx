import { Link, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { label: 'Dashboard',   path: '/dashboard',   icon: '▦' },
  { label: 'Events',      path: '/events',       icon: '◈' },
  { label: 'Inventory',   path: '/inventory',    icon: '▤' },
  { label: 'Alerts',      path: '/alerts',       icon: '◉' },
  { label: 'Warehouse',   path: '/warehouse',    icon: '▣' },
  { label: 'Predictions', path: '/predictions',  icon: '▲' },
  { label: 'Reports',     path: '/reports',      icon: '▥' },
]

export function Sidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="w-60 bg-[#1E5A8D] text-white flex flex-col flex-shrink-0 shadow-xl">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-white/10">
        <span className="text-xl font-bold tracking-tight">XProject</span>
        <p className="text-blue-200 text-xs mt-0.5">Operations Platform</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.path || pathname.startsWith(item.path + '/')
          return (
            <Link
              key={item.path}
              to={item.path}
              className={
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ' +
                (active
                  ? 'bg-[#6C63FF] text-white shadow-sm'
                  : 'text-blue-100 hover:bg-white/10 hover:text-white')
              }
            >
              <span className="text-base leading-none w-5 text-center">{item.icon}</span>
              {item.label}
            </Link>
          )
        })}
      </nav>

      {/* User footer */}
      <div className="px-6 py-4 border-t border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[#6C63FF] flex items-center justify-center text-sm font-bold flex-shrink-0">
            O
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-white">Omar (Owner)</p>
            <p className="text-xs text-blue-200">Full access</p>
          </div>
        </div>
      </div>
    </aside>
  )
}
