/**
 * Bell icon shown in the TopBar. Click → dropdown of recent mentions.
 * Red badge shows unread count. Clicking a mention marks it read +
 * navigates to its channel.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useMarkMentionRead, useMentions, type MentionResponse } from './useMentions'


export function MentionBell() {
  const [open, setOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()

  const { data: mentions = [] } = useMentions(false, 20)
  const markRead = useMarkMentionRead()

  const unreadCount = mentions.filter((m) => m.read_at === null).length

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  function handleMentionClick(m: MentionResponse) {
    if (m.read_at === null) {
      markRead.mutate(m.id)
    }
    setOpen(false)
    navigate('/chat')
  }

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Bell button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 rounded-full hover:bg-[#F0F4F8] transition-colors"
        aria-label="Notifications"
      >
        <svg className="w-5 h-5 text-[#4A5568]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 bg-[#E74C3C] text-white text-[10px] font-bold rounded-full flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute right-0 mt-2 w-80 rounded-xl shadow-xl overflow-hidden z-50"
          style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
        >
          <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
            <h3 className="font-semibold text-sm" style={{ color: 'var(--v-text)' }}>Mentions</h3>
            {unreadCount > 0 && (
              <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>{unreadCount} unread</span>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {mentions.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: 'var(--v-text-dim)' }}>
                No mentions yet. You'll see them here when someone @-mentions you.
              </div>
            ) : (
              mentions.map((m) => (
                <button
                  key={m.id}
                  onClick={() => handleMentionClick(m)}
                  className="w-full text-left px-4 py-3 transition-colors hover:bg-white/[0.05]"
                  style={{
                    borderBottom: '0.5px solid var(--v-border)',
                    background: m.read_at === null ? 'rgba(0, 229, 212, 0.07)' : undefined,
                  }}
                >
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <span className="text-xs font-semibold" style={{ color: 'var(--v-text)' }}>
                      {m.sender_name ?? '(deleted user)'}
                    </span>
                    <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--v-text-dim)' }}>
                      {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <div className="text-[11px] mb-1" style={{ color: 'var(--v-text-muted)' }}>in #{m.channel_name}</div>
                  <div className="text-xs line-clamp-2" style={{ color: 'var(--v-text)' }}>{m.body}</div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
