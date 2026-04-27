/**
 * Axios instance with base URL and auth interceptor.
 * All feature hooks must import { api } from here — never create axios instances elsewhere.
 */
import axios from 'axios'
import { getToken, refreshToken } from './auth'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT to every request
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401, attempt token refresh once, then redirect to /login.
//
// CRITICAL: skip the auto-redirect when the FAILING request was itself a
// /auth/login call. Otherwise wrong-password failures cause a full page
// reload mid-handler, which wipes the form's error state — the user sees
// the error flash for <1s before the reload kills it. Login form code
// owns its own 401 handling (it shows the inline 'Incorrect email or
// password' banner). The interceptor only needs to handle session
// expiration during real app use.
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status !== 401) {
      return Promise.reject(error)
    }
    // Identify the request URL. axios stores it on error.config.url.
    const url: string = error.config?.url ?? ''
    const isLoginRequest = url.includes('/auth/login')
    if (isLoginRequest) {
      // Bad credentials. Let the caller (LoginForm) handle the error.
      return Promise.reject(error)
    }
    // Real session-expired path: try refresh once, then bounce to login.
    const refreshed = await refreshToken()
    if (!refreshed) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)
