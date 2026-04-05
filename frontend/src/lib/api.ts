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

// On 401, attempt token refresh once, then redirect to /login
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401) {
      const refreshed = await refreshToken()
      if (!refreshed) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)
