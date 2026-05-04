/**
 * useEventWeather — fetches the weather snapshot for an event.
 *
 * Backend: GET /api/v1/events/{eventId}/weather (returns
 * EventWeatherResponse from backend/app/modules/events/router.py).
 *
 * Refetch every 5 minutes (weather doesn\'t change second-to-second;
 * the backend sync is what keeps it fresh, this just reads what\'s
 * persisted).
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type WeatherCurrent = {
  time:                   string
  temperature_2m:         number
  weather_code:           number
  relative_humidity_2m?:  number | null
  wind_speed_10m?:        number | null
  precipitation?:         number | null
}

export type WeatherHourly = {
  time:                       string[]
  temperature_2m?:            number[]
  precipitation?:             number[]
  precipitation_probability?: number[]
  weather_code?:              number[]
  wind_speed_10m?:            number[]
}

export type WeatherSnapshot = {
  current?: WeatherCurrent
  hourly?:  WeatherHourly
  timezone?: string
}

export type EventWeatherResponse = {
  event_id:           string
  weather_fetched_at: string | null
  snapshot:           WeatherSnapshot | null
  is_stale:           boolean
}

export const weatherKeys = {
  byEvent: (eventId: string | null | undefined) =>
    ['event-weather', eventId ?? 'none'] as const,
} as const

const REFETCH_MS = 5 * 60 * 1000   // 5 min — weather is slow-moving

export function useEventWeather(eventId: string | null | undefined) {
  return useQuery<EventWeatherResponse>({
    queryKey: weatherKeys.byEvent(eventId),
    queryFn: async () => {
      const { data } = await api.get<EventWeatherResponse>(
        `/events/${eventId}/weather`,
      )
      return data
    },
    refetchInterval:             REFETCH_MS,
    refetchIntervalInBackground: false,
    staleTime:                   60_000,
    enabled:                     Boolean(eventId),
  })
}
