/**
 * EventForm — React Hook Form + Zod form for creating a new event.
 * Calls POST /api/v1/events and navigates to the event detail page on success.
 */
export function EventForm() {
  // TODO: implement with useForm, zodResolver, useMutation, useNavigate
  return (
    <form className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-[#4A5568]">Event Name</label>
        <input className="mt-1 w-full border border-[#E2E8F0] rounded px-3 py-2" />
      </div>
      <div>
        <label className="block text-sm font-medium text-[#4A5568]">Venue</label>
        <input className="mt-1 w-full border border-[#E2E8F0] rounded px-3 py-2" />
      </div>
      <button
        type="submit"
        className="bg-[#1E5A8D] text-white px-6 py-2 rounded font-medium"
      >
        Create Event
      </button>
    </form>
  )
}
