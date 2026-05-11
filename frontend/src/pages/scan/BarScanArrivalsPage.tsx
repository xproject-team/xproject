/**
 * BarScanArrivalsPage — Mode B (Manager DISPATCH).
 *
 * The page Federico the Manager opens on his phone during a live event,
 * pointed at the bar he's running. Each bottle physically arriving at
 * his bar gets scanned; the system records a DISPATCH against his bar
 * and the live event. Server-side allocation tables drop their
 * available stock; warehouse_inventory drops their on-hand count.
 *
 * Composition: this is mostly orchestration code. The components built
 * in Step 6.6.1 do the actual scanning, feedback, and history-row
 * rendering. This page is the assembly + guard rails + state shell.
 *
 * Route: /scan/arrivals  (wired in Step 6.8).
 * Permission: canScanArrivalsAtBar  (Manager + Owner per Step 6.5).
 *
 * ─── Eight Sundance-safety properties enforced at the page level ─────
 *   1. Manual fallback always one tap                   → BottleScanCard
 *   2. Pre-scoped to operator's bar                     → this page
 *   3. Pre-scoped to live event                         → this page
 *   4. Idempotent every scan                            → BottleScanCard
 *   5. Visible scan history (last 10)                   → this page
 *   6. Loud network failures                            → this page header
 *   7. No destructive controls                          → append-only
 *   8. Zero new dependencies                            → all in-tree
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import { usePermissions } from '@/features/auth/usePermissions'
import { useLiveEvent } from '@/features/dashboard/hooks'
import { useBars } from '@/features/bars/hooks'
import {
  useScanQueueAutoDrain,
  useScanQueueStatus,
  useVoidScan,
  type ScanResponse,
} from '@/features/warehouse/useWarehouse'
import { BottleScanCard } from '@/features/warehouse/scanner/BottleScanCard'
import {
  ScanHistoryRow,
  type ScanHistoryRowData,
} from '@/features/warehouse/scanner/ScanHistoryRow'
import { playUndoFeedback } from '@/features/warehouse/scanner/feedback'

const HISTORY_MAX_ROWS = 10
const TICK_INTERVAL_MS = 1000

// ─── Guard / error states ──────────────────────────────────────────────────

function ScanPageShell({
  title,
  subtitle,
  message,
}: {
  title: string
  subtitle?: string
  message: string
}) {
  return (
    <div className="max-w-2xl mx-auto p-6">
      <header className="mb-6">
        <Link
          to="/dashboard"
          className="text-sm text-[#1E5A8D] hover:underline mb-2 inline-block"
        >
          ← Back
        </Link>
        <h1 className="text-xl font-bold text-[#1A202C]">{title}</h1>
        {subtitle && (
          <p className="text-sm text-[#718096] mt-0.5">{subtitle}</p>
        )}
      </header>
      <div className="bg-[#FEF3C7] border border-[#F59E0B] rounded-lg p-4 text-sm text-[#92400E]">
        {message}
      </div>
    </div>
  )
}

// ─── Sync status indicator (top-right of the page header) ──────────────────

function SyncIndicator({ userId }: { userId: string | null }) {
  const status = useScanQueueStatus(userId)
  if (!userId) return null
  if (status.failed > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#B91C1C]">
        <span className="h-2 w-2 rounded-full bg-[#B91C1C]" aria-hidden />
        {status.failed} failed
      </span>
    )
  }
  if (status.pending > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#A16207]">
        <span className="h-2 w-2 rounded-full bg-[#F59E0B]" aria-hidden />
        {status.pending} pending sync
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-[#10B981]">
      <span className="h-2 w-2 rounded-full bg-[#10B981]" aria-hidden />
      online
    </span>
  )
}

// ─── Main page component ───────────────────────────────────────────────────

export function BarScanArrivalsPage() {
  const { user } = useAuth()
  const permissions = usePermissions()
  const liveEvent = useLiveEvent()

  const userId = user?.id ?? null
  const role = user?.role ?? null
  const isOwner = role === 'owner'

  // We pull all bars for the live event so we can:
  //  (a) render the operator's bar name in the header
  //  (b) fall back to "first bar" when an Owner is testing the page
  const eventId = liveEvent.data?.id ?? null
  const barsQuery = useBars(eventId ?? undefined)

  // Effective bar id:
  //   Manager / Bartender  → their assignedBarId (the only legal value)
  //   Owner                → first bar in the event (testing convenience,
  //                          Option O1 per Phase 6.6.2 design discussion)
  const effectiveBarId = useMemo<string | null>(() => {
    if (permissions.assignedBarId) return permissions.assignedBarId
    if (isOwner && barsQuery.data && barsQuery.data.length > 0) {
      return barsQuery.data[0].id
    }
    return null
  }, [permissions.assignedBarId, isOwner, barsQuery.data])

  const effectiveBarName = useMemo<string | null>(() => {
    if (!effectiveBarId || !barsQuery.data) return null
    const found = barsQuery.data.find((b) => b.id === effectiveBarId)
    return found?.name ?? null
  }, [effectiveBarId, barsQuery.data])

  // ─── Auto-drain the offline queue on mount + on 'online' event ────────
  useScanQueueAutoDrain(userId)

  // ─── History list state ───────────────────────────────────────────────
  const [history, setHistory] = useState<ScanHistoryRowData[]>([])
  const [now, setNow] = useState<number>(() => Date.now())

  // Shared 1-second tick drives all rows' Undo countdowns. ONE timer
  // for the whole list, not N timers.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), TICK_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  const appendRow = useCallback((row: ScanHistoryRowData) => {
    setHistory((prev) => [row, ...prev].slice(0, HISTORY_MAX_ROWS))
  }, [])

  // ─── Wire BottleScanCard callbacks → history rows ─────────────────────

  const onScanSucceeded = useCallback(
    (scan: ScanResponse) => {
      appendRow({ kind: 'synced', scan, createdAt: Date.now() })
    },
    [appendRow],
  )

  const onScanQueued = useCallback(
    (info: {
      clientEventId: string
      productName: string | null
      barcodeRaw: string
    }) => {
      appendRow({
        kind: 'queued',
        clientEventId: info.clientEventId,
        productName: info.productName,
        barcodeRaw: info.barcodeRaw,
        createdAt: Date.now(),
      })
    },
    [appendRow],
  )

  const onScanFailed = useCallback(
    (errorMessage: string, productName: string | null) => {
      appendRow({
        kind: 'failed',
        clientEventId: 'unsubmitted',
        productName,
        barcodeRaw: null,
        errorMessage,
        createdAt: Date.now(),
      })
    },
    [appendRow],
  )

  // ─── Undo wiring ──────────────────────────────────────────────────────

  const voidScan = useVoidScan()
  const handleUndo = useCallback(
    async (scanId: string) => {
      try {
        const voided = await voidScan.mutateAsync(scanId)
        // Replace the matching synced row with a voided row in-place
        setHistory((prev) =>
          prev.map((r) =>
            r.kind === 'synced' && r.scan.id === scanId
              ? { kind: 'voided', scan: voided, createdAt: r.createdAt }
              : r,
          ),
        )
        playUndoFeedback()
      } catch {
        // Failure is rare (server allows 5-minute window vs UI's 5s).
        // If it happens, leave the row as-is; user can scan a counter
        // ADJUSTMENT via Owner later. We don't surface a toast here
        // because the row stays visible — operator can see Undo didn't
        // change the row.
      }
    },
    [voidScan],
  )

  // ─── Guard renders ────────────────────────────────────────────────────

  if (liveEvent.isLoading || barsQuery.isLoading) {
    return (
      <ScanPageShell
        title="Scan Arrivals"
        message="Loading scanner…"
      />
    )
  }

  if (!liveEvent.data) {
    return (
      <ScanPageShell
        title="Scan Arrivals"
        message="No event is currently live. The scanner is disabled until an event starts."
      />
    )
  }

  if (!effectiveBarId) {
    return (
      <ScanPageShell
        title="Scan Arrivals"
        subtitle={liveEvent.data.name}
        message="Your account isn't assigned to a bar yet. Contact your Owner to fix this."
      />
    )
  }

  // ─── Happy path ───────────────────────────────────────────────────────

  const liveEventName = liveEvent.data.name
  const barLabel = effectiveBarName ?? 'Your Bar'

  return (
    <div className="max-w-2xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <Link
            to="/dashboard"
            className="text-sm text-[#1E5A8D] hover:underline mb-2 inline-block"
          >
            ← Back
          </Link>
          <h1 className="text-xl sm:text-2xl font-bold text-[#1A202C] leading-tight">
            Scan Arrivals — {barLabel}
          </h1>
          <p className="text-sm text-[#718096] mt-0.5">
            {liveEventName}
            {isOwner && permissions.assignedBarId === null && (
              <span className="ml-1 text-[11px] text-[#A16207]">
                (Owner view — first bar)
              </span>
            )}
          </p>
        </div>
        <div className="pt-1">
          <SyncIndicator userId={userId} />
        </div>
      </header>

      {/* Scanner card */}
      <BottleScanCard
        scanType="DISPATCH"
        eventId={liveEvent.data.id}
        barId={effectiveBarId}
        tenantId={userId ?? ''}
        onScanSucceeded={onScanSucceeded}
        onScanQueued={onScanQueued}
        onScanFailed={onScanFailed}
      />

      {/* History list */}
      <section className="mt-6">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-2">
          Recent scans
        </h2>
        {history.length === 0 ? (
          <p className="text-sm text-[#A0AEC0] py-6 text-center bg-[#F7FAFC] rounded-lg border border-dashed border-[#E2E8F0]">
            No scans yet. Point the camera at a bottle's barcode, or type
            it manually above.
          </p>
        ) : (
          <div className="bg-white rounded-lg border border-[#E2E8F0] overflow-hidden">
            {history.map((row, idx) => (
              <ScanHistoryRow
                key={
                  row.kind === 'synced' || row.kind === 'voided'
                    ? row.scan.id
                    : `${row.kind}:${row.clientEventId}:${idx}`
                }
                row={row}
                now={now}
                onUndo={handleUndo}
                voiding={voidScan.isPending}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
