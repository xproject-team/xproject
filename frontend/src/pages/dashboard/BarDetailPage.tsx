/**
 * BarDetailPage — per-bar inventory, consumption chart, and alert panel.
 * Thin page: layout + composition only, no business logic.
 */
import { useParams } from 'react-router-dom'

export default function BarDetailPage() {
  const { barId } = useParams<{ barId: string }>()

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-6">Bar {barId}</h1>
      {/* TODO: compose StockTable, RateChart, AlertPanel */}
    </div>
  )
}
