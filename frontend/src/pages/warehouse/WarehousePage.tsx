/**
 * WarehousePage — Owner's warehouse dashboard.
 *
 * Replaces the 460-line mock scaffold with real backend-wired data. Covers
 * spec §3.4 layout:
 *   Top strip  — 4 KPI tiles (+ 1 bonus: total quantity)
 *   Pending deliveries strip — horizontal invoice list for EXPECTED/SCANNING/PAUSED
 *   Main area  — product inventory grid, searchable, sorted by at-risk first
 *   Side panel — activity feed (last N scans with role badges)
 *
 * Intentionally DROPPED from the old mockup:
 *   - Hardcoded "150 units" / "20 products tracked" fake numbers
 *   - "Stock Overview / Scan History" tabs that duplicated functionality
 *   - Event-scoped subtitle ("Sundance 2026 · 20 products tracked") —
 *     warehouse is tenant-scoped per spec §4.3; data persists independent
 *     of any event
 *
 * Intentionally DEFERRED to Session 3:
 *   - Camera scanner UI (html5-qrcode integration)
 *   - Invoice creation form
 *   - Active scan session screen with progress bars
 *   - Discrepancy report render
 *   - Pending review approve/reject UI
 *
 * For now the "+ New Delivery" button links to /warehouse/scan (placeholder
 * until Session 3 ships the real form).
 *
 * Spec: docs/warehouse-module-spec.md §3.4 + §8.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  useActivityFeed,
  useInventoryGrid,
  useInventoryKpis,
  usePendingDeliveries,
  type ActivityFeedRow,
  type InventoryRow,
  type InvoiceStatus,
  type InvoiceSummary,
  type ScannerRole,
  type ScanType,
} from '@/features/warehouse/useWarehouse'

// ─── Formatting helpers ──────────────────────────────────────────────────────

function fmtInt(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return Math.round(n).toLocaleString('it-IT')
}

function fmtDecimal(value: string | number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('it-IT', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

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
  })
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffMin = Math.floor((now - then) / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}h ago`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay}d ago`
}

// ─── KPI tile ─────────────────────────────────────────────────────────────────

interface KpiTileProps {
  label: string
  value: string
  hint?: string
  accent?: 'default' | 'warning' | 'danger'
}

function KpiTile({ label, value, hint, accent = 'default' }: KpiTileProps) {
  const accentColor =
    accent === 'danger' ? '#E53E3E' : accent === 'warning' ? '#DD6B20' : '#1E5A8D'

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4 shadow-sm">
      <p className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-1">
        {label}
      </p>
      <p className="text-2xl font-bold leading-tight" style={{ color: accentColor }}>
        {value}
      </p>
      {hint && <p className="text-xs text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}

// ─── Pending deliveries strip ────────────────────────────────────────────────

const INVOICE_STATUS_CONFIG: Record<
  InvoiceStatus,
  { bg: string; color: string; label: string }
> = {
  EXPECTED:    { bg: '#EBF8FF', color: '#2B6CB0', label: 'Expected'    },
  SCANNING:    { bg: '#FEF3C7', color: '#B45309', label: 'Scanning'    },
  PAUSED:      { bg: '#F3E8FF', color: '#6B21A8', label: 'Paused'      },
  VERIFIED:    { bg: '#D1FAE5', color: '#065F46', label: 'Verified'    },
  DISCREPANCY: { bg: '#FEE2E2', color: '#991B1B', label: 'Discrepancy' },
  DISPUTED:    { bg: '#FECACA', color: '#7F1D1D', label: 'Disputed'    },
  CLOSED:      { bg: '#F3F4F6', color: '#374151', label: 'Closed'      },
}

function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  const cfg = INVOICE_STATUS_CONFIG[status]
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded-full"
      style={{ backgroundColor: cfg.bg, color: cfg.color }}
    >
      {cfg.label}
    </span>
  )
}

function PendingDeliveryCard({ invoice }: { invoice: InvoiceSummary }) {
  return (
    <Link
      to={`/warehouse/scan?invoice=${invoice.id}`}
      className="block bg-white border border-[#E2E8F0] rounded-lg p-4 shadow-sm
                 hover:shadow-md hover:border-[#1E5A8D] transition min-w-[240px] flex-shrink-0"
    >
      <div className="flex items-start justify-between mb-2">
        <p className="text-sm font-semibold text-[#1A202C] truncate">
          {invoice.supplier_name}
        </p>
        <InvoiceStatusBadge status={invoice.status} />
      </div>
      <p className="text-xs text-[#718096]">
        Expected: <span className="font-medium">{fmtDate(invoice.expected_arrival_date)}</span>
      </p>
      <div className="flex items-center justify-between mt-2">
        <p className="text-xs text-[#4A5568]">
          {invoice.items_count} item{invoice.items_count === 1 ? '' : 's'}
        </p>
        {invoice.total_expected_cents !== null && (
          <p className="text-xs font-semibold text-[#1A202C]">
            {fmtEur(invoice.total_expected_cents)}
          </p>
        )}
      </div>
    </Link>
  )
}

// ─── Activity feed row ──────────────────────────────────────────────────────

const SCAN_TYPE_LABELS: Record<ScanType, string> = {
  INTAKE: 'Intake',
  DISPATCH: 'Dispatch',
  RETURN: 'Return',
  ADJUSTMENT: 'Adjustment',
  INSPECT: 'Inspect',
  CONSUMED: 'Consumed',
}

const ROLE_BADGES: Record<ScannerRole, { label: string; color: string }> = {
  owner: { label: 'owner', color: '#1E5A8D' },
  warehouse_keeper: { label: 'warehouse', color: '#DD6B20' },
  manager: { label: 'manager', color: '#6B21A8' },
  bartender: { label: 'bartender', color: '#059669' },
}

function ActivityRow({ row }: { row: ActivityFeedRow }) {
  const role = ROLE_BADGES[row.scanned_by_role]
  return (
    <div className="border-b border-[#EDF2F7] last:border-b-0 py-2.5">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#1A202C]">
            <span className="font-semibold">{fmtDecimal(row.qty, 0)}×</span>{' '}
            <span>{row.product_name ?? 'Unknown'}</span>
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-[#718096]">
              {SCAN_TYPE_LABELS[row.scan_type]}
            </span>
            <span className="text-xs text-[#CBD5E0]">·</span>
            <span className="text-xs text-[#718096]">
              {row.scanned_by_user_name ?? 'System'}
            </span>
            <span
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide"
              style={{ color: role.color, backgroundColor: `${role.color}15` }}
            >
              {role.label}
            </span>
          </div>
        </div>
        <p className="text-xs text-[#A0AEC0] whitespace-nowrap">
          {fmtRelative(row.scanned_at)}
        </p>
      </div>
      {row.is_unexpected && (
        <p className="text-xs text-[#DD6B20] mt-1 font-medium">
          ⚠ Unexpected · Needs review
        </p>
      )}
    </div>
  )
}

// ─── Product inventory row ──────────────────────────────────────────────────

function InventoryRowView({ row }: { row: InventoryRow }) {
  return (
    <tr
      className={`border-b border-[#EDF2F7] last:border-b-0 ${
        row.is_at_risk ? 'bg-[#FFF5F5]' : ''
      }`}
    >
      <td className="px-4 py-3">
        <p className="text-sm font-semibold text-[#1A202C]">{row.product_name}</p>
        {row.brand && (
          <p className="text-xs text-[#718096] mt-0.5">{row.brand}</p>
        )}
      </td>
      <td className="px-4 py-3">
        {row.category && (
          <span className="text-xs font-medium text-[#4A5568] bg-[#EDF2F7] px-2 py-0.5 rounded">
            {row.category}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <span
          className={`font-semibold ${
            row.is_at_risk ? 'text-[#E53E3E]' : 'text-[#1A202C]'
          }`}
        >
          {fmtDecimal(row.current_qty, 0)}
        </span>
      </td>
      <td className="px-4 py-3 text-right text-[#4A5568]">
        {fmtDecimal(row.allocated_qty, 0)}
      </td>
      <td className="px-4 py-3 text-right font-medium text-[#1A202C]">
        {fmtDecimal(row.available_qty, 0)}
      </td>
      <td className="px-4 py-3">
        {row.is_at_risk && (
          <span className="text-xs font-semibold text-[#E53E3E]">⚠ At risk</span>
        )}
      </td>
    </tr>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function WarehousePage() {
  const [search, setSearch] = useState('')

  const kpisQuery = useInventoryKpis()
  const inventoryQuery = useInventoryGrid()
  const activityQuery = useActivityFeed(20)
  const pendingQuery = usePendingDeliveries()

  const filteredInventory = useMemo(() => {
    if (!inventoryQuery.data) return []
    if (!search.trim()) return inventoryQuery.data
    const q = search.trim().toLowerCase()
    return inventoryQuery.data.filter(
      (r) =>
        r.product_name.toLowerCase().includes(q) ||
        (r.brand?.toLowerCase().includes(q) ?? false) ||
        (r.category?.toLowerCase().includes(q) ?? false),
    )
  }, [inventoryQuery.data, search])

  // Sort at-risk first, then alphabetically
  const sortedInventory = useMemo(() => {
    return [...filteredInventory].sort((a, b) => {
      if (a.is_at_risk !== b.is_at_risk) return a.is_at_risk ? -1 : 1
      return a.product_name.localeCompare(b.product_name)
    })
  }, [filteredInventory])

  const kpis = kpisQuery.data

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Page header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">
            Warehouse Management
          </h1>
          <p className="text-sm text-[#718096] mt-1">
            Invoice reconciliation & inventory tracking
          </p>
        </div>
        <Link
          to="/warehouse/scan"
          className="inline-flex items-center gap-2 bg-[#1E5A8D] hover:bg-[#2C7AA6]
                     text-white text-sm font-semibold px-4 py-2 rounded-lg shadow-sm
                     transition"
        >
          <span className="text-lg">+</span>
          New Delivery
        </Link>
      </div>

      {/* KPI strip — 5 tiles */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <KpiTile
          label="Total Items"
          value={kpis ? fmtInt(kpis.total_items) : '…'}
          hint="distinct products"
        />
        <KpiTile
          label="Total Quantity"
          value={kpis ? fmtDecimal(kpis.total_quantity, 0) : '…'}
          hint="units in warehouse"
        />
        <KpiTile
          label="At Risk"
          value={kpis ? fmtInt(kpis.products_at_risk) : '…'}
          hint="below threshold"
          accent={kpis && kpis.products_at_risk > 0 ? 'warning' : 'default'}
        />
        <KpiTile
          label="Active Allocations"
          value={kpis ? fmtDecimal(kpis.active_allocations, 0) : '…'}
          hint="reserved for events"
        />
        <div className="flex flex-col">
          {kpis && kpis.pending_reviews > 0 ? (
            <Link to="/warehouse/pending-review" className="block hover:shadow-md transition rounded-lg">
              <KpiTile
                label="Pending Reviews"
                value={fmtInt(kpis.pending_reviews)}
                hint="click to review"
                accent="danger"
              />
            </Link>
          ) : (
            <KpiTile
              label="Pending Reviews"
              value={kpis ? fmtInt(kpis.pending_reviews) : '…'}
              hint="scans to approve"
              accent="default"
            />
          )}
          <Link
            to="/warehouse/pending-review"
            className="text-[11px] text-[#1E5A8D] hover:text-[#2C7AA6] underline mt-1.5 self-end pr-1"
          >
            See review history →
          </Link>
        </div>
      </div>

      {/* Pending deliveries strip (only if any) */}
      {pendingQuery.data && pendingQuery.data.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-bold text-[#1A202C] mb-2">
            Pending Deliveries
          </h2>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {pendingQuery.data.map((inv) => (
              <PendingDeliveryCard key={inv.id} invoice={inv} />
            ))}
          </div>
        </div>
      )}

      {/* Main grid: inventory (left 2/3) + activity feed (right 1/3) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Inventory grid */}
        <div className="lg:col-span-2">
          <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm">
            <div className="px-4 py-3 border-b border-[#EDF2F7] flex items-center justify-between flex-wrap gap-3">
              <h2 className="text-sm font-bold text-[#1A202C]">Inventory</h2>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search product, brand, category…"
                className="text-sm border border-[#E2E8F0] rounded-md px-3 py-1.5 w-64
                           focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]"
              />
            </div>
            {inventoryQuery.isLoading && (
              <div className="p-6 text-sm text-[#718096]">Loading…</div>
            )}
            {inventoryQuery.isError && (
              <div className="p-6 text-sm text-[#E53E3E]">Failed to load inventory.</div>
            )}
            {inventoryQuery.data && sortedInventory.length === 0 && (
              <div className="p-10 text-center">
                <p className="text-4xl mb-3">📦</p>
                <p className="text-sm font-semibold text-[#1A202C]">
                  {search ? 'No products match your search.' : 'No inventory yet.'}
                </p>
                {!search && (
                  <p className="text-xs text-[#718096] mt-1">
                    Create a delivery invoice and scan the first shipment to populate inventory.
                  </p>
                )}
              </div>
            )}
            {sortedInventory.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-[#F7FAFC]">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-[#718096] uppercase tracking-widest">
                        Product
                      </th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-[#718096] uppercase tracking-widest">
                        Category
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-[#718096] uppercase tracking-widest">
                        In Stock
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-[#718096] uppercase tracking-widest">
                        Allocated
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-[#718096] uppercase tracking-widest">
                        Available
                      </th>
                      <th className="px-4 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedInventory.map((row) => (
                      <InventoryRowView key={row.product_id} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Activity feed */}
        <div>
          <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm">
            <div className="px-4 py-3 border-b border-[#EDF2F7]">
              <h2 className="text-sm font-bold text-[#1A202C]">Activity</h2>
              <p className="text-xs text-[#718096] mt-0.5">Last 20 scans</p>
            </div>
            <div className="p-3 max-h-[600px] overflow-y-auto">
              {activityQuery.isLoading && (
                <p className="text-sm text-[#718096] p-2">Loading…</p>
              )}
              {activityQuery.isError && (
                <p className="text-sm text-[#E53E3E] p-2">Failed to load.</p>
              )}
              {activityQuery.data && activityQuery.data.length === 0 && (
                <div className="py-6 text-center">
                  <p className="text-3xl mb-2">📊</p>
                  <p className="text-sm font-semibold text-[#1A202C]">
                    No activity yet
                  </p>
                  <p className="text-xs text-[#718096] mt-1">
                    Scans will appear here.
                  </p>
                </div>
              )}
              {activityQuery.data && activityQuery.data.length > 0 && (
                <div className="divide-y divide-[#EDF2F7]">
                  {activityQuery.data.map((row) => (
                    <ActivityRow key={row.id} row={row} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
