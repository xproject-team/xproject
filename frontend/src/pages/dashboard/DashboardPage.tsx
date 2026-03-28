/**
 * DashboardPage — real-time event operations overview for Owner/Manager.
 * Thin page: layout + composition only, no business logic.
 */
import { BarGrid } from '@/features/dashboard/BarGrid'
import { StatsStrip } from '@/features/dashboard/StatsStrip'

export default function DashboardPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-4">Dashboard</h1>
      <StatsStrip />
      <BarGrid />
    </div>
  )
}
