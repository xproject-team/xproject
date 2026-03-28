/**
 * PredictionPage — ML demand forecast display for Owner/Manager.
 * Thin page: layout + composition only, no business logic.
 */
import { ForecastCard } from '@/features/predictions/ForecastCard'
import { TicketChart } from '@/features/predictions/TicketChart'

export default function PredictionPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-4">Demand Predictions</h1>
      <TicketChart />
      <ForecastCard />
    </div>
  )
}
