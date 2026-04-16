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
