/**
 * WarehousePendingReviewPage — Owner's queue of unexpected scans needing approval.
 *
 * Mounted at /warehouse/pending-review. Owner-only.
 *
 * Workflow:
 *   1. INTAKE scan submitted for a product NOT on the active invoice
 *      → backend flags scan as is_unexpected=true + pending_review=true
 *      → KPI tile on /warehouse increments
 *   2. Owner opens this page, sees the queue
 *   3. Each row has APPROVE (keep the inventory delta) or REJECT
 *      (reverse the delta) action
 *   4. Action clears pending_review, removes the row from the queue
 *
 * Spec: docs/warehouse-module-spec.md §3.4 (Pending Reviews KPI) + §6.4
 *       (unexpected scan handling) + §8 (approve/reject endpoints).
 */
import { Link } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import {
  useApprovePendingScan,
  usePendingReviewQueue,
  useRejectPendingScan,
  type ScanResponse,
} from '@/features/warehouse/useWarehouse'
import { resolveRoleBadge } from '@/features/warehouse/roleBadges'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('it-IT', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtDecimal(value: string | number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('it-IT', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

// ─── Pending review row ──────────────────────────────────────────────────────

function PendingReviewRow({ scan }: { scan: ScanResponse }) {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'
  const approve = useApprovePendingScan()
  const reject = useRejectPendingScan()

  // Tolerates unknown roles (resolveRoleBadge falls back instead of
  // crashing) — scanned_by_role is a historical audit snapshot that can
  // outlive the current role model.
  const role = resolveRoleBadge(scan.scanned_by_role)
  const inFlight = approve.isPending || reject.isPending

  const handleApprove = () => approve.mutate(scan.id)
  const handleReject = () => reject.mutate(scan.id)

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-4 mb-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        {/* Left: scan info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <p className="text-base font-semibold text-[#1A202C]">
              {fmtDecimal(scan.qty)}× {scan.product_name ?? 'Unknown product'}
            </p>
            <span
              className="inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest rounded-full"
              style={{
                backgroundColor: '#FEF3C7',
                color: '#92400E',
              }}
            >
              {scan.scan_type}
            </span>
          </div>

          {scan.barcode_raw && (
            <p className="text-xs text-[#718096] mb-1 font-mono">
              Barcode: {scan.barcode_raw}
            </p>
          )}

          <div className="flex items-center gap-3 mt-2 text-xs text-[#4A5568] flex-wrap">
            <span>
              Scanned: <strong>{fmtTime(scan.scanned_at)}</strong>
            </span>
            {scan.scanned_by_user_name && (
              <>
                <span className="text-[#CBD5E0]">·</span>
                <span>
                  by <strong>{scan.scanned_by_user_name}</strong>
                </span>
                <span
                  className="text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide"
                  style={{ color: role.color, backgroundColor: `${role.color}15` }}
                >
                  {role.label}
                </span>
              </>
            )}
          </div>

          {scan.invoice_id && (
            <p className="text-xs text-[#718096] mt-2">
              <Link
                to={`/warehouse/scan?invoice=${scan.invoice_id}`}
                className="underline hover:text-[#1E5A8D]"
              >
                View linked invoice →
              </Link>
            </p>
          )}
        </div>

        {/* Right: action buttons — Owner only per spec §5.3 */}
        {isOwner && (
        <div className="flex flex-col gap-2 shrink-0">
          <button
            onClick={handleApprove}
            disabled={inFlight}
            className="bg-[#10B981] hover:bg-[#059669] disabled:bg-[#CBD5E0]
                       text-white text-sm font-semibold px-4 py-2 rounded-md
                       transition min-w-[100px]"
          >
            {approve.isPending ? 'Approving…' : '✓ Approve'}
          </button>
          <button
            onClick={handleReject}
            disabled={inFlight}
            className="bg-white hover:bg-[#FEE2E2] disabled:bg-[#F7FAFC]
                       border border-[#E2E8F0] hover:border-[#EF4444]
                       text-[#991B1B] disabled:text-[#A0AEC0]
                       text-sm font-semibold px-4 py-2 rounded-md transition min-w-[100px]"
          >
            {reject.isPending ? 'Rejecting…' : '✕ Reject'}
          </button>
        </div>
        )}
      </div>

      {/* Error feedback if either mutation fails */}
      {(approve.isError || reject.isError) && (
        <div className="mt-3 text-xs text-[#991B1B] bg-[#FEE2E2] rounded p-2">
          Action failed. Try again or refresh the page.
        </div>
      )}
    </div>
  )
}

// ─── Empty + loading + error states ──────────────────────────────────────────

function EmptyState() {
  return (
    <div className="bg-white border border-dashed border-[#CBD5E0] rounded-lg
                    p-12 text-center max-w-2xl mx-auto">
      <p className="text-5xl mb-3">✓</p>
      <p className="text-lg font-semibold text-[#1A202C] mb-1">
        Nothing to review
      </p>
      <p className="text-sm text-[#718096]">
        Unexpected scans during deliveries appear here so you can decide whether
        to keep them as bonus stock or reject them as supplier errors.
      </p>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function WarehousePendingReviewPage() {
  const queue = usePendingReviewQueue()

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">
            Pending Reviews
          </h1>
          <p className="text-sm text-[#718096] mt-1">
            Approve unexpected scans as bonus stock, or reject them to reverse
            the inventory change.
          </p>
        </div>
        <Link
          to="/warehouse"
          className="text-sm text-[#4A5568] hover:text-[#1A202C] underline"
        >
          ← Back to Warehouse
        </Link>
      </div>

      {queue.isLoading && (
        <p className="text-sm text-[#718096]">Loading queue…</p>
      )}

      {queue.isError && (
        <div className="bg-[#FEE2E2] border border-[#EF4444] rounded p-4">
          <p className="text-sm text-[#991B1B]">
            Failed to load pending reviews.
          </p>
        </div>
      )}

      {queue.data && queue.data.length === 0 && <EmptyState />}

      {queue.data && queue.data.length > 0 && (
        <>
          <p className="text-xs text-[#718096] mb-3">
            {queue.data.length} scan{queue.data.length === 1 ? '' : 's'} awaiting decision
          </p>
          {queue.data.map((scan) => (
            <PendingReviewRow key={scan.id} scan={scan} />
          ))}
        </>
      )}
    </div>
  )
}
