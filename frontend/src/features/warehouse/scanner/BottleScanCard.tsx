/**
 * BottleScanCard — the single-purpose scanner control.
 *
 * Knows ONE scan_type at a time (DISPATCH or CONSUMED). The parent page
 * picks which mode this card represents and guarantees the event/bar
 * context is non-null. The card is a pure I/O surface: barcode in (via
 * camera OR manual input), callback out.
 *
 * Reused by BarScanArrivalsPage (Manager Mode B, scanType='DISPATCH')
 * and BarScanEmptiesPage (Bartender Mode C, scanType='CONSUMED'). The
 * only difference between the two pages is the prop value.
 *
 * ─── Sundance-safety properties enforced here ──────────────────────────
 *   1. Manual fallback ALWAYS visible (input field rendered next to the
 *      viewport, NOT behind a toggle). Camera failure is never a dead end.
 *   2. Camera permission denial flips to MANUAL_ONLY state silently —
 *      operator can keep working with the typed input.
 *   3. Idempotent every scan via useSubmitScanWithQueue (which auto-
 *      injects client_event_id; server dedupes by (tenant, UUID)).
 *   4. Same-barcode-within-2s dedup defeats camera multi-fire bursts.
 *   5. Audio + haptic + visual flash on every result (success AND fail),
 *      two-of-three redundancy from feedback.ts.
 *   6. Audio primed on first user gesture (camera permission tap or
 *      manual submit) — satisfies iOS Safari's audio policy.
 *   7. In-flight guard prevents double-submit from rapid taps.
 *   8. NO destructive controls on this card. Undo lives in parent's
 *      history list. Card is append-only.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Html5Qrcode } from 'html5-qrcode'

import { extractScanErrorMessage } from './scanErrorMessage'

import { Button } from '@/shared/ui/Button'
import {
  useResolveBarcode,
  useSubmitScanWithQueue,
  type ScanType,
  type ScanResponse,
} from '@/features/warehouse/useWarehouse'
import {
  primeAudio,
  playSuccessFeedback,
  playFailureFeedback,
} from './feedback'

// ─── Props ───────────────────────────────────────────────────────────────────

export interface BottleScanCardProps {
  /** Hard-coded per page. Card never lets the user change this. */
  scanType: Extract<ScanType, 'DISPATCH' | 'CONSUMED'>
  /** Non-null guaranteed by parent (it checks useLiveEvent first). */
  eventId: string
  /** Non-null guaranteed by parent (assignedBarId from permissions). */
  barId: string
  /** Tenant id — required for the offline-queue's per-tenant key isolation. */
  tenantId: string

  /** Server accepted the scan, returned a full row. */
  onScanSucceeded: (scan: ScanResponse) => void
  /** Network was unreachable; scan went to the localStorage queue. */
  onScanQueued: (info: {
    clientEventId: string
    productName: string | null
    barcodeRaw: string
  }) => void
  /** Server rejected the scan (4xx) OR barcode resolution failed. */
  onScanFailed: (errorMessage: string, productName: string | null) => void

  /** Optional disable — parent uses this when a confirm dialog is open
   *  or during teardown. Camera continues; submissions are blocked. */
  disabled?: boolean
}

// ─── Internal state ──────────────────────────────────────────────────────────

type CameraState = 'requesting' | 'live' | 'manual_only'

type FlashState = 'idle' | 'success' | 'failure'

const ELEMENT_ID = 'xproject-bottle-scan-viewport'
const DEDUP_WINDOW_MS = 2000   // same barcode within 2s = ignored
const COOLDOWN_MS = 400        // feedback chip visible window before next scan
const FLASH_MS = 400           // visual flash duration

// ─── Component ───────────────────────────────────────────────────────────────

