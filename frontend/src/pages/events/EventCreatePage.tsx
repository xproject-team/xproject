/**
 * EventCreatePage — form for creating a new event.
 * Thin page: layout only; form logic lives in EventForm.
 */
import { EventForm } from '@/features/events/EventForm'

export default function EventCreatePage() {
  return (
    <div className="p-6 max-w-lg mx-auto">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-6">Create Event</h1>
      <EventForm />
    </div>
  )
}
