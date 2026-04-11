/**
 * EventCard — displays a single event summary with status badge and navigation link.
 */
import { Link } from 'react-router-dom'
import type { EventResponse } from '@/lib/types'

interface EventCardProps {
  event: EventResponse
}

export function EventCard({ event }: EventCardProps) {
  return (
    <Link
      to={`/events/${event.id}`}
      className="block bg-white border border-[#E2E8F0] rounded-lg p-4 hover:shadow-md transition-shadow"
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-[#1A202C]">{event.name}</h3>
          <p className="text-sm text-[#4A5568]">{event.location}</p>
        </div>
        <span className="text-xs font-medium px-2 py-1 rounded-full bg-[#F7FAFC] border border-[#E2E8F0]">
          {event.status}
        </span>
      </div>
    </Link>
  )
}
