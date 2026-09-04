/**
 * The landing page is evidence, not advertising — and its numbers are
 * governed: every figure must be real, sourced, and cleared for
 * publication. These tests pin the governance, not just the shape.
 */
import { describe, expect, it } from 'vitest'

import { LANDING_FACTS, TECHNICAL_FACTS } from './landingFacts'

describe('landing facts — governed numbers', () => {
  it('every fact is a real positive figure with a precise label and a source', () => {
    expect(LANDING_FACTS.length).toBeGreaterThanOrEqual(4)
    for (const fact of LANDING_FACTS) {
      expect(fact.value).toBeGreaterThan(0)
      expect(Number.isFinite(fact.value)).toBe(true)
      expect(fact.label.length).toBeGreaterThan(3)
      // Sourcing is mandatory: where the number came from and how to
      // re-verify it before any promotion to production.
      expect(fact.source.length).toBeGreaterThan(10)
    }
  })

  it('NO revenue figures until the client clears them — structurally enforced', () => {
    for (const fact of LANDING_FACTS) {
      const text = `${fact.label} ${fact.source}`.toLowerCase()
      expect(fact.label).not.toMatch(/€|eur/i)
      expect(text).not.toMatch(/revenue|fatturato/)
      expect(String(fact.value)).not.toMatch(/187718|18771800/)
    }
  })

  it('the record the headline stands on is present: events and orders', () => {
    const labels = LANDING_FACTS.map((f) => f.label.toLowerCase()).join(' | ')
    expect(labels).toMatch(/event/)
    expect(labels).toMatch(/order/)
  })

  it('the rendered strip is legible to a non-technical reader (staging review, 4 Sep)', () => {
    const labels = LANDING_FACTS.map((f) => f.label.toLowerCase()).join(' | ')
    // Scale of processing, not internal engineering detail:
    expect(labels).toMatch(/stock movement/)
    expect(labels).not.toMatch(/migration/)
    // The migrations figure is KEPT for the technical document — moved,
    // not deleted:
    const technical = TECHNICAL_FACTS.map((f) => f.label.toLowerCase()).join(' | ')
    expect(technical).toMatch(/migration/)
  })

  it('technical facts obey the same governance', () => {
    for (const fact of TECHNICAL_FACTS) {
      expect(fact.value).toBeGreaterThan(0)
      expect(fact.source.length).toBeGreaterThan(10)
      expect(`${fact.label} ${fact.source}`.toLowerCase()).not.toMatch(/revenue|fatturato/)
    }
  })
})
