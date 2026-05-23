/**
 * TanStack Query hooks for the auth module.
 *
 * Current scope:
 *   useChangePassword() — POST /auth/change-password
 *
 * The legacy login + /me hooks remain in useAuth.ts (context-based)
 * for backward compatibility.  New mutations land here.
 */
import { useMutation } from '@tanstack/react-query'
import { AxiosError } from 'axios'

import { api } from '@/lib/api'

export interface ChangePasswordPayload {
  old_password: string
  new_password: string
}

export interface ChangePasswordError {
  status: number
  detail: string
}

/**
 * Change the current user's password.
 *
 * Backend returns:
 *   204 — success (no body)
 *   401 — old password incorrect
 *   400 — new password too short OR same as old
 *
 * The hook normalizes axios errors into { status, detail } so the form
 * can map errors to specific fields without parsing axios internals.
 */
export function useChangePassword() {
  return useMutation<void, ChangePasswordError, ChangePasswordPayload>({
    mutationFn: async (payload: ChangePasswordPayload): Promise<void> => {
      try {
        await api.post('/auth/change-password', payload)
      } catch (err) {
        const ax = err as AxiosError<{ detail?: string }>
        throw {
          status: ax.response?.status ?? 0,
          detail: ax.response?.data?.detail ?? ax.message ?? 'Unknown error',
        } as ChangePasswordError
      }
    },
  })
}
