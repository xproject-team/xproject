/**
 * ScanHistoryRow — one row in the scanner page's "Last N scans" list.
 *
 * Pure presentation: no fetching, no state, no internal timers.
 * The parent page owns the list state AND the shared "now" tick that
 * decides whether the Undo button is still in-window.
 *
 * Sundance-safety properties enforced by this component:
 *   1. Discriminated union on `kind` means TypeScript exhaustive-checks
 *      every state. Adding a new state will fail to compile until
 *      every render path handles it.
 *   2. The row never throws on malformed data — null product, missing
 *      barcode, weird timestamps all fall back to "Scan recorded".
 *      A row that can't render correctly is a recoverable UI bug, not
 *      a page crash mid-rush.
 *   3. Undo button is only rendered when (a) kind is 'synced',
 *      (b) age ≤ 5 seconds, (c) parent provided onUndo. Server still
 *      gates with its own 5-minute window; UI's 5s is ergonomic.
 *   4. Tap-target on Undo is 44px high (Apple HIG minimum). A gloved
 *      Sundance thumb can hit it.
 */
import { type ScanResponse } from '@/features/warehouse/useWarehouse'

// ─── Public discriminated union — one row, many states ──────────────────────

/** A scan that the server accepted and returned a full row for. */
export interface SyncedRow {
  kind: 'synced'
  scan: ScanResponse
  /** ms-since-epoch when THIS UI placed the row in the list. Used for
   *  the 5-second Undo countdown — NOT scan.scanned_at, since clock
   *  skew between client and server would distort the window. */
  createdAt: number
}

/** A scan submitted while offline; sitting in the localStorage queue. */
export interface QueuedRow {
  kind: 'queued'
  clientEventId: string
  productName: string | null
  barcodeRaw: string | null
  createdAt: number
}

/** A scan whose drain attempts have all failed (terminal-failed in the queue). */
export interface FailedRow {
  kind: 'failed'
  clientEventId: string
  productName: string | null
  barcodeRaw: string | null
  errorMessage: string
  createdAt: number
}

/** A scan that was successfully voided via the 5-second Undo. */
export interface VoidedRow {
  kind: 'voided'
  scan: ScanResponse
  createdAt: number
}

export type ScanHistoryRowData = SyncedRow | QueuedRow | FailedRow | VoidedRow

// ─── Props ───────────────────────────────────────────────────────────────────

export interface ScanHistoryRowProps {
  row: ScanHistoryRowData
  /** Wall-clock from parent's shared 1-second tick. Used to compute
   *  whether the Undo button is still in its 5-second window. */
  now: number
  /** Window in ms during which Undo is offered. Default 5000. */
  undoWindowMs?: number
  /** Called when user taps Undo. Only invoked for 'synced' rows in window.
   *  Parent is responsible for then dispatching useVoidScan with this id. */
  onUndo?: (scanId: string) => void
  /** Disables the Undo button while a void mutation is in flight. */
  voiding?: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STATE_STYLE: Record<ScanHistoryRowData['kind'], string> = {
  synced: 'border-l-2 border-l-[#10B981]',
  queued: 'border-l-2 border-l-[#F59E0B]',
  failed: 'border-l-2 border-l-[#EF4444]',
  voided: 'border-l-2 border-l-[#3B82F6] opacity-60',
}

const STATE_ICON: Record<ScanHistoryRowData['kind'], string> = {
  synced: '✓',
  queued: '⏳',
  failed: '⚠',
  voided: '↶',
}

const STATE_ICON_COLOR: Record<ScanHistoryRowData['kind'], string> = {
  synced: 'text-[#10B981]',
  queued: 'text-[#F59E0B]',
  failed: 'text-[#EF4444]',
  voided: 'text-[#3B82F6]',
}

/** Format a ms-since-epoch as HH:MM in the user's locale. */
function formatTime(ms: number): string {
  try {
    return new Date(ms).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '--:--'
  }
}

/** Extract a display label for the bottle: prefer product_name, fall back
 *  to barcode, then to a generic placeholder. Never throws on null data.
 *  'failed' never falls back to "Scan recorded" — nothing WAS recorded;
 *  saying so was actively misleading about a scan that just errored out. */
export function rowLabel(row: ScanHistoryRowData): string {
  switch (row.kind) {
    case 'synced':
    case 'voided':
      return row.scan.product_name ?? row.scan.barcode_raw ?? 'Scan recorded'
    case 'queued':
      return row.productName ?? row.barcodeRaw ?? 'Scan recorded'
    case 'failed':
      return row.productName ?? row.barcodeRaw ?? 'Scan failed'
  }
}

/** Extract a scan id for the Undo callback. Only meaningful for synced. */
function syncedScanId(row: ScanHistoryRowData): string | null {
  return row.kind === 'synced' ? row.scan.id : null
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ScanHistoryRow({
  row,
  now,
  undoWindowMs = 5000,
  onUndo,
  voiding = false,
}: ScanHistoryRowProps) {
  const label = rowLabel(row)
  const time = formatTime(row.createdAt)
  const id = syncedScanId(row)
  const ageMs = now - row.createdAt
  const undoAvailable =
    row.kind === 'synced' &&
    id !== null &&
    onUndo !== undefined &&
    ageMs >= 0 &&
    ageMs < undoWindowMs &&
    !voiding

  const secondsRemaining = undoAvailable
    ? Math.max(0, Math.ceil((undoWindowMs - ageMs) / 1000))
    : 0

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2.5 border-b border-[#EDF2F7] last:border-b-0 bg-white ${STATE_STYLE[row.kind]}`}
    >
      {/* State icon */}
      <span
        className={`text-base ${STATE_ICON_COLOR[row.kind]} w-5 flex-shrink-0 text-center`}
        aria-hidden
      >
        {STATE_ICON[row.kind]}
      </span>

      {/* Timestamp */}
      <span className="text-xs font-mono text-[#718096] w-12 flex-shrink-0 tabular-nums">
        {time}
      </span>

      {/* Label + sub-text */}
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm truncate ${
            row.kind === 'voided'
              ? 'text-[#4A5568] line-through'
              : 'text-[#1A202C]'
          }`}
        >
          {label}
        </p>
        {row.kind === 'queued' && (
          <p className="text-[11px] text-[#A16207]">pending sync</p>
        )}
        {row.kind === 'failed' && (
          <p className="text-[11px] text-[#B91C1C] break-words">
            {row.errorMessage}
          </p>
        )}
        {row.kind === 'voided' && (
          <p className="text-[11px] text-[#3B82F6]">undone</p>
        )}
      </div>

      {/* Undo button — only for synced rows within the window */}
      {undoAvailable && id !== null && (
        <button
          type="button"
          onClick={() => onUndo?.(id)}
          disabled={voiding}
          className="h-11 px-3 min-w-[64px] text-xs font-semibold rounded-md
                     bg-[#EBF8FF] hover:bg-[#BEE3F8] active:bg-[#90CDF4]
                     text-[#1E5A8D] disabled:opacity-50 disabled:cursor-not-allowed
                     transition"
          aria-label={`Undo scan, ${secondsRemaining} seconds remaining`}
        >
          Undo {secondsRemaining}s
        </button>
      )}
    </div>
  )
}
