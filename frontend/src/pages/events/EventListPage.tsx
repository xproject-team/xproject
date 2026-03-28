/**
 * EventListPage — lists all events with create button.
 * Thin page: layout + composition only, no business logic.
 */
import { EventCard } from '@/features/events/EventCard'
import { useEvents } from '@/features/events/useEvents'

export default function EventListPage() {
  const { events, isLoading } = useEvents()

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-6">Events</h1>
      {isLoading ? (
        <p>Loading…</p>
      ) : (
        <div className="grid gap-4">
          {events.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}
