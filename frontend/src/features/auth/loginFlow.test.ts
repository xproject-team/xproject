/**
 * Sign-in flow logic — the three steps and every error state, tested at
 * the logic layer (node-only vitest; rendering is verified by tsc + the
 * production build, per the standing constraint).
 *
 * These functions are mechanical EXTRACTIONS from LoginForm — the
 * restyle ruling: markup may change, behaviour may not. The tests pin
 * the behaviour so the restyle provably cannot have changed it.
 */
import { describe, expect, it } from 'vitest'

import {
  loginErrorMessage,
  loginStepBack,
  ROLE_DESCRIPTION,
  ROLE_LABEL,
  ROLE_LANDING,
} from './LoginForm'

describe('loginErrorMessage — every error state, exact user-facing strings', () => {
  it('401 → wrong credentials', () => {
    expect(loginErrorMessage({ response: { status: 401 } }))
      .toBe('Incorrect email or password.')
  })
  it('403 → unauthorised role', () => {
    expect(loginErrorMessage({ response: { status: 403 } }))
      .toBe('You are not authorized for this role.')
  })
  it('string detail from the backend passes through verbatim', () => {
    expect(loginErrorMessage({
      response: { status: 422, data: { detail: 'Unknown role: "bartender"' } },
    })).toBe('Unknown role: "bartender"')
  })
  it('request sent, no response → network failure', () => {
    expect(loginErrorMessage({ request: {} }))
      .toBe("Can't reach the server. Check your connection.")
  })
  it('anything else → generic fallback, never a raw error object', () => {
    expect(loginErrorMessage(new Error('boom')))
      .toBe('Sign in failed. Please try again.')
    expect(loginErrorMessage(undefined))
      .toBe('Sign in failed. Please try again.')
  })
})

describe('loginStepBack — the three-step machine, backwards', () => {
  it('password → role → email; email is the floor', () => {
    expect(loginStepBack('password')).toBe('role')
    expect(loginStepBack('role')).toBe('email')
    expect(loginStepBack('email')).toBe('email')
  })
})

describe('role metadata — copy and destinations pinned through the restyle', () => {
  it('labels and descriptions', () => {
    expect(ROLE_LABEL).toEqual({ owner: 'Owner', manager: 'Manager' })
    expect(ROLE_DESCRIPTION.owner).toMatch(/full operational control/i)
    expect(ROLE_DESCRIPTION.manager).toMatch(/one bar/i)
  })
  it('both roles land on the dashboard', () => {
    expect(ROLE_LANDING).toEqual({ owner: '/dashboard', manager: '/dashboard' })
  })
})
