/**
 * ReportDetailPage — placeholder for /reports/:id.
 *
 * Minimal v0.1 version to prevent 404s when clicking report cards from
 * the index page. Full implementation (cover + narrative + revenue +
 * stock + alerts sections) is scheduled as the next frontend milestone.
 *
 * Currently shown:
 *   - Breadcrumb back to /reports
 *   - Report ID echo (so Omar can confirm the click routed correctly)
 *   - "Coming soon" notice with what the full page will contain
 *
 * Spec: docs/report-module-spec.md §8.2.
 */
import { Link, useParams } from 'react-router-dom'

import { useReport } from '@/features/reports/useReports'

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const { data: report, isLoading, isError } = useReport(reportId ?? null)

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <Link
        to="/reports"
        className="inline-flex items-center gap-1 text-sm text-[#4A5568] hover:text-[#1A202C] mb-4"
      >
        ← Back to reports
      </Link>

      {/* Header */}
      <h1 className="text-2xl font-bold text-[#1A202C] mb-1">
        {isLoading
          ? 'Loading…'
          : report?.data?.event.event_name ?? 'Report Detail'}
      </h1>
      <p className="text-xs text-[#A0AEC0] font-mono mb-6">
        {reportId}
      </p>

      {/* Error state */}
      {isError && (
        <div className="bg-[#FED7D7] text-[#742A2A] text-sm rounded-xl p-4 mb-4">
          Report not found. It may have been deleted, or the ID is invalid.
        </div>
      )}

      {/* Coming-soon notice */}
      <div className="bg-white border border-dashed border-[#CBD5E0] rounded-xl p-8">
        <div className="text-4xl mb-3">📄</div>
        <h2 className="text-base font-semibold text-[#1A202C] mb-2">
          Detailed report view — coming soon
        </h2>
        <p className="text-sm text-[#4A5568] leading-relaxed max-w-xl">
          The full report layout is being built. When it ships, this page will show:
        </p>
        <ul className="text-sm text-[#4A5568] mt-3 space-y-1 list-disc list-inside">
          <li>Cover page with event name, venue, total revenue</li>
          <li>Executive narrative — the consultant's letter (Italian or English)</li>
          <li>Revenue breakdown — per-bar chart + peak-hour timeline</li>
          <li>Stock Reality Check — opening/closing per product per bar</li>
          <li>Alerts timeline — every alert, acknowledged or not</li>
          <li>PDF download + language toggle IT ↔ EN</li>
        </ul>

        {/* Show raw narrative preview if the report is ready — proof the data flows */}
        {report?.status === 'ready' && report.data?.narrative && (
          <details className="mt-6">
            <summary className="text-xs text-[#718096] cursor-pointer hover:text-[#1A202C]">
              ▸ Preview narrative (raw)
            </summary>
            <div className="mt-3 text-sm bg-[#F7FAFC] rounded-lg p-4 space-y-3">
              <div>
                <p className="text-[11px] font-semibold text-[#718096] uppercase mb-1">
                  Cosa è successo
                </p>
                <p className="text-[#1A202C]">{report.data.narrative.what_happened}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-[#718096] uppercase mb-1">
                  Cosa ha funzionato
                </p>
                <p className="text-[#1A202C]">{report.data.narrative.what_worked}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-[#718096] uppercase mb-1">
                  Cosa fare al prossimo
                </p>
                <ul className="list-disc list-inside text-[#1A202C] space-y-1">
                  {report.data.narrative.what_next.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          </details>
        )}
      </div>
    </div>
  )
}
