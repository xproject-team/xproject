/**
 * WarehouseScanPage — the full invoice-reconciliation flow at /warehouse/scan.
 *
 * Three states based on URL ?invoice=<id>:
 *   - No invoice selected      -> invoice list + 'New Delivery' button + form
 *   - Invoice EXPECTED/SCANNING/PAUSED -> ScannerView + live progress bars
 *   - Invoice closed (any terminal state) -> DiscrepancyReport view
 *
 * Spec: docs/warehouse-module-spec.md S3.1 + S3.2 + S3.3 + S6.
 *
 * Owner-only path today. The role passed to ScannerView is the current user's
 * role; ScannerView's role-aware buttons and the backend's role enforcement
 * (spec S3.5 matrix) work together to constrain what the user can do.
 */
import { useMemo, useState } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import { ScannerView } from '@/features/warehouse/ScannerView'
import {
  useCloseScan,
  useCreateInvoice,
  useInvoice,
  useInvoiceReport,
  usePauseScan,
  usePendingDeliveries,
  useResumeScan,
  useStartScan,
  type DiscrepancyLine,
  type DiscrepancyReport,
  type InvoiceItemCreate,
  type InvoiceResponse,
  type InvoiceStatus,
  type ScannerRole,
} from '@/features/warehouse/useWarehouse'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtEur(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return '—'
  return `€${(cents / 100).toLocaleString('it-IT', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('it-IT', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const TERMINAL_STATES: InvoiceStatus[] = ['VERIFIED', 'DISCREPANCY', 'DISPUTED', 'CLOSED']

// Map User.role (auth model) -> ScannerRole (warehouse module).
// Two-role model: this page is gated owner+manager; anything else at
// runtime (stale token) gets the least-privileged manager button set.
function mapAuthRole(role: string | null | undefined): ScannerRole {
  const r = (role ?? '').toLowerCase()
  if (r === 'owner') return 'owner'
  return 'manager'
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function WarehouseScanPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const invoiceId = searchParams.get('invoice')

  return (
    <div className="max-w-7xl mx-auto p-6">
      {!invoiceId && <InvoicePicker />}
      {invoiceId && (
        <InvoiceSession
          invoiceId={invoiceId}
          onClose={() => setSearchParams({})}
        />
      )}
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// State 1 — Invoice picker (no invoice selected)
// ═════════════════════════════════════════════════════════════════════════════

function InvoicePicker() {
  const [showForm, setShowForm] = useState(false)
  const pending = usePendingDeliveries()

  return (
    <>
      <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">New Delivery</h1>
          <p className="text-sm text-[#718096] mt-1">
            Create an invoice from the supplier's paper, then scan the bottles
            as they arrive.
          </p>
        </div>
        <Link
          to="/warehouse"
          className="text-sm text-[#4A5568] hover:text-[#1A202C] underline"
        >
          ← Back to Warehouse
        </Link>
      </div>

      {!showForm && (
        <button
          onClick={() => setShowForm(true)}
          className="bg-[#1E5A8D] hover:bg-[#2C7AA6] text-white font-semibold
                     px-5 py-2.5 rounded-lg shadow-sm transition mb-6"
        >
          + Create New Invoice
        </button>
      )}

      {showForm && <InvoiceForm onCreated={() => setShowForm(false)} />}

      <div className="mt-8">
        <h2 className="text-sm font-bold text-[#1A202C] mb-3">
          Pending Deliveries
        </h2>
        {pending.isLoading && (
          <p className="text-sm text-[#718096]">Loading…</p>
        )}
        {pending.data && pending.data.length === 0 && (
          <div className="bg-white border border-[#E2E8F0] rounded-lg p-8 text-center">
            <p className="text-3xl mb-2">📦</p>
            <p className="text-sm font-semibold text-[#1A202C]">
              No pending deliveries
            </p>
            <p className="text-xs text-[#718096] mt-1">
              Create one above when the next truck is scheduled.
            </p>
          </div>
        )}
        {pending.data && pending.data.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {pending.data.map((inv) => (
              <Link
                key={inv.id}
                to={`/warehouse/scan?invoice=${inv.id}`}
                className="block bg-white border border-[#E2E8F0] rounded-lg p-4
                           shadow-sm hover:shadow-md hover:border-[#1E5A8D] transition"
              >
                <div className="flex items-start justify-between mb-1">
                  <p className="font-semibold text-[#1A202C] truncate">
                    {inv.supplier_name}
                  </p>
                  <span
                    className="text-xs font-semibold px-2 py-0.5 rounded-full"
                    style={{
                      backgroundColor:
                        inv.status === 'EXPECTED'
                          ? '#EBF8FF'
                          : inv.status === 'SCANNING'
                            ? '#FEF3C7'
                            : '#F3E8FF',
                      color:
                        inv.status === 'EXPECTED'
                          ? '#2B6CB0'
                          : inv.status === 'SCANNING'
                            ? '#B45309'
                            : '#6B21A8',
                    }}
                  >
                    {inv.status}
                  </span>
                </div>
                <p className="text-xs text-[#718096]">
                  {fmtDate(inv.expected_arrival_date)} ·{' '}
                  {inv.items_count} item{inv.items_count === 1 ? '' : 's'}
                  {inv.total_expected_cents !== null && (
                    <> · {fmtEur(inv.total_expected_cents)}</>
                  )}
                </p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

// ─── Invoice creation form ───────────────────────────────────────────────────

interface FormLine extends Omit<InvoiceItemCreate, 'expected_qty'> {
  expected_qty: number
  unit_price_eur: number | null
}

function InvoiceForm({ onCreated }: { onCreated: () => void }) {
  const navigate = useNavigate()
  const [supplier, setSupplier] = useState('')
  const [arrivalDate, setArrivalDate] = useState(
    new Date().toISOString().slice(0, 10),
  )
  const [invoiceNumber, setInvoiceNumber] = useState('')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState<FormLine[]>([
    {
      kind: 'miscellaneous',
      product_id: null,
      miscellaneous_description: '',
      expected_qty: 0,
      unit_price_eur: null,
    },
  ])
  const [error, setError] = useState<string | null>(null)
  const create = useCreateInvoice()

  const total = useMemo(() => {
    return lines.reduce((sum, l) => {
      if (l.unit_price_eur && l.expected_qty)
        return sum + l.unit_price_eur * l.expected_qty
      return sum
    }, 0)
  }, [lines])

  const updateLine = (idx: number, patch: Partial<FormLine>) => {
    setLines((prev) =>
      prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)),
    )
  }

  const addLine = () => {
    setLines((prev) => [
      ...prev,
      {
        kind: 'miscellaneous',
        product_id: null,
        miscellaneous_description: '',
        expected_qty: 0,
        unit_price_eur: null,
      },
    ])
  }

  const removeLine = (idx: number) => {
    setLines((prev) => prev.filter((_, i) => i !== idx))
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const validLines = lines.filter(
      (l) => l.expected_qty > 0 && l.miscellaneous_description?.trim(),
    )
    if (validLines.length === 0) {
      setError('Add at least one line with a product description and quantity.')
      return
    }

    try {
      const created = await create.mutateAsync({
        supplier_name: supplier.trim(),
        invoice_number: invoiceNumber.trim() || null,
        expected_arrival_date: arrivalDate,
        notes: notes.trim() || null,
        items: validLines.map((l) => ({
          kind: 'miscellaneous',
          miscellaneous_description: l.miscellaneous_description?.trim() ?? '',
          expected_qty: l.expected_qty,
          unit_price_cents: l.unit_price_eur
            ? Math.round(l.unit_price_eur * 100)
            : null,
        })),
      })
      onCreated()
      navigate(`/warehouse/scan?invoice=${created.id}`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create invoice')
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-5"
    >
      <h2 className="text-base font-bold text-[#1A202C] mb-4">
        Create Invoice
      </h2>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <div>
          <label className="text-xs font-semibold text-[#4A5568] mb-1 block">
            Supplier *
          </label>
          <input
            type="text"
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            required
            placeholder="e.g. Distributore Roma SRL"
            className="w-full text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-[#4A5568] mb-1 block">
            Expected Arrival *
          </label>
          <input
            type="date"
            value={arrivalDate}
            onChange={(e) => setArrivalDate(e.target.value)}
            required
            className="w-full text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-[#4A5568] mb-1 block">
            Invoice # (optional)
          </label>
          <input
            type="text"
            value={invoiceNumber}
            onChange={(e) => setInvoiceNumber(e.target.value)}
            placeholder="e.g. INV-2026-0142"
            className="w-full text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
          />
        </div>
      </div>

      <div className="border border-[#E2E8F0] rounded-lg overflow-hidden mb-3">
        <div className="bg-[#F7FAFC] px-3 py-2 grid grid-cols-12 gap-2 text-xs font-semibold uppercase tracking-widest text-[#718096]">
          <div className="col-span-6">Product description</div>
          <div className="col-span-2 text-right">Qty</div>
          <div className="col-span-3 text-right">Unit price (€)</div>
          <div className="col-span-1"></div>
        </div>
        {lines.map((line, idx) => (
          <div
            key={idx}
            className="px-3 py-2 grid grid-cols-12 gap-2 border-t border-[#E2E8F0]"
          >
            <input
              type="text"
              value={line.miscellaneous_description ?? ''}
              onChange={(e) =>
                updateLine(idx, { miscellaneous_description: e.target.value })
              }
              placeholder="e.g. Vodka Smirnoff 1L"
              className="col-span-6 text-sm border border-[#E2E8F0] rounded-md px-2 py-1"
            />
            <input
              type="number"
              value={line.expected_qty || ''}
              onChange={(e) =>
                updateLine(idx, { expected_qty: Number(e.target.value) || 0 })
              }
              min={0}
              step="0.01"
              placeholder="0"
              className="col-span-2 text-sm border border-[#E2E8F0] rounded-md px-2 py-1 text-right"
            />
            <input
              type="number"
              value={line.unit_price_eur ?? ''}
              onChange={(e) =>
                updateLine(idx, {
                  unit_price_eur: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
              min={0}
              step="0.01"
              placeholder="—"
              className="col-span-3 text-sm border border-[#E2E8F0] rounded-md px-2 py-1 text-right"
            />
            <button
              type="button"
              onClick={() => removeLine(idx)}
              disabled={lines.length === 1}
              className="col-span-1 text-[#E53E3E] hover:text-[#C53030] disabled:opacity-30"
              aria-label="Remove line"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={addLine}
        className="text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline mb-4"
      >
        + Add line
      </button>

      <div className="bg-[#F7FAFC] rounded-md p-3 mb-4 flex items-center justify-between">
        <p className="text-xs font-semibold text-[#4A5568] uppercase tracking-widest">
          Expected total
        </p>
        <p className="text-lg font-bold text-[#1A202C]">
          {total > 0
            ? `€${total.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : '—'}
        </p>
      </div>

      <div className="mb-4">
        <label className="text-xs font-semibold text-[#4A5568] mb-1 block">
          Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
        />
      </div>

      {error && (
        <div className="bg-[#FEE2E2] border border-[#EF4444] rounded p-2 mb-3">
          <p className="text-xs text-[#991B1B]">{error}</p>
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={create.isPending}
          className="bg-[#1E5A8D] hover:bg-[#2C7AA6] disabled:bg-[#CBD5E0]
                     text-white text-sm font-semibold px-4 py-2 rounded-md transition"
        >
          {create.isPending ? 'Creating…' : 'Create Invoice'}
        </button>
        <button
          type="button"
          onClick={onCreated}
          className="text-sm text-[#4A5568] hover:text-[#1A202C] px-4 py-2"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// State 2/3 — Active scan session OR closed report
// ═════════════════════════════════════════════════════════════════════════════

interface InvoiceSessionProps {
  invoiceId: string
  onClose: () => void
}

function InvoiceSession({ invoiceId, onClose }: InvoiceSessionProps) {
  const invoiceQuery = useInvoice(invoiceId)
  const reportQuery = useInvoiceReport(invoiceId)
  const startScan = useStartScan(invoiceId)
  const pauseScan = usePauseScan(invoiceId)
  const resumeScan = useResumeScan(invoiceId)
  const closeScan = useCloseScan(invoiceId)
  const { user } = useAuth()

  const role = mapAuthRole(user?.role)

  if (invoiceQuery.isLoading) {
    return <p className="text-sm text-[#718096]">Loading invoice…</p>
  }
  if (invoiceQuery.isError || !invoiceQuery.data) {
    return (
      <div className="bg-[#FEE2E2] border border-[#EF4444] rounded p-4">
        <p className="text-sm text-[#991B1B]">
          Failed to load invoice. It may have been deleted.
        </p>
        <button onClick={onClose} className="text-xs underline mt-2">
          Back
        </button>
      </div>
    )
  }

  const invoice = invoiceQuery.data
  const isTerminal = TERMINAL_STATES.includes(invoice.status)

  return (
    <>
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div>
          <button
            onClick={onClose}
            className="text-xs text-[#4A5568] hover:text-[#1A202C] underline mb-2"
          >
            ← All deliveries
          </button>
          <h1 className="text-2xl font-bold text-[#1A202C]">
            {invoice.supplier_name}
          </h1>
          <p className="text-sm text-[#718096] mt-1">
            Expected {fmtDate(invoice.expected_arrival_date)}
            {invoice.invoice_number && <> · #{invoice.invoice_number}</>}
            {' · '}
            <span className="font-semibold">{invoice.status}</span>
          </p>
        </div>
        <InvoiceActionBar
          invoice={invoice}
          onStart={() => startScan.mutate()}
          onPause={() => pauseScan.mutate()}
          onResume={() => resumeScan.mutate()}
          onClose={() => closeScan.mutate()}
          startPending={startScan.isPending}
          pausePending={pauseScan.isPending}
          resumePending={resumeScan.isPending}
          closePending={closeScan.isPending}
        />
      </div>

      {!isTerminal && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {invoice.status === 'SCANNING' ? (
            <ScannerView
              role={role}
              invoiceId={invoiceId}
              onScanSubmitted={() => {
                void reportQuery.refetch()
              }}
            />
          ) : (
            <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-6 text-center">
              <p className="text-3xl mb-2">📦</p>
              <p className="text-sm text-[#1A202C] font-semibold">
                Scanning not started yet
              </p>
              <p className="text-xs text-[#718096] mt-1">
                {invoice.status === 'EXPECTED'
                  ? 'Press “Start scanning” when the truck arrives.'
                  : 'Press “Resume” to continue this paused session.'}
              </p>
            </div>
          )}
          <ProgressPanel
            invoice={invoice}
            report={reportQuery.data ?? null}
            isLoadingReport={reportQuery.isLoading}
          />
        </div>
      )}

      {isTerminal && reportQuery.data && (
        <DiscrepancyReportView report={reportQuery.data} />
      )}
    </>
  )
}

// ─── Action bar (state-machine buttons) ──────────────────────────────────────

interface InvoiceActionBarProps {
  invoice: InvoiceResponse
  onStart: () => void
  onPause: () => void
  onResume: () => void
  onClose: () => void
  startPending: boolean
  pausePending: boolean
  resumePending: boolean
  closePending: boolean
}

function InvoiceActionBar({
  invoice,
  onStart,
  onPause,
  onResume,
  onClose,
  startPending,
  pausePending,
  resumePending,
  closePending,
}: InvoiceActionBarProps) {
  const cls =
    'text-sm font-semibold px-4 py-2 rounded-md transition disabled:opacity-50'
  const primary = `${cls} bg-[#1E5A8D] hover:bg-[#2C7AA6] text-white`
  const secondary = `${cls} bg-white border border-[#E2E8F0] text-[#1A202C] hover:bg-[#F7FAFC]`

  return (
    <div className="flex gap-2 flex-wrap">
      {invoice.status === 'EXPECTED' && (
        <button onClick={onStart} disabled={startPending} className={primary}>
          {startPending ? 'Starting…' : 'Start scanning'}
        </button>
      )}
      {invoice.status === 'SCANNING' && (
        <>
          <button onClick={onPause} disabled={pausePending} className={secondary}>
            {pausePending ? 'Pausing…' : 'Pause'}
          </button>
          <button onClick={onClose} disabled={closePending} className={primary}>
            {closePending ? 'Closing…' : 'Close & reconcile'}
          </button>
        </>
      )}
      {invoice.status === 'PAUSED' && (
        <button onClick={onResume} disabled={resumePending} className={primary}>
          {resumePending ? 'Resuming…' : 'Resume'}
        </button>
      )}
    </div>
  )
}

// ─── Progress panel ──────────────────────────────────────────────────────────

interface ProgressPanelProps {
  invoice: InvoiceResponse
  report: DiscrepancyReport | null
  isLoadingReport: boolean
}

function ProgressPanel({ invoice, report }: ProgressPanelProps) {
  const scannedByKey = new Map<string, number>()
  if (report) {
    for (const line of report.lines) {
      const key =
        line.product_id ?? `misc:${line.product_name.toLowerCase().trim()}`
      scannedByKey.set(key, Number(line.scanned_qty) || 0)
    }
  }

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-4">
      <h2 className="text-sm font-bold text-[#1A202C] mb-3">
        Expected items ({invoice.items.length})
      </h2>
      <div className="space-y-3">
        {invoice.items.map((item) => {
          const key =
            item.kind === 'catalog_product'
              ? (item.product_id ?? '')
              : `misc:${(item.miscellaneous_description ?? '').toLowerCase().trim()}`
          const scanned = scannedByKey.get(key) ?? 0
          const expected = Number(item.expected_qty) || 0
          const pct = expected > 0 ? Math.min(100, (scanned / expected) * 100) : 0
          const fillColor =
            pct >= 100
              ? '#10B981'
              : pct >= 50
                ? '#F59E0B'
                : '#1E5A8D'
          const label =
            item.kind === 'catalog_product'
              ? `Product ${item.product_id?.slice(0, 8) ?? '—'}`
              : (item.miscellaneous_description ?? 'Unnamed')
          return (
            <div key={item.id}>
              <div className="flex items-baseline justify-between mb-1">
                <p className="text-sm font-medium text-[#1A202C] truncate flex-1">
                  {label}
                </p>
                <p className="text-xs font-semibold text-[#4A5568] ml-2 whitespace-nowrap">
                  {scanned} / {expected}
                </p>
              </div>
              <div className="h-2 bg-[#EDF2F7] rounded-full overflow-hidden">
                <div
                  className="h-full transition-all duration-300"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: fillColor,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
      {report && report.has_unexpected && (
        <p className="text-xs text-[#DD6B20] mt-3 font-medium">
          ⚠ Unexpected items scanned — they'll show in the discrepancy report.
        </p>
      )}
    </div>
  )
}

// ─── Discrepancy report (terminal states) ────────────────────────────────────

const STATUS_STYLES: Record<DiscrepancyLine['status'], { bg: string; color: string; label: string }> = {
  match:      { bg: '#D1FAE5', color: '#065F46', label: 'OK' },
  short:      { bg: '#FEE2E2', color: '#991B1B', label: 'SHORT' },
  extra:      { bg: '#FEF3C7', color: '#92400E', label: 'EXTRA' },
  unexpected: { bg: '#FECACA', color: '#7F1D1D', label: 'UNEXPECTED' },
}

function DiscrepancyReportView({ report }: { report: DiscrepancyReport }) {
  const overallBg =
    report.overall_status === 'match' ? '#D1FAE5' : '#FEE2E2'
  const overallColor =
    report.overall_status === 'match' ? '#065F46' : '#991B1B'
  const overallLabel =
    report.overall_status === 'match'
      ? '✓ Delivery verified — everything matches'
      : '✗ Discrepancy detected'

  return (
    <div className="space-y-4">
      <div
        className="rounded-lg p-4"
        style={{ backgroundColor: overallBg, color: overallColor }}
      >
        <p className="text-base font-bold">{overallLabel}</p>
        {report.total_delta_cents !== null && (
          <p className="text-sm mt-1">
            Net delta:{' '}
            <span className="font-semibold">
              {fmtEur(report.total_delta_cents)}
            </span>{' '}
            (Expected {fmtEur(report.total_expected_cents)} · Scanned{' '}
            {fmtEur(report.total_scanned_value_cents)})
          </p>
        )}
      </div>

      <div className="bg-white border border-[#E2E8F0] rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-[#F7FAFC]">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-widest text-[#718096]">
                Product
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-widest text-[#718096]">
                Expected
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-widest text-[#718096]">
                Scanned
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-widest text-[#718096]">
                Delta
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-widest text-[#718096]">
                € impact
              </th>
              <th className="px-4 py-2 text-center text-xs font-semibold uppercase tracking-widest text-[#718096]">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {report.lines.map((line, idx) => {
              const style = STATUS_STYLES[line.status]
              return (
                <tr key={idx} className="border-t border-[#EDF2F7]">
                  <td className="px-4 py-2 text-sm font-medium text-[#1A202C]">
                    {line.product_name}
                  </td>
                  <td className="px-4 py-2 text-sm text-right text-[#4A5568]">
                    {Number(line.expected_qty).toLocaleString('it-IT')}
                  </td>
                  <td className="px-4 py-2 text-sm text-right text-[#1A202C] font-semibold">
                    {Number(line.scanned_qty).toLocaleString('it-IT')}
                  </td>
                  <td
                    className="px-4 py-2 text-sm text-right font-semibold"
                    style={{
                      color:
                        Number(line.delta) === 0
                          ? '#4A5568'
                          : Number(line.delta) < 0
                            ? '#991B1B'
                            : '#92400E',
                    }}
                  >
                    {Number(line.delta) > 0
                      ? `+${line.delta}`
                      : line.delta}
                  </td>
                  <td className="px-4 py-2 text-sm text-right text-[#4A5568]">
                    {line.value_delta_cents !== null
                      ? fmtEur(line.value_delta_cents)
                      : '—'}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className="inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded-full"
                      style={{ backgroundColor: style.bg, color: style.color }}
                    >
                      {style.label}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
