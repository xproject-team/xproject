/**
 * Token storage, decode, and refresh utilities.
 * Uses localStorage for persistence. Import into api.ts interceptors only.
 */
const TOKEN_KEY = 'xproject_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function decodeToken(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload))
  } catch {
    return null
  }
}

export async function refreshToken(): Promise<boolean> {
  // TODO: implement silent token refresh via /api/v1/auth/refresh
  return false
}
