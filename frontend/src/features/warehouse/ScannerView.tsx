/**
 * ScannerView — camera-based barcode scanner with manual-entry fallback.
 *
 * Spec: docs/warehouse-module-spec.md §6 + §3.5.
 *
 * UX flow:
 *   1. User picks scan_type (role-aware buttons — see _BUTTONS_BY_ROLE)
 *   2. Camera permission prompt (browser native) on first activation
 *   3. Live camera preview; html5-qrcode decodes EAN/UPC/QR continuously
 *   4. On decode -> resolve_barcode -> show product chip -> auto-submit scan
 *   5. Manual fallback: 'Type instead' button reveals product dropdown
 *
 * Design decisions:
 *   - Camera owns the page while active. Manual entry is a sibling form
 *     hidden until toggled. Avoids two simultaneous input modes confusing users.
 *   - Continuous scanning: after a successful scan, beep/vibrate, brief
 *     'Scanned ✓' chip, then immediately ready for next bottle. Optimized
 *     for the bulk-intake use case (Marco scanning 200 vodka in a row).
 *   - Permission denial gracefully falls to manual mode. Never a dead end.
 *   - INSPECT mode is read-only — shows product info, doesn't submit a scan.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Html5Qrcode } from 'html5-qrcode'

import {
  useResolveBarcode,
  useSubmitScan,
  type ScanType,
  type ScannerRole,
  type BarcodeResolveResponse,
} from '@/features/warehouse/useWarehouse'

// ─── Role-aware scan-type matrix (mirrors scan_service.py) ──────────────────
// Two-role model: Manager absorbed the warehouse-execution scans (INTAKE/
// DISPATCH/RETURN) from the retired warehouse_keeper entry. CONSUMED is a
// bar-floor action offered on /scan/empties, not here. Partial because
// ScannerRole keeps retired values for READING historical scans — they
// just have no buttons (the `?? []` lookup below).

const _BUTTONS_BY_ROLE: Partial<Record<ScannerRole, ScanType[]>> = {
  owner: ['INTAKE', 'DISPATCH', 'RETURN', 'ADJUSTMENT', 'INSPECT'],
  manager: ['INTAKE', 'DISPATCH', 'RETURN'],
}

const SCAN_TYPE_LABELS: Record<ScanType, string> = {
  INTAKE: 'Intake',
  DISPATCH: 'Dispatch',
  RETURN: 'Return',
  ADJUSTMENT: 'Adjust',
  INSPECT: 'Inspect',
  CONSUMED: 'Consumed',
}

const SCAN_TYPE_DESCRIPTIONS: Record<ScanType, string> = {
  INTAKE: 'Receiving stock from supplier',
  DISPATCH: 'Sending stock from warehouse to bar',
  RETURN: 'Returning stock from bar to warehouse',
  ADJUSTMENT: 'Owner correction (found / lost items)',
  INSPECT: 'Look up product info — read only',
  CONSUMED: 'Bottle used at the bar',
}

// ─── Component props ────────────────────────────────────────────────────────

export interface ScannerViewProps {
  /** Active scanner role — determines which scan_type buttons render. */
  role: ScannerRole
  /** When set, INTAKE scans link to this invoice and skip the picker. */
  invoiceId?: string | null
  /** When set, DISPATCH/RETURN/CONSUMED scans link to this event. */
  eventId?: string | null
  /** When set, DISPATCH/RETURN/CONSUMED scans target this bar. */
  barId?: string | null
  /** Called after every successful scan submission. Parent invalidates
   *  caches / updates progress bars. */
  onScanSubmitted?: (scanResult: {
    productName: string | null
    qty: number
    isUnexpected: boolean
  }) => void
}

// ─── State machine for the scanner ──────────────────────────────────────────

type CameraState =
  | 'idle' // before user picks a scan type
  | 'starting' // requesting camera permission
  | 'active' // camera running, decoding continuously
  | 'denied' // permission rejected; manual-only path
  | 'failed' // hardware error; manual-only path
  | 'manual' // user explicitly chose manual mode

