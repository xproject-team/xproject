/**
 * ReportPage — post-event AI narratives, metrics, and export controls.
 * Thin page: layout + composition only, no business logic.
 */

import { useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface PastReport {
  id: number
  name: string
  generated: string
  content: {
    guests: number
    revenue: string
    accuracy: string
    highlights: string[]
  }
}

// ─── Past reports data ────────────────────────────────────────────────────────

const PAST_REPORTS: PastReport[] = [
  {
    id: 1,
    name: 'Spring Festival 2025',
    generated: 'April 13, 2025',
    content: {
      guests: 312,
      revenue: '€19,840',
      accuracy: '91%',
      highlights: [
        'Craft beer was the top-selling product — 38% above ML prediction.',
        'Pool Bar operated at 97% efficiency with zero critical alerts.',
        'Pre-event stock allocation was within 3% of post-event actual demand.',
      ],
    },
  },
  {
    id: 2,
    name: 'NYE Party 2024',
    generated: 'January 2, 2025',
    content: {
      guests: 490,
      revenue: '€31,200',
      accuracy: '85%',
      highlights: [
        'Champagne accounted for 41% of VIP Lounge revenue.',
        'Staff-to-guest ratio was slightly under-optimised in DJ Booth.',
        'Emergency restock of prosecco was required at 23:30.',
      ],
    },
  },
]

// ─── Narrative sections ───────────────────────────────────────────────────────

interface NarrativeSection {
  id: string
  title: string
  icon: React.ReactNode
  accent: string
  body: React.ReactNode
}

// ─── Metric cards ─────────────────────────────────────────────────────────────

interface Metric {
  label: string
  value: string
  sub?: string
  icon: React.ReactNode
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ message, visible }: { message: string; visible: boolean }) {
  return (
    <div
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(14px)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        pointerEvents: 'none',
      }}
      className="fixed bottom-6 right-6 z-50 bg-[#1A202C] text-white text-sm font-medium px-5 py-3 rounded-xl shadow-2xl flex items-center gap-2"
    >
      <svg className="w-4 h-4 text-[#68D391] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
      </svg>
      {message}
    </div>
  )
}

// ─── Expandable accordion card ────────────────────────────────────────────────

