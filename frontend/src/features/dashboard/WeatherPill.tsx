/**
 * WeatherPill — small badge in the dashboard header showing current
 * conditions at the event venue.
 *
 * Visual:
 *   ☀️ 24°C  (clear)
 *   ⛅ 18°C  (partly cloudy)
 *   🌧 12°C 60%  (rain — shows precipitation_probability if available)
 *   ⚠ stale  if backend reports is_stale (sync hasn\'t run in 2h+)
 *
 * Hidden when:
 *   - eventId is missing
 *   - the request is in flight (loading)
 *   - the snapshot is null (weather has never been synced for this event)
 *
 * Tooltip on hover shows last-fetched time + venue lat/lon (when present).
 */
import { useEventWeather } from './useEventWeather'

// WMO weather codes -> emoji + short label.
// Reference: https://open-meteo.com/en/docs (search WMO Weather interpretation codes)
function describeWeather(code: number | undefined): { emoji: string; label: string } {
  if (code === undefined || code === null) return { emoji: '·', label: '—' }
  if (code === 0)                  return { emoji: '☀️', label: 'clear' }
  if (code >= 1 && code <= 3)      return { emoji: '⛅', label: 'partly cloudy' }
  if (code === 45 || code === 48)  return { emoji: '🌫', label: 'fog' }
  if (code >= 51 && code <= 57)    return { emoji: '🌦', label: 'drizzle' }
  if (code >= 61 && code <= 67)    return { emoji: '🌧', label: 'rain' }
  if (code >= 71 && code <= 77)    return { emoji: '❄️', label: 'snow' }
  if (code >= 80 && code <= 82)    return { emoji: '🌧', label: 'showers' }
  if (code >= 85 && code <= 86)    return { emoji: '🌨', label: 'snow showers' }
  if (code >= 95)                  return { emoji: '⛈', label: 'thunderstorm' }
  return { emoji: '·', label: 'unknown' }
}

interface WeatherPillProps {
  eventId: string | null | undefined
}

export function WeatherPill({ eventId }: WeatherPillProps) {
  const { data, isLoading } = useEventWeather(eventId)

  if (!eventId || isLoading || !data || !data.snapshot || !data.snapshot.current) {
    return null
  }

  const c       = data.snapshot.current
  const tempC   = Math.round(c.temperature_2m)
  const wx      = describeWeather(c.weather_code)
  const isStale = data.is_stale

  // Pull next-3-hour rain probability if available (defensive — array might be empty)
  const probs   = data.snapshot.hourly?.precipitation_probability ?? []
  const next3h  = probs.slice(0, 3)
  const peakProb = next3h.length > 0 ? Math.max(...next3h) : 0

  const pillClasses = isStale
    ? 'bg-amber-50 text-amber-800 ring-amber-200'
    : 'bg-sky-50 text-sky-800 ring-sky-200'

  const fetchedHumanReadable = data.weather_fetched_at
    ? new Date(data.weather_fetched_at).toLocaleString('it-IT', {
        hour:   '2-digit',
        minute: '2-digit',
      })
    : '—'

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs ring-1 ${pillClasses}`}
      title={`Weather at venue · last fetched ${fetchedHumanReadable}${isStale ? ' (stale, >2h)' : ''}`}
    >
      <span aria-hidden="true">{wx.emoji}</span>
      <span className="font-semibold">{tempC}°C</span>
      {peakProb >= 30 && (
        <span className="opacity-75">· {peakProb}% rain</span>
      )}
      {isStale && (
        <span className="opacity-75 italic">· stale</span>
      )}
    </span>
  )
}
