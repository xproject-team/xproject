/**
 * Regression coverage for the pending-review actor-role badge.
 *
 * Before this fix: ROLE_BADGES was an exhaustive Record indexed directly
 * with the API's scanned_by_role value; a role the frontend doesn't
 * recognise (any future role change) yielded undefined and the page
 * crashed dereferencing .label / .color. The resolver must tolerate
 * unknown roles with fallback rendering instead.
 */
import { describe, expect, it } from 'vitest'

import { resolveRoleBadge } from './roleBadges'

describe('resolveRoleBadge', () => {
  it('resolves the known roles, including retired historical ones', () => {
    expect(resolveRoleBadge('owner').label).toBe('Owner')
    expect(resolveRoleBadge('manager').label).toBe('Manager')
    // Retired roles still appear on historical scans and must keep rendering
    expect(resolveRoleBadge('bartender').label).toBe('Bartender')
    expect(resolveRoleBadge('warehouse_keeper').label).toBe('Warehouse')
  })

  it('falls back for a role it does not recognise instead of crashing', () => {
    const badge = resolveRoleBadge('supervisor')
    expect(badge).toBeDefined()
    expect(badge.label).toBe('supervisor')
    expect(badge.color).toBeTruthy()
  })

  it('tolerates an empty role string', () => {
    const badge = resolveRoleBadge('')
    expect(badge).toBeDefined()
    expect(badge.label).toBeTruthy()
  })
})