export function BottleScanCard({
  scanType,
  eventId,
  barId,
  tenantId,
  onScanSucceeded,
  onScanQueued,
  onScanFailed,
  disabled = false,
}: BottleScanCardProps) {
  const [cameraState, setCameraState] = useState<CameraState>('requesting')
  const [flash, setFlash] = useState<FlashState>('idle')
  const [manualInput, setManualInput] = useState('')

  const scannerRef = useRef<Html5Qrcode | null>(null)
  const inFlightRef = useRef<boolean>(false)
  const lastBarcodeRef = useRef<{ code: string; at: number } | null>(null)

  const resolveBarcode = useResolveBarcode()
  const submitScan = useSubmitScanWithQueue(tenantId)

  // ─── Visual flash helper ─────────────────────────────────────────────────

  const triggerFlash = useCallback((kind: 'success' | 'failure') => {
    setFlash(kind)
    setTimeout(() => setFlash('idle'), FLASH_MS)
  }, [])

  // ─── The single decode→submit pipeline (shared by camera + manual) ───────

  const processBarcode = useCallback(
    async (decodedText: string, source: 'camera' | 'manual') => {
      // Dedup: ignore same-barcode-within-window (camera multi-fire defense).
      // We dedup only for camera; manual submits are deliberate operator
      // actions and never get deduped (Federico might actually want to scan
      // the same product 5 times in a row).
      const now = Date.now()
      if (source === 'camera') {
        if (
          lastBarcodeRef.current &&
          lastBarcodeRef.current.code === decodedText &&
          now - lastBarcodeRef.current.at < DEDUP_WINDOW_MS
        ) {
          return
        }
        lastBarcodeRef.current = { code: decodedText, at: now }
      }

      // In-flight guard — prevents double-tap or simultaneous camera+manual.
      if (inFlightRef.current) return
      if (disabled) return
      inFlightRef.current = true

      try {
        // Step 1 — resolve barcode to product (server lookup)
        const resolved = await resolveBarcode.mutateAsync({
          barcode: decodedText,
        })

        if (resolved.status === 'unknown' || !resolved.product_id) {
          triggerFlash('failure')
          playFailureFeedback()
          onScanFailed(
            `Unknown barcode: ${decodedText}. Add to catalog first.`,
            null,
          )
          return
        }

        // Step 2 — submit the scan (auto-injects UUID via useSubmitScanWithQueue)
        const result = await submitScan.mutateAsync({
          scan_type: scanType,
          product_id: resolved.product_id,
          barcode_raw: decodedText,
          qty: 1,
          event_id: eventId,
          bar_id: barId,
        })

        // Step 3 — react to the outcome
        if ('queued' in result) {
          // Offline path: scan in localStorage, will drain on reconnect.
          // Treat as a soft-success — operator should see ⏳ pending,
          // not an error. Audio is still success-toned (their action
          // worked from their POV).
          triggerFlash('success')
          playSuccessFeedback()
          onScanQueued({
            clientEventId: result.client_event_id,
            productName: resolved.product_name,
            barcodeRaw: decodedText,
          })
        } else {
          // Happy path: server accepted, returned full row.
          triggerFlash('success')
          playSuccessFeedback()
          onScanSucceeded(result)
        }
      } catch (err: unknown) {
        triggerFlash('failure')
        playFailureFeedback()
        onScanFailed(extractScanErrorMessage(err), null)
      } finally {
        // Brief cooldown so the user sees the flash, then ready for next scan.
        setTimeout(() => {
          inFlightRef.current = false
        }, COOLDOWN_MS)
      }
    },
    [
      scanType,
      eventId,
      barId,
      disabled,
      resolveBarcode,
      submitScan,
      onScanSucceeded,
      onScanQueued,
      onScanFailed,
      triggerFlash,
    ],
  )

  // ─── Camera lifecycle ────────────────────────────────────────────────────

  const stopCamera = useCallback(async () => {
    if (scannerRef.current) {
      try {
        if (scannerRef.current.isScanning) {
          await scannerRef.current.stop()
        }
        scannerRef.current.clear()
      } catch {
        // Silent — we're tearing down
      }
      scannerRef.current = null
    }
  }, [])

  const startCamera = useCallback(async () => {
    setCameraState('requesting')
    try {
      const scanner = new Html5Qrcode(ELEMENT_ID)
      scannerRef.current = scanner
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 8, qrbox: { width: 240, height: 160 } },
        (decodedText) => {
          // Fire-and-forget; processBarcode handles its own errors.
          void processBarcode(decodedText, 'camera')
        },
        () => {
          // Per-frame decode failure — silent; the scanner keeps trying.
        },
      )
      setCameraState('live')
      // Once camera permission was granted, the surrounding tap satisfies
      // iOS's user-gesture rule for audio. Prime now so the FIRST scan's
      // beep isn't blocked.
      primeAudio()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      const isPermDenied =
        msg.toLowerCase().includes('permission') ||
        msg.toLowerCase().includes('notallowed')
      // Either way, we fall to manual-only — no dead end.
      setCameraState('manual_only')
      // eslint-disable-next-line no-console
      if (!isPermDenied) console.warn('Camera failed:', msg)
    }
  }, [processBarcode])

  useEffect(() => {
    void startCamera()
    return () => {
      void stopCamera()
    }
    // startCamera/stopCamera are stable via useCallback
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ─── Manual submit handler ───────────────────────────────────────────────

  const handleManualSubmit = useCallback(async () => {
    const trimmed = manualInput.trim()
    if (!trimmed) return
    // Prime audio on the first manual gesture too — covers the case
    // where the camera never started (e.g. desktop with no webcam).
    primeAudio()
    setManualInput('')
    await processBarcode(trimmed, 'manual')
  }, [manualInput, processBarcode])

  // ─── Render ──────────────────────────────────────────────────────────────

  const flashOverlay =
    flash === 'success'
      ? 'bg-[#10B981]/30'
      : flash === 'failure'
        ? 'bg-[#EF4444]/30'
        : 'bg-transparent'

  return (
    <div className="bg-white rounded-lg border border-[#E2E8F0] overflow-hidden">
      {/* Camera viewport — square aspect, rounded inside the card */}
      <div className="relative bg-[#1A202C] aspect-square">
        <div id={ELEMENT_ID} className="absolute inset-0" />

        {/* Flash overlay (success/failure) */}
        <div
          className={`absolute inset-0 pointer-events-none transition-opacity duration-200 ${flashOverlay}`}
          aria-hidden
        />

        {/* State-specific overlays */}
        {cameraState === 'requesting' && (
          <div className="absolute inset-0 flex items-center justify-center text-white text-sm">
            Starting camera…
          </div>
        )}
        {cameraState === 'manual_only' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-white text-center px-6 gap-3">
            <p className="text-sm">Camera unavailable.</p>
            <p className="text-xs text-[#CBD5E0]">
              Use the manual input below — same effect.
            </p>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void startCamera()
              }}
            >
              Retry camera
            </Button>
          </div>
        )}
      </div>

      {/* Manual fallback — ALWAYS visible, not behind a toggle */}
      <div className="p-3 border-t border-[#E2E8F0]">
        <label
          htmlFor="bottle-scan-manual-input"
          className="block text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-2"
        >
          Or type the barcode
        </label>
        <div className="flex gap-2">
          <input
            id="bottle-scan-manual-input"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="e.g. 7501055309603"
            value={manualInput}
            onChange={(e) => setManualInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleManualSubmit()
            }}
            disabled={disabled}
            className="flex-1 px-3 py-2 text-sm border border-[#E2E8F0] rounded
                       focus:outline-none focus:border-[#1E5A8D] disabled:bg-[#F7FAFC]"
          />
          <Button
            variant="primary"
            size="lg"
            onClick={() => {
              void handleManualSubmit()
            }}
            disabled={disabled || manualInput.trim().length === 0}
          >
            Scan
          </Button>
        </div>
      </div>
    </div>
  )
}
