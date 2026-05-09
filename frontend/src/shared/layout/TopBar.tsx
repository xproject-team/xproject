import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/features/auth/useAuth'
import type { UserRole } from '@/features/auth/AuthContext'
import { MentionBell } from '@/features/chat/MentionBell'

const ROLE_BADGE: Record<
  UserRole,
  { label: string; bg: string; text: string; border: string; dot: string }
> = {
  owner:     { label: 'Owner',     bg: 'bg-[#E6FBF6]', text: 'text-[#1ABC9C]', border: 'border-[#1ABC9C]/40', dot: '#1E5A8D' },
  manager:   { label: 'Manager',   bg: 'bg-[#EBF5FB]', text: 'text-[#3498DB]', border: 'border-[#3498DB]/40', dot: '#6B21A8' },
  warehouse: { label: 'Warehouse', bg: 'bg-[#FEF9E7]', text: 'text-[#D69E2E]', border: 'border-[#D69E2E]/40', dot: '#DD6B20' },
  bartender: { label: 'Bartender', bg: 'bg-[#FDEDEC]', text: 'text-[#E74C3C]', border: 'border-[#E74C3C]/40', dot: '#059669' },
}

export function TopBar() {
  const navigate         = useNavigate()
  const { user, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  const menuRef    = useRef<HTMLDivElement>(null)
  const buttonRef  = useRef<HTMLButtonElement>(null)
  const firstItem  = useRef<HTMLButtonElement>(null)

  const role        = user?.activeRole ?? user?.role ?? 'owner'
  const badge       = ROLE_BADGE[role]
  const initials    = (user?.full_name ?? user?.email ?? '?')
    .split(/\s+/).map(s => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
  const hasMultipleRoles = (user?.assignedRoles?.length ?? 0) > 1

  useEffect(() => {
    if (!menuOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setMenuOpen(false)
        buttonRef.current?.focus()
      }
    }
    function onClick(e: MouseEvent) {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    requestAnimationFrame(() => firstItem.current?.focus())
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [menuOpen])

  function goProfile() {
    setMenuOpen(false)
    navigate('/settings')
  }

  function goSwitchRole() {
    setMenuOpen(false)
    if (user?.email) {
      try { localStorage.setItem('lastEmail', user.email) } catch { /* quota */ }
    }
    logout()
    navigate('/login')
  }

  function goSignOut() {
    setMenuOpen(false)
    logout()
    navigate('/login')
  }

  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center px-6 justify-between flex-shrink-0 shadow-sm gap-4">

      <div className="flex items-center gap-2.5 shrink-0">
        <div className="w-2 h-2 rounded-full bg-[#38A169] animate-pulse" />
        <span className="text-sm font-semibold text-[#1A202C]">XProject</span>
        <span className="text-[#CBD5E0]">·</span>
        <span className="text-sm text-[#4A5568]">Sundance 2026</span>
        <span className="bg-[#38A169]/10 text-[#38A169] text-[10px] font-semibold px-2 py-0.5 rounded-full border border-[#38A169]/20 tracking-wide">
          LIVE
        </span>
      </div>

      {role === 'bartender' && (
        <div className="flex items-center gap-2 text-xs">
          <span className="flex items-center gap-1.5 bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1.5 rounded-full text-[#4A5568]">
            Bottles opened today:
            <span className="font-bold text-[#1A202C]">12</span>
          </span>
        </div>
      )}

      <div className="flex items-center gap-1.5 shrink-0 relative">
        {role !== 'warehouse' && <MentionBell />}
        {role !== 'owner' && (
          <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${badge.bg} ${badge.text} ${badge.border}`}>
            {badge.label}
          </span>
        )}

        <button
          ref={buttonRef}
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label="Open profile menu"
          title="Profile menu"
          className="w-8 h-8 flex items-center justify-center rounded-full border border-[#E2E8F0] bg-[#F7FAFC] text-[#4A5568] hover:text-[#1A202C] hover:border-[#CBD5E0] hover:bg-[#EDF2F7] focus:outline-none focus:border-[#1E5A8D] transition-colors text-[11px] font-bold"
        >
          {initials}
        </button>

        {menuOpen && (
          <div
            ref={menuRef}
            role="menu"
            className="absolute right-0 top-full mt-2 w-64 bg-white border border-[#E2E8F0] rounded-xl shadow-lg z-50 overflow-hidden"
          >
            <div className="px-4 py-3 bg-[#F7FAFC] border-b border-[#E2E8F0]">
              <div className="text-sm font-semibold text-[#1A202C] truncate">
                {user?.full_name ?? '—'}
              </div>
              <div className="text-xs text-[#718096] truncate">{user?.email}</div>
              <div className="flex items-center gap-1.5 mt-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: badge.dot }} />
                <span className="text-[11px] text-[#4A5568]">Signed in as <span className="font-semibold">{badge.label}</span></span>
              </div>
            </div>

            <div className="py-1.5">
              <button
                ref={firstItem}
                role="menuitem"
                onClick={goProfile}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-[#1A202C] hover:bg-[#F7FAFC] focus:outline-none focus:bg-[#F7FAFC] transition-colors text-left"
              >
                <svg className="w-4 h-4 text-[#718096]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="7" r="4" /><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
                </svg>
                Profile
              </button>

              {hasMultipleRoles && (
                <button
                  role="menuitem"
                  onClick={goSwitchRole}
                  className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-[#1A202C] hover:bg-[#F7FAFC] focus:outline-none focus:bg-[#F7FAFC] transition-colors text-left"
                >
                  <svg className="w-4 h-4 text-[#718096]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 1l4 4-4 4M3 11V9a4 4 0 014-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 01-4 4H3" />
                  </svg>
                  Switch Role
                </button>
              )}
            </div>

            <div className="border-t border-[#E2E8F0] py-1.5">
              <button
                role="menuitem"
                onClick={goSignOut}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-[#E74C3C] hover:bg-[#FDEDEC] focus:outline-none focus:bg-[#FDEDEC] transition-colors text-left"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
                </svg>
                Sign Out
              </button>
            </div>
          </div>
        )}
      </div>

    </header>
  )
}
