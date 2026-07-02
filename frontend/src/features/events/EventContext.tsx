/**
 * EventContext — the shared "which event am I in" context for
 * /events/:id/* pages (Phase 1 of the event-scoped restructure).
 *
 * Provided by EventLayout (src/app/EventLayout.tsx), consumed via
 * useEvent(). Wraps useFullEvent() so any page under an event route
 * can read event basics + derived status booleans without
 * re-fetching or re-deriving them itself.
 *
 * Phase 1 scope: this context exists and is available, but no page
 * consumes it yet — every page still resolves its own event via
 * useLiveEvent() (or its own props) exactly as before. Phase 3
 * migrates pages to read from here instead and removes the parallel
 * guessing logic.
 */
import { createContext, useContext, type ReactNode } from 'react'

import type { FullEventDetail } from './useFullEvent'

export interface EventContextValue {
  id: string
  name: string
  status: string
  isDraft: boolean
  isLive: boolean
  isCompleted: boolean
  /** True once the event has left DRAFT and finished — mirrors the
   *  backend's "recipes/charges are locked" convention used
   *  elsewhere (see event_recipes service). */
  isReadOnly: boolean
  fullEvent: FullEventDetail
}

const EventContext = createContext<EventContextValue | null>(null)

export function EventProvider({
  value,
  children,
}: {
  value: EventContextValue
  children: ReactNode
}) {
  return <EventContext.Provider value={value}>{children}</EventContext.Provider>
}

/**
 * Read the current event from context. Throws if called outside an
 * /events/:id/* route — every consumer is expected to be mounted
 * under EventLayout, so a thrown error here means a real bug (a
 * component rendered in the wrong place), not a case to handle
 * gracefully with a fallback.
 */
export function useEvent(): EventContextValue {
  const ctx = useContext(EventContext)
  if (ctx === null) {
    throw new Error(
      'useEvent() called outside an EventProvider — this component must be ' +
        'mounted under /events/:id/* (inside EventLayout).',
    )
  }
  return ctx
}

/**
 * Build the EventContextValue from a FullEventDetail response.
 * Exported so EventLayout (the sole producer) doesn't duplicate the
 * derived-boolean logic, and so it stays testable in isolation.
 */
export function buildEventContextValue(fullEvent: FullEventDetail): EventContextValue {
  const status = fullEvent.event.status
  return {
    id: fullEvent.event.id,
    name: fullEvent.event.name,
    status,
    isDraft: status === 'draft',
    isLive: status === 'live',
    isCompleted: status === 'completed',
    isReadOnly: status === 'completed',
    fullEvent,
  }
}
