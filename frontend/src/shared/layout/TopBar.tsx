import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/features/auth/useAuth'
import { usePermissions } from '@/features/auth/usePermissions'
import type { MockUser } from '@/lib/mockUsers'

const ROLE_BADGE: Record<
  MockUser['role'],
  { label: string; bg: string; text: string; border: string }
> = {
  owner:     { label: 'Owner',     bg: 'bg-[#E6FBF6]', text: 'text-[#1ABC9C]', border: 'border-[#1ABC9C]/40' },
  manager:   { label: 'Manager',   bg: 'bg-[#EBF5FB]', text: 'text-[#3498DB]', border: 'border-[#3498DB]/40' },
  warehouse: { label: 'Warehouse', bg: 'bg-[#FEF9E7]', text: 'text-[#D69E2E]', border: 'border-[#D69E2E]/40' },
  bartender: { label: 'Bartender', bg: 'bg-[#FDEDEC]', text: 'text-[#E74C3C]', border: 'border-[#E74C3C]/40' },
}

export function TopBar() {
  const navigate         = useNavigate()
  const { user, logout } = useAuth()
  const perms            = usePermissions()

  const role  = user?.role ?? 'owner'
  const badge = ROLE_BADGE[role]

  function handleSwitch() {
    logout()
    navigate('/login')
  }

  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center px-6 justify-between flex-shrink-0 shadow-sm gap-4">

      {/* Left — event identity */}
      <div className="flex items-center gap-2.5 shrink-0">
        <div className="w-2 h-2 rounded-full bg-[#38A169] animate-pulse" />
        <span className="text-sm font-semibold text-[#1A202C]">XProject</span>
        <span className="text-[#CBD5E0]">·</span>
        <span className="text-sm text-[#4A5568]">Sundance 2026</span>
        <span className="bg-[#38A169]/10 text-[#38A169] text-[10px] font-semibold px-2 py-0.5 rounded-full border border-[#38A169]/20 tracking-wide">
          LIVE
        </span>
      </div>

      {/* Middle — manager: bar name + stock/alerts; bartender: bar name + bottles */}
      {role === 'manager' && user?.assignedBarName && (
        <div className="flex items-center gap-2 text-xs">
          <span className="bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1.5 rounded-full font-semibold text-[#1A202C]">
            {user.assignedBarName}
          </span>
        </div>
      )}

      {role === 'bartender' && (
        <div className="flex items-center gap-2 text-xs">
          {user?.assignedBarName && (
            <span className="bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1.5 rounded-full font-semibold text-[#1A202C]">
              {user.assignedBarName}
            </span>
          )}
          <span className="flex items-center gap-1.5 bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1.5 rounded-full text-[#4A5568]">
            Bottles opened today:
            <span className="font-bold text-[#1A202C]">12</span>
          </span>
        </div>
      )}

      {/* Right — role badge + swap button */}
      <div className="flex items-center gap-2.5 shrink-0">
        {role !== 'owner' && (
          <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${badge.bg} ${badge.text} ${badge.border}`}>
            {badge.label}
          </span>
        )}
        <button
          onClick={handleSwitch}
          title="Switch user"
          className="w-8 h-8 flex items-center justify-center rounded-full border border-[#E2E8F0] text-[#4A5568] hover:text-[#1A202C] hover:border-[#CBD5E0] hover:bg-[#F7FAFC] transition-colors"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
            <circle cx="12" cy="7" r="4" />
            <path d="M18 8l2 2-2 2M20 10h-4" />
          </svg>
        </button>
      </div>

    </header>
  )
}
