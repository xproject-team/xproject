/**
 * EventDetailPage — shows full event details, inventory summary, and alert feed.
 * Thin page: layout + composition only, no business logic.
 */
import { useParams } from 'react-router-dom'

export default function EventDetailPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-6">Event {id}</h1>
      {/* TODO: compose EventMetrics, AlertPanel, InventorySnapshot */}
    </div>
  )
}
