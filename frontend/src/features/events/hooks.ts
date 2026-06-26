/**
 * TanStack Query hooks for the Events API.
 *
 * D1: Hierarchical query keys.
 * D2: Wait-for-server (no optimistic updates).
 * D3: Typed error envelope matching backend contract §7.3.
 * D4: No localStorage — backend is single source of truth.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
} from '@tanstack/react-query'
import { AxiosError } from 'axios'

import { api } from '@/lib/api'
import type {
  Event,
  EventCreatePayload,
  EventUpdatePayload,
} from '@/lib/mockData'
import type { ParsedEventPlan } from '@/lib/eventPlan'

export const eventKeys = {
  all:    ['events'] as const,
  list:   () => [...eventKeys.all] as const,
  detail: (id: string) => [...eventKeys.all, id] as const,
} as const

export type ApiErrorDetail =
  | { error: 'stale_version';        message: string; current_version: number }
  | { error: 'event_already_live';   message: string; conflicting_event: { id: string; name: string } }
  | { error: 'field_locked';         message: string; field: string; status: string }
  | { error: 'invalid_transition';   message: string; from_status: string; to_status: string }
  | { error: 'event_not_found';      message: string }
  | { error: 'venue_not_found';      message: string }
  | { error: string;                 message: string }

export function getApiError(error: unknown): ApiErrorDetail | null {
  if (error instanceof AxiosError && error.response?.data?.detail) {
    const detail = error.response.data.detail
    if (typeof detail === 'object' && !Array.isArray(detail) && 'error' in detail) {
      return detail as ApiErrorDetail
    }
  }
  return null
}

export function useEvents() {
  return useQuery({
    queryKey: eventKeys.list(),
    queryFn:  async (): Promise<Event[]> => {
      const res = await api.get<Event[]>('/events')
      return res.data
    },
  })
}

export function useEvent(id: string | undefined) {
  return useQuery({
    queryKey: id ? eventKeys.detail(id) : eventKeys.all,
    queryFn:  async (): Promise<Event> => {
      const res = await api.get<Event>(`/events/${id}`)
      return res.data
    },
    enabled: Boolean(id),
  })
}

function useInvalidateEventOnSuccess() {
  const qc = useQueryClient()
  return (eventId?: string) => {
    qc.invalidateQueries({ queryKey: eventKeys.list() })
    if (eventId) qc.invalidateQueries({ queryKey: eventKeys.detail(eventId) })
  }
}

export function useCreateEvent(
  options?: UseMutationOptions<Event, AxiosError, EventCreatePayload>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async (payload: EventCreatePayload): Promise<Event> => {
      const res = await api.post<Event>('/events', payload)
      return res.data
    },
    onSuccess: (event, ...rest) => {
      invalidate(event.id)
      options?.onSuccess?.(event, ...rest)
    },
    ...options,
  })
}

export function useUpdateEvent(
  options?: UseMutationOptions<Event, AxiosError, { id: string; payload: EventUpdatePayload }>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async ({ id, payload }): Promise<Event> => {
      const res = await api.patch<Event>(`/events/${id}`, payload)
      return res.data
    },
    onSuccess: (event, ...rest) => {
      invalidate(event.id)
      options?.onSuccess?.(event, ...rest)
    },
    ...options,
  })
}

export function useDeleteEvent(
  options?: UseMutationOptions<void, AxiosError, string>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(`/events/${id}`)
    },
    onSuccess: (_, id, ...rest) => {
      invalidate(id)
      options?.onSuccess?.(_, id, ...rest)
    },
    ...options,
  })
}

export function useActivateEvent(
  options?: UseMutationOptions<Event, AxiosError, string>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async (id: string): Promise<Event> => {
      const res = await api.post<Event>(`/events/${id}/activate`)
      return res.data
    },
    onSuccess: (event, ...rest) => {
      invalidate(event.id)
      options?.onSuccess?.(event, ...rest)
    },
    ...options,
  })
}

export function useStartEvent(
  options?: UseMutationOptions<Event, AxiosError, string>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async (id: string): Promise<Event> => {
      const res = await api.post<Event>(`/events/${id}/start`)
      return res.data
    },
    onSuccess: (event, ...rest) => {
      invalidate(event.id)
      invalidate()
      options?.onSuccess?.(event, ...rest)
    },
    ...options,
  })
}

export function useEndEvent(
  options?: UseMutationOptions<Event, AxiosError, string>,
) {
  const invalidate = useInvalidateEventOnSuccess()
  return useMutation({
    mutationFn: async (id: string): Promise<Event> => {
      const res = await api.post<Event>(`/events/${id}/end`)
      return res.data
    },
    onSuccess: (event, ...rest) => {
      invalidate(event.id)
      options?.onSuccess?.(event, ...rest)
    },
    ...options,
  })
}
// ─── Phase 4 (Jun 21 2026): Excel plan import ────────────────────────────────
// Mutation hook that uploads a Slesh project-plan .xlsx to the backend's
// /events/import-plan endpoint. Returns the parsed structure for the
// Create Event wizard's Step 2 (Upload) to render as an editable preview.
//
// The endpoint NEVER writes to the database — it only parses the file
// and returns ParsedEventPlan as JSON. The wizard's finalize step is
// what eventually persists the confirmed data atomically.

/** Maps an axios error onto a user-friendly STRING. FastAPI's `detail`
 *  may be a string (for HTTPException) OR an array of Pydantic validation
 *  errors (for 422). We collapse it down to a single string so the UI can
 *  safely render it inside a <p>. */
