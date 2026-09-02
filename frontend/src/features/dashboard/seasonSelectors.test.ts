/**
 * Idle-dashboard season view — the three states, tested at the logic
 * layer (the vitest environment is node-only; rendering is verified by
 * tsc + the production build, as on every converted page):
 *
 *   1. idle with history  → season rows derived from real report data
 *   2. idle, no history   → 'first-run' (a beginning, never an error)
 *   3. live event running → the idle view is never entered (the
 *      existing eventId branch decides; pickNextEvent additionally
 *      never offers a live event as "next")
 *
 * Real data only: every selector returns what the API actually said,
 * or nothing — no placeholder values exist anywhere in this layer.
 */
import { describe, expect, it } from 'vitest'

import {
  pickNextEvent,
  seasonEventRevenues,
  seasonIdleState,
} from './seasonSelectors'

const NOW = new Date('2026-09-02T12:00:00Z')

const event = (over: Record<string, unknown>) => ({
  id: 'e1', name: 'Event', status: 'draft', scheduled_at: '2026-09-10T16:00:00Z',
  ...over,
})

const report = (over: Record<string, unknown>) => ({
  id: 'r1', event_id: 'e1', event_name: 'Night One',
  event_started_at: '2026-06-14T16:00:00Z', event_ended_at: '2026-06-15T02:00:00Z',
  version: 1, status: 'ready', language: 'it', generated_at: '2026-06-15T03:00:00Z',
  total_revenue: '54017.00', alerts_count: 0, top_bar_name: null,
  ...over,
})

describe('seasonIdleState — the three dashboard states', () => {
  it('is loading until the KPI response exists', () => {
    expect(seasonIdleState(undefined)).toBe('loading')
  })
  it('no completed events → first-run, a beginning not an absence', () => {
    expect(seasonIdleState({ total_events_completed: 0 } as never)).toBe('first-run')
  })
  it('history present → the season view', () => {
    expect(seasonIdleState({ total_events_completed: 4 } as never)).toBe('season')
  })
})

describe('seasonEventRevenues', () => {
  it('one row per event: latest READY version, one language, date-ordered', () => {
    const rows = seasonEventRevenues([
      report({ id: 'a', event_id: 'e1', language: 'it', version: 1 }),
      report({ id: 'b', event_id: 'e1', language: 'en', version: 1 }),   // sibling: same numbers
      report({ id: 'c', event_id: 'e1', language: 'it', version: 2,      // superseded winner
               total_revenue: '54017.00' }),
      report({ id: 'd', event_id: 'e2', event_name: 'Night Two',
               event_started_at: '2026-07-05T16:00:00Z', total_revenue: '50760.00' }),
      report({ id: 'e', event_id: 'e3', event_name: 'Broken',
               status: 'failed', total_revenue: null }),                 // never counted
    ] as never)
    expect(rows).toEqual([
      { eventId: 'e1', name: 'Night One', date: '2026-06-14T16:00:00Z', revenue: 54017 },
      { eventId: 'e2', name: 'Night Two', date: '2026-07-05T16:00:00Z', revenue: 50760 },
    ])
  })
  it('no reports → empty, no invented rows', () => {
    expect(seasonEventRevenues([])).toEqual([])
  })
})

describe('pickNextEvent', () => {
  it('earliest FUTURE draft/active event wins', () => {
    const next = pickNextEvent([
      event({ id: 'past', scheduled_at: '2026-08-01T16:00:00Z' }),
      event({ id: 'later', status: 'active', scheduled_at: '2026-09-20T16:00:00Z' }),
      event({ id: 'sooner', scheduled_at: '2026-09-05T16:00:00Z' }),
    ] as never, NOW)
    expect(next?.id).toBe('sooner')
  })
  it('live and completed events are never "next"; none scheduled → null', () => {
    expect(pickNextEvent([
      event({ status: 'live', scheduled_at: '2026-09-10T16:00:00Z' }),
      event({ status: 'completed', scheduled_at: '2026-09-10T16:00:00Z' }),
      event({ scheduled_at: '2026-01-01T16:00:00Z' }),
    ] as never, NOW)).toBeNull()
    expect(pickNextEvent([], NOW)).toBeNull()
  })
})
