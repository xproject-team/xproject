/**
 * XSS regression coverage for chat search highlighting.
 *
 * The old implementation returned an HTML string (raw message body with
 * <mark> wrappers) that ChatSearchPanel rendered via
 * dangerouslySetInnerHTML — so a message body containing markup executed
 * as markup. The segment API returns plain text spans that React escapes;
 * these tests pin down that message content is never interpreted as HTML.
 */
import { describe, expect, it } from 'vitest'

import { highlightSegments } from './useChatSearch'

const XSS_BODY = 'restock now <img src=x onerror=alert(document.cookie)> please'

describe('highlightSegments', () => {
  it('returns the malicious body verbatim as inert text segments', () => {
    const segments = highlightSegments(XSS_BODY, 'restock')
    // Round-trip: joined segments reproduce the body EXACTLY — nothing is
    // stripped, nothing is added, and nothing is markup (segments carry no
    // HTML, only {text, match} pairs that React renders as text nodes).
    expect(segments.map((s) => s.text).join('')).toBe(XSS_BODY)
    for (const s of segments) {
      expect(typeof s.text).toBe('string')
      expect(Object.keys(s).sort()).toEqual(['match', 'text'])
    }
  })

  it('marks only the query terms, case-insensitively', () => {
    const segments = highlightSegments('Vodka is out. vodka!', 'vodka')
    const matched = segments.filter((s) => s.match).map((s) => s.text)
    expect(matched).toEqual(['Vodka', 'vodka'])
  })

  it('a query that IS an HTML payload matches as text, never as markup', () => {
    const segments = highlightSegments(XSS_BODY, '<img')
    expect(segments.map((s) => s.text).join('')).toBe(XSS_BODY)
    expect(segments.some((s) => s.match && s.text === '<img')).toBe(true)
  })

  it('empty query returns the whole body unhighlighted', () => {
    expect(highlightSegments(XSS_BODY, '  ')).toEqual([{ text: XSS_BODY, match: false }])
  })
})
