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

describe('seasonEventRevenues — the asymmetric staging shape (2 Sep defect)', () => {
  it('version asymmetry across events: all three survive, and the bars are drawn from the SAME population the season tiles sum (latest ready IT per event)', () => {
    // The shape that made the bug visible: e2 carries a higher-version
    // EN row with a different total than its IT row (staging's
    // premature-zero + diverged-EN-regeneration state). Uniform data
    // can never catch this: with IT == EN the two populations agree by
    // coincidence. The selector must key on (event_id, language) and
    // follow the endpoint's convention (IT series), so sum(bars) always
    // equals the season tile — consistent even when the data is wrong.
    const rows = seasonEventRevenues([
      report({ id: 'a', event_id: 'e1', event_name: 'Notte 1',
               language: 'it', version: 1, total_revenue: '18581.00' }),
      report({ id: 'b', event_id: 'e2', event_name: 'Notte 2',
               event_started_at: '2026-07-05T16:00:00Z',
               language: 'it', version: 1, total_revenue: '0.00' }),
      report({ id: 'c', event_id: 'e2', event_name: 'Notte 2',
               event_started_at: '2026-07-05T16:00:00Z',
               language: 'en', version: 2, total_revenue: '18240.00' }),
      report({ id: 'd', event_id: 'e3', event_name: 'Notte 3',
               event_started_at: '2026-07-19T16:00:00Z',
               language: 'it', version: 1, total_revenue: '0.00' }),
    ] as never)
    // All three events survive the version asymmetry…
    expect(rows.map((r) => r.eventId)).toEqual(['e1', 'e2', 'e3'])
    // …and every value comes from the IT series — e2 must show its IT
    // figure, NOT the higher-version EN row, so the bars can never
    // disagree with the endpoint's season total.
    expect(rows.map((r) => r.revenue)).toEqual([18581, 0, 0])
  })

  it('within one language, the latest ready version still wins', () => {
    const rows = seasonEventRevenues([
      report({ id: 'a', event_id: 'e1', language: 'it', version: 1,
               total_revenue: '100.00' }),
      report({ id: 'b', event_id: 'e1', language: 'it', version: 3,
               total_revenue: '54017.00' }),
      report({ id: 'c', event_id: 'e1', language: 'it', version: 2,
               total_revenue: '999.00' }),
    ] as never)
    expect(rows).toEqual([
      { eventId: 'e1', name: 'Night One', date: '2026-06-14T16:00:00Z', revenue: 54017 },
    ])
  })
})
