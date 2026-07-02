/**
 * EventLayout — layout route wrapping every /events/:id/* page
 * (Phase 1 of the event-scoped restructure).
 *
 * Responsibilities:
 *   - Read :id from the URL, fetch the event via useFullEvent
 *   - Loading   → skeleton
 *   - Not found / error → redirect to /events
 *   - Provide EventContext (useEvent()) to every nested route
 *   - Render the event top bar: "← Back to events · {name} · <status>"
 *
 * Does NOT render its own sidebar. Sidebar.tsx (mounted once by
 * AppShell for the whole app) switches to the event-scoped nav
 * (EventSidebar) whenever the current route matches /events/:id/*
 * for the Owner role. Two separate sidebar implementations racing to
 * render the left rail would be worse than one component owning that
 * decision everywhere.
 */
import { Link, Navigate, Outlet, useParams } from 'react-router-dom'

import { useFullEvent } from '@/features/events/useFullEvent'
import { EventProvider, buildEventContextValue } from '@/features/events/EventContext'

const STATUS_BADGE: Record<string, string> = {
  draft:     'bg-gray-100 text-[#718096] border border-gray-200',
  active:    'bg-blue-100 text-[#3498DB] border border-blue-200',
  live:      'bg-green-100 text-[#38A169] border border-green-200',
  completed: 'bg-[#F7FAFC] text-[#4A5568] border border-[#E2E8F0]',
}

export function EventLayout() {
  const { id } = useParams<{ id: string }>()
  const fullEventQuery = useFullEvent(id ?? null)

  if (fullEventQuery.isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="animate-pulse space-y-3">
          <div className="h-5 w-64 bg-[#E2E8F0] rounded" />
          <div className="h-4 w-96 bg-[#E2E8F0] rounded" />
          <div className="h-24 w-full bg-[#E2E8F0] rounded mt-6" />
        </div>
      </div>
    )
  }

  // Bad/unknown id, or the fetch failed outright — send the user back
  // to the event picker rather than showing a broken shell.
  if (fullEventQuery.isError || !fullEventQuery.data) {
    return <Navigate to="/events" replace />
  }

  const value = buildEventContextValue(fullEventQuery.data)

  return (
    <EventProvider value={value}>
      <div className="flex flex-col h-full">
        <div className="h-12 bg-white border-b border-[#E2E8F0] flex items-center px-6 gap-3 flex-shrink-0">
          <Link
            to="/events"
            className="text-sm text-[#718096] hover:text-[#1E5A8D] transition-colors shrink-0"
          >
            ← Back to events
          </Link>
          <span className="text-[#CBD5E0]">·</span>
          <span className="text-sm font-semibold text-[#1A202C] truncate">
            {value.name}
          </span>
          <span
            className={`text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 ${
              STATUS_BADGE[value.status] ?? STATUS_BADGE.draft
            }`}
          >
            {value.status.toUpperCase()}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </EventProvider>
  )
}