function importPlanErrorMessage(status: number | undefined, detail: unknown): string {
  if (status === 413) return 'File is too large. Maximum size is 2 MB.'
  if (status === 401) return 'Your session expired. Please sign in again.'
  if (status === 403) return 'You do not have permission to import event plans.'

  // Pull a string out of detail safely
  let detailStr: string | null = null
  if (typeof detail === 'string') {
    detailStr = detail
  } else if (Array.isArray(detail)) {
    // Pydantic v2 errors: each item is {type, loc, msg, input, ...}
    const messages = detail
      .map((e: { msg?: string; loc?: unknown[] }) => {
        const where = Array.isArray(e?.loc) ? e.loc.join('.') : ''
        return where ? `${where}: ${e?.msg ?? 'invalid'}` : (e?.msg ?? 'invalid')
      })
      .filter(Boolean)
    if (messages.length > 0) detailStr = messages.join('; ')
  } else if (detail && typeof detail === 'object') {
    // Last-ditch: stringify so we never throw, but it'll look ugly.
    try { detailStr = JSON.stringify(detail) } catch { detailStr = null }
  }

  if (status === 400) return detailStr || 'The file is empty or unreadable.'
  if (status === 422) return detailStr || 'The file failed validation. Check the contents and try again.'
  return detailStr || 'Could not parse the file. Please check it and try again.'
}

export function useImportEventPlan() {
  return useMutation({
    mutationFn: async (file: File): Promise<ParsedEventPlan> => {
      const formData = new FormData()
      formData.append('file', file)
      // Our shared axios instance bakes 'Content-Type: application/json'
      // into the defaults — which OVERRIDES axios\u2019s auto-detection
      // when a FormData body is passed. Result: the request goes out as
      // JSON, FastAPI sees no multipart parts, and rejects with 422
      // 'body.file: Field required'. Setting Content-Type to
      // 'multipart/form-data' here lets axios fill in the boundary on
      // its own. We do NOT want to mutate the shared defaults (other
      // callers expect json), so the override lives at the call site.
      const res = await api.post<ParsedEventPlan>('/events/import-plan', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    },
    onError: (err) => {
      // Surfacing errors handled by the caller via mutation.error;
      // we only normalize the message here so the UI doesn't have to
      // know about axios error shapes.
      const ax = err as { response?: { status?: number; data?: { detail?: string } } }
      const message = importPlanErrorMessage(ax.response?.status, ax.response?.data?.detail)
      // Stash the normalized message on the error so the component can read it.
      ;(err as Error).message = message
    },
  })
}