const ELEMENT_ID = 'warehouse-scanner-camera'

// ─── Main component ──────────────────────────────────────────────────────────

export function ScannerView({
  role,
  invoiceId = null,
  eventId = null,
  barId = null,
  onScanSubmitted,
}: ScannerViewProps) {
  const [scanType, setScanType] = useState<ScanType | null>(null)
  const [cameraState, setCameraState] = useState<CameraState>('idle')
  const [recentResolve, setRecentResolve] =
    useState<BarcodeResolveResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [lastSubmitted, setLastSubmitted] = useState<{
    productName: string | null
    qty: number
    timestamp: number
  } | null>(null)

  const scannerRef = useRef<Html5Qrcode | null>(null)
  const inFlightRef = useRef<boolean>(false) // prevents double-submits
  const lastBarcodeRef = useRef<{ code: string; at: number } | null>(null)

  const resolveBarcode = useResolveBarcode()
  const submitScan = useSubmitScan()

  const allowedTypes = _BUTTONS_BY_ROLE[role] ?? []

  // ─── Camera lifecycle ─────────────────────────────────────────────────────

  const stopCamera = useCallback(async () => {
    if (scannerRef.current) {
      try {
        if (scannerRef.current.isScanning) {
          await scannerRef.current.stop()
        }
        scannerRef.current.clear()
      } catch {
        // Ignore — we're tearing down anyway
      }
      scannerRef.current = null
    }
  }, [])

  const startCamera = useCallback(
    async (chosenType: ScanType) => {
      setCameraState('starting')
      setErrorMsg(null)

      // INSPECT/ADJUSTMENT default to manual entry (no barcode workflow needed)
      if (chosenType === 'ADJUSTMENT') {
        setCameraState('manual')
        return
      }

      try {
        const scanner = new Html5Qrcode(ELEMENT_ID)
        scannerRef.current = scanner
        await scanner.start(
          { facingMode: 'environment' },
          {
            fps: 8,
            qrbox: { width: 240, height: 160 },
          },
          handleDecode,
          () => {
            // Per-frame decode failure — silent, the scanner keeps trying
          },
        )
        setCameraState('active')
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        if (
          msg.toLowerCase().includes('permission') ||
          msg.toLowerCase().includes('notallowed')
        ) {
          setCameraState('denied')
          setErrorMsg(
            'Camera permission denied. Use manual entry or update browser settings.',
          )
        } else {
          setCameraState('failed')
          setErrorMsg(`Camera failed: ${msg}`)
        }
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [], // handleDecode is stable (memoized below)
  )

  // ─── Decode handler ──────────────────────────────────────────────────────

  const handleDecode = useCallback(
    async (decodedText: string) => {
      // Debounce: ignore the same barcode within 1.5s (camera fires repeatedly
      // when bottle stays in frame).
      const now = Date.now()
      if (
        lastBarcodeRef.current &&
        lastBarcodeRef.current.code === decodedText &&
        now - lastBarcodeRef.current.at < 1500
      ) {
        return
      }
      lastBarcodeRef.current = { code: decodedText, at: now }

      if (inFlightRef.current) return
      if (!scanType) return

      inFlightRef.current = true
      try {
        // 1. Resolve barcode -> product
        const resolved = await resolveBarcode.mutateAsync({
          barcode: decodedText,
        })
        setRecentResolve(resolved)

        // 2. INSPECT mode never submits a scan — read-only
        if (scanType === 'INSPECT') {
          inFlightRef.current = false
          return
        }

        // 3. Submit the scan with full context
        const result = await submitScan.mutateAsync({
          scan_type: scanType,
          product_id: resolved.product_id,
          barcode_raw: decodedText,
          qty: 1,
          invoice_id: invoiceId,
          event_id: eventId,
          bar_id: barId,
        })

        setLastSubmitted({
          productName: resolved.product_name,
          qty: 1,
          timestamp: Date.now(),
        })
        onScanSubmitted?.({
          productName: resolved.product_name,
          qty: 1,
          isUnexpected: result.is_unexpected,
        })

        // Brief vibration on success (mobile only — no-op on desktop)
        if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
          navigator.vibrate?.(60)
        }
      } catch (err: unknown) {
        const msg =
          err instanceof Error ? err.message : 'Scan submission failed'
        setErrorMsg(msg)
      } finally {
        // Small cooldown so the user sees the feedback chip
        setTimeout(() => {
          inFlightRef.current = false
        }, 600)
      }
    },
    [
      scanType,
      invoiceId,
      eventId,
      barId,
      resolveBarcode,
      submitScan,
      onScanSubmitted,
    ],
  )

  // ─── Cleanup on unmount or scan-type switch ──────────────────────────────

  useEffect(() => {
    return () => {
      stopCamera()
    }
  }, [stopCamera])

  const handleScanTypeChoice = (t: ScanType) => {
    setScanType(t)
    setRecentResolve(null)
    setLastSubmitted(null)
    setErrorMsg(null)
    void startCamera(t)
  }

  const handleSwitchToManual = async () => {
    await stopCamera()
    setCameraState('manual')
  }

  const handleResetToTypePicker = async () => {
    await stopCamera()
    setScanType(null)
    setCameraState('idle')
    setRecentResolve(null)
    setErrorMsg(null)
    setLastSubmitted(null)
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  // Step 1: pick scan type (only allowed for current role)
  if (cameraState === 'idle' || scanType === null) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-6">
        <h2 className="text-lg font-bold text-[#1A202C] mb-1">Scan</h2>
        <p className="text-sm text-[#718096] mb-5">
          Pick the type of scan, then aim the camera at a barcode.
        </p>
        {allowedTypes.length === 0 ? (
          <p className="text-sm text-[#E53E3E]">
            Your role has no scanner permissions.
          </p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {allowedTypes.map((t) => (
              <button
                key={t}
                onClick={() => handleScanTypeChoice(t)}
                className="text-left p-4 border border-[#E2E8F0] rounded-lg
                           hover:border-[#1E5A8D] hover:bg-[#F7FAFC] transition"
              >
                <p className="font-semibold text-[#1A202C]">
                  {SCAN_TYPE_LABELS[t]}
                </p>
                <p className="text-xs text-[#718096] mt-0.5">
                  {SCAN_TYPE_DESCRIPTIONS[t]}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  // Step 2+: scanning UI (camera, manual, error states)
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-4">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-[#1E5A8D]">
            {SCAN_TYPE_LABELS[scanType]}
          </p>
          <p className="text-xs text-[#718096]">
            {SCAN_TYPE_DESCRIPTIONS[scanType]}
          </p>
        </div>
        <button
          onClick={handleResetToTypePicker}
          className="text-xs text-[#4A5568] hover:text-[#1A202C] underline"
        >
          Change type
        </button>
      </div>

      {/* Camera viewport (always rendered when not in manual mode) */}
      {cameraState !== 'manual' && (
        <div
          id={ELEMENT_ID}
          className="bg-black rounded-lg overflow-hidden mb-3"
          style={{ minHeight: 240 }}
        />
      )}

      {/* State-specific feedback */}
      {cameraState === 'starting' && (
        <p className="text-sm text-[#718096] py-2">Starting camera…</p>
      )}

      {cameraState === 'denied' && (
        <div className="bg-[#FEF3C7] border border-[#F59E0B] rounded p-3 mb-3">
          <p className="text-sm font-semibold text-[#92400E]">
            Camera permission denied
          </p>
          <p className="text-xs text-[#92400E] mt-1">{errorMsg}</p>
        </div>
      )}

      {cameraState === 'failed' && (
        <div className="bg-[#FEE2E2] border border-[#EF4444] rounded p-3 mb-3">
          <p className="text-sm font-semibold text-[#991B1B]">Camera error</p>
          <p className="text-xs text-[#991B1B] mt-1">{errorMsg}</p>
        </div>
      )}

      {/* Last-scanned chip — sticky for ~3 seconds */}
      {lastSubmitted && Date.now() - lastSubmitted.timestamp < 3000 && (
        <div className="bg-[#D1FAE5] border border-[#10B981] rounded p-2 mb-3 flex items-center gap-2">
          <span className="text-lg">✓</span>
          <p className="text-sm font-medium text-[#065F46]">
            Scanned: {lastSubmitted.productName ?? 'Unknown product'}
          </p>
        </div>
      )}

      {/* INSPECT-mode resolved-product display */}
      {scanType === 'INSPECT' && recentResolve && (
        <div className="bg-[#EBF8FF] border border-[#3B82F6] rounded p-3 mb-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-[#2B6CB0] mb-1">
            Product
          </p>
          {recentResolve.status === 'known' ? (
            <p className="text-sm font-bold text-[#1A202C]">
              {recentResolve.product_name}
            </p>
          ) : (
            <p className="text-sm text-[#718096]">
              Unknown barcode: {recentResolve.barcode}
            </p>
          )}
        </div>
      )}

      {errorMsg &&
        cameraState !== 'denied' &&
        cameraState !== 'failed' && (
          <div className="bg-[#FEE2E2] border border-[#EF4444] rounded p-2 mb-3">
            <p className="text-xs text-[#991B1B]">{errorMsg}</p>
          </div>
        )}

      {/* Manual entry fallback — always available */}
      {cameraState !== 'manual' ? (
        <button
          onClick={handleSwitchToManual}
          className="text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline"
        >
          Type instead (manual entry)
        </button>
      ) : (
        <ManualEntryForm
          scanType={scanType}
          invoiceId={invoiceId}
          eventId={eventId}
          barId={barId}
          onSubmitted={(name, qty, isUnexpected) => {
            setLastSubmitted({ productName: name, qty, timestamp: Date.now() })
            onScanSubmitted?.({ productName: name, qty, isUnexpected })
          }}
        />
      )}
    </div>
  )
}

// ─── Manual entry form (fallback) ────────────────────────────────────────────

interface ManualEntryFormProps {
  scanType: ScanType
  invoiceId: string | null
  eventId: string | null
  barId: string | null
  onSubmitted: (
    productName: string | null,
    qty: number,
    isUnexpected: boolean,
  ) => void
}

function ManualEntryForm({
  scanType,
  invoiceId,
  eventId,
  barId,
  onSubmitted,
}: ManualEntryFormProps) {
  const [barcode, setBarcode] = useState('')
  const [qty, setQty] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitScan = useSubmitScan()
  const resolveBarcode = useResolveBarcode()

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!barcode.trim() || qty < 1) return
    setSubmitting(true)
    setError(null)
    try {
      const resolved = await resolveBarcode.mutateAsync({ barcode: barcode.trim() })
      const result = await submitScan.mutateAsync({
        scan_type: scanType,
        product_id: resolved.product_id,
        barcode_raw: barcode.trim(),
        qty,
        invoice_id: invoiceId,
        event_id: eventId,
        bar_id: barId,
      })
      onSubmitted(resolved.product_name, qty, result.is_unexpected)
      setBarcode('')
      setQty(1)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="border-t border-[#E2E8F0] pt-3 mt-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-2">
        Manual entry
      </p>
      <div className="flex gap-2 mb-2">
        <input
          type="text"
          value={barcode}
          onChange={(e) => setBarcode(e.target.value)}
          placeholder="Barcode or product name"
          className="flex-1 text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
          required
        />
        <input
          type="number"
          value={qty}
          onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
          min={1}
          className="w-20 text-sm border border-[#E2E8F0] rounded-md px-3 py-2"
        />
      </div>
      {error && (
        <p className="text-xs text-[#E53E3E] mb-2">{error}</p>
      )}
      <button
        type="submit"
        disabled={submitting || !barcode.trim()}
        className="bg-[#1E5A8D] hover:bg-[#2C7AA6] disabled:bg-[#CBD5E0]
                   text-white text-sm font-semibold px-4 py-2 rounded-md transition"
      >
        {submitting ? 'Submitting…' : 'Submit scan'}
      </button>
    </form>
  )
}
