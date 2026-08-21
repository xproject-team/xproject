/**
 * Deterministic categorical color mapping for stacked/multi-series charts.
 *
 * Given a category key (a product id, a bucket name, anything used as a
 * chart series identifier), colorForCategory always returns the same
 * palette slot for the same key — on every chart, every render — so the
 * same drink keeps the same color whether it's the top seller at one bar
 * (and thus first in a revenue-ranked stack) or a minor seller at another.
 * Rank-based color assignment (index into whatever subset is visible on
 * THIS chart) can't guarantee that; a pure hash of the key can.
 */

export const CATEGORICAL_PALETTE = [
  'var(--v-cat-1)',
  'var(--v-cat-2)',
  'var(--v-cat-3)',
  'var(--v-cat-4)',
  'var(--v-cat-5)',
  'var(--v-cat-6)',
  'var(--v-cat-7)',
  'var(--v-cat-8)',
] as const

export function colorForCategory(key: string): string {
  let hash = 0
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0
  }
  const index = Math.abs(hash) % CATEGORICAL_PALETTE.length
  return CATEGORICAL_PALETTE[index]
}