function AccordionCard({
  title,
  icon,
  accent,
  children,
  defaultOpen = false,
}: {
  title: string
  icon: React.ReactNode
  accent: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-[#FAFAFA] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: accent + '18' }}
          >
            <span style={{ color: accent }}>{icon}</span>
          </span>
          <span className="font-bold text-[#1A202C] text-sm">{title}</span>
        </div>
        <svg
          className="w-4 h-4 text-[#A0AEC0] flex-shrink-0 transition-transform duration-300"
          style={{ transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Animated body */}
      <div
        style={{
          maxHeight: open ? '600px' : '0px',
          opacity: open ? 1 : 0,
          transition: 'max-height 0.35s ease, opacity 0.25s ease',
          overflow: 'hidden',
        }}
      >
        <div className="px-6 pb-5 pt-1 border-t border-[#EDF2F7]">{children}</div>
      </div>
    </div>
  )
}

// ─── Past report expanded view ────────────────────────────────────────────────

function PastReportCard({ report }: { report: PastReport }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden">
      {/* Header row */}
      <div className="flex items-center justify-between gap-4 px-5 py-4">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-[#F7FAFC] border border-[#E2E8F0] flex items-center justify-center flex-shrink-0">
            <svg className="w-5 h-5 text-[#4A5568]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <div>
            <p className="font-bold text-[#1A202C] text-sm">{report.name}</p>
            <p className="text-xs text-[#718096] mt-0.5">Generated {report.generated}</p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {/* Status badge */}
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-[#276749] bg-[#F0FFF4] border border-[#9AE6B4] px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-[#38A169] inline-block" />
            Complete
          </span>

          {/* View Report button */}
          <button
            id={`btn-view-report-${report.id}`}
            onClick={() => setExpanded((e) => !e)}
            className="flex items-center gap-1.5 text-xs font-semibold text-[#0694A2] border border-[#0694A2] px-3 py-1.5 rounded-lg hover:bg-[#E6FFFA] transition-colors"
          >
            {expanded ? 'Hide Report' : 'View Report'}
            <svg
              className="w-3.5 h-3.5 transition-transform duration-300"
              style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Expanded report content */}
      <div
        style={{
          maxHeight: expanded ? '400px' : '0px',
          opacity: expanded ? 1 : 0,
          transition: 'max-height 0.4s ease, opacity 0.3s ease',
          overflow: 'hidden',
        }}
      >
        <div className="border-t border-[#EDF2F7] px-5 py-4 bg-[#FAFBFC]">
          <div className="flex gap-6 mb-4">
            {[
              { label: 'Guests', val: report.content.guests },
              { label: 'Revenue', val: report.content.revenue },
              { label: 'ML Accuracy', val: report.content.accuracy },
            ].map((m) => (
              <div key={m.label}>
                <p className="text-xs text-[#A0AEC0] font-medium">{m.label}</p>
                <p className="text-base font-bold text-[#1A202C] mt-0.5">{m.val}</p>
              </div>
            ))}
          </div>
          <p className="text-xs font-semibold text-[#4A5568] uppercase tracking-wider mb-2">Highlights</p>
          <ul className="space-y-1.5">
            {report.content.highlights.map((h, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[#4A5568]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0694A2] mt-1.5 flex-shrink-0" />
                {h}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ReportPage() {
  const [toast, setToast] = useState<{ msg: string; visible: boolean }>({ msg: '', visible: false })

  function showToast(msg: string) {
    setToast({ msg, visible: true })
    setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000)
  }

  // ── Narrative sections ────────────────────────────────────────────────────

  const narratives: NarrativeSection[] = [
    {
      id: 'what-happened',
      title: 'What Happened',
      accent: '#3182CE',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
      ),
      body: (
        <p className="text-sm text-[#4A5568] leading-relaxed mt-3">
          Sundance 2026 attracted <strong className="text-[#1A202C]">347 guests</strong> across{' '}
          <strong className="text-[#1A202C]">4 bars</strong> over 6 hours. Total revenue reached{' '}
          <strong className="text-[#1A202C]">€24,350</strong>, exceeding predictions by 12%. VIP Lounge
          generated <strong className="text-[#1A202C]">32% of total revenue</strong> with only 18% of staff
          allocation, making it the most efficient service point. DJ Booth experienced critical stock depletion
          at 22:14, requiring emergency restock of vodka and tonic water.
        </p>
      ),
    },
    {
      id: 'what-worked',
      title: 'What Worked',
      accent: '#38A169',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ),
      body: (
        <p className="text-sm text-[#4A5568] leading-relaxed mt-3">
          ML demand predictions achieved <strong className="text-[#1A202C]">89% accuracy</strong> for beer
          and <strong className="text-[#1A202C]">94% accuracy</strong> for spirits. The dynamic alert system
          caught the DJ Booth depletion <strong className="text-[#1A202C]">45 minutes</strong> before complete
          stockout, preventing an estimated{' '}
          <strong className="text-[#1A202C]">€800 in lost sales</strong>. Pre-event stock allocation for Main
          Bar and Pool Bar was within <strong className="text-[#1A202C]">5% of optimal</strong>.
        </p>
      ),
    },
    {
      id: 'what-next',
      title: 'What Next',
      accent: '#D69E2E',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
      body: (
        <ul className="space-y-3 mt-3">
          {[
            'Increase DJ Booth initial vodka allocation by 40% for next event.',
            'Consider adding a 5th bartender to VIP Lounge during peak hours (21:00–23:00).',
            'Champagne reorder threshold should be raised from 10 to 15 bottles.',
            'Investigate beer consumption anomaly at Main Bar — 18% above prediction.',
          ].map((rec, i) => (
            <li key={i} className="flex items-start gap-3 text-sm text-[#4A5568]">
              <span className="w-5 h-5 rounded-full bg-[#FFF3CD] border border-[#F6E05E] text-[#744210] text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                {i + 1}
              </span>
              {rec}
            </li>
          ))}
        </ul>
      ),
    },
  ]

  // ── Metrics ───────────────────────────────────────────────────────────────

  const metrics: Metric[] = [
    {
      label: 'Total Revenue',
      value: '€24,350',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
    {
      label: 'Total Guests',
      value: '347',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
    {
      label: 'Prediction Accuracy',
      value: '89%',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
    },
    {
      label: 'Alerts Triggered',
      value: '7',
      sub: '5 resolved · 2 critical',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
      ),
    },
    {
      label: 'Avg Transaction',
      value: '€12.40',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
        </svg>
      ),
    },
    {
      label: 'Staff Efficiency',
      value: '87',
      sub: 'drinks / staff / hour',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      ),
    },
  ]

  const METRIC_ACCENTS = ['#3182CE', '#38A169', '#0694A2', '#E53E3E', '#805AD5', '#D69E2E']

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">

      {/* ── Page header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-[#1A202C] tracking-tight">Event Reports</h1>
          <p className="text-sm text-[#718096] mt-1">
            Post-event summaries and AI-generated narratives
          </p>
        </div>
        <button
          id="btn-generate-new-report"
          onClick={() => showToast('Report generating...')}
          className="inline-flex items-center gap-2 text-sm font-semibold text-white bg-[#0694A2] hover:bg-[#047481] px-4 py-2.5 rounded-lg shadow-sm transition-all flex-shrink-0"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 4v16m8-8H4" />
          </svg>
          Generate New Report
        </button>
      </div>

      {/* ── Past reports ── */}
      <section>
        <h2 className="text-sm font-bold text-[#4A5568] uppercase tracking-widest mb-3">
          Past Reports
        </h2>
        <div className="space-y-3">
          {PAST_REPORTS.map((r) => (
            <PastReportCard key={r.id} report={r} />
          ))}
        </div>
      </section>

      {/* ── Current event card ── */}
      <section>
        <h2 className="text-sm font-bold text-[#4A5568] uppercase tracking-widest mb-3">
          Current Event
        </h2>
        <div className="bg-gradient-to-r from-[#1A365D] to-[#2A4A7F] text-white rounded-2xl shadow-lg p-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <h2 className="text-lg font-extrabold">Sundance 2026 — Live Event</h2>
                <span className="inline-flex items-center gap-1 text-xs font-bold text-[#FBD38D] bg-white/10 border border-[#FBD38D]/40 px-2.5 py-1 rounded-full">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#F6AD55] animate-pulse inline-block" />
                  In Progress
                </span>
              </div>
              <p className="text-blue-200 text-sm leading-relaxed max-w-lg">
                Full report will be available after event completion. Preliminary data shown below.
              </p>
            </div>
            <div className="flex-shrink-0 bg-white/10 backdrop-blur-sm border border-white/20 rounded-xl px-5 py-3 text-center">
              <p className="text-2xl font-extrabold">€24,350</p>
              <p className="text-xs text-blue-300 mt-0.5">Revenue so far</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── AI Narrative sections ── */}
      <section>
        <h2 className="text-sm font-bold text-[#4A5568] uppercase tracking-widest mb-3">
          AI-Generated Narrative
        </h2>
        <div className="space-y-3">
          {narratives.map((n, i) => (
            <AccordionCard
              key={n.id}
              title={n.title}
              icon={n.icon}
              accent={n.accent}
              defaultOpen={i === 0}
            >
              {n.body}
            </AccordionCard>
          ))}
        </div>
      </section>

      {/* ── Metrics grid ── */}
      <section>
        <h2 className="text-sm font-bold text-[#4A5568] uppercase tracking-widest mb-3">
          Key Metrics
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {metrics.map((m, i) => (
            <div
              key={m.label}
              className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm p-5 hover:shadow-md transition-shadow"
              style={{ borderLeftColor: METRIC_ACCENTS[i], borderLeftWidth: 4 }}
            >
              <div className="flex items-start justify-between mb-3">
                <p className="text-xs font-semibold text-[#718096] uppercase tracking-wider leading-tight">
                  {m.label}
                </p>
                <span style={{ color: METRIC_ACCENTS[i] }}>{m.icon}</span>
              </div>
              <p className="text-2xl font-extrabold text-[#1A202C]">{m.value}</p>
              {m.sub && (
                <p className="text-xs text-[#A0AEC0] mt-1">{m.sub}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Export section ── */}
      <section>
        <h2 className="text-sm font-bold text-[#4A5568] uppercase tracking-widest mb-3">
          Export & Share
        </h2>
        <div className="bg-white border border-[#E2E8F0] rounded-2xl shadow-sm p-6 flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <div className="flex-1">
            <p className="text-sm font-semibold text-[#1A202C]">Download or share this report</p>
            <p className="text-xs text-[#A0AEC0] mt-0.5">
              PDF includes full narrative, metrics, and raw transaction data.
            </p>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              id="btn-download-pdf"
              onClick={() => showToast('PDF downloading...')}
              className="inline-flex items-center gap-2 text-sm font-semibold text-white bg-[#1A202C] hover:bg-[#2D3748] px-4 py-2.5 rounded-lg shadow-sm transition-all"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Download PDF Report
            </button>
            <button
              id="btn-share-report"
              onClick={() => showToast('Report shared via email')}
              className="inline-flex items-center gap-2 text-sm font-semibold text-[#0694A2] border border-[#0694A2] hover:bg-[#E6FFFA] px-4 py-2.5 rounded-lg transition-all"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
              </svg>
              Share with Team
            </button>
          </div>
        </div>
      </section>

      <Toast message={toast.msg} visible={toast.visible} />
    </div>
  )
}
