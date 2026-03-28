/**
 * ReportPage — post-event report with AI narrative and metrics grid.
 * Thin page: layout + composition only, no business logic.
 */
import { MetricsGrid } from '@/features/reports/MetricsGrid'
import { NarrativeSection } from '@/features/reports/NarrativeSection'

export default function ReportPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-4">Event Report</h1>
      <MetricsGrid />
      <NarrativeSection />
    </div>
  )
}
