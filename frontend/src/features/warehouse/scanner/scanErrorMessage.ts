/**
 * extractScanErrorMessage — pull the backend's actual reason a scan
 * failed out of an Axios error, instead of Axios's own generic
 * "Request failed with status code 409" sentence.
 *
 * The backend returns a structured 4xx body — HTTPException(detail=
 * {"error": "...", "message": "..."}) — e.g. AllocationNotFoundError's
 * 409: {"detail": {"error": "allocation_not_found", "message": "No
 * allocation found for event ... Configure stock before dispatching."}}.
 * That message is the whole point: the operator needs to see WHY the
 * scan failed, not just that it did.
 *
 * Split into its own dependency-free module (rather than living inline
 * in BottleScanCard.tsx) so it stays trivially unit-testable without
 * dragging html5-qrcode/React Query into the test environment.
 */
export function extractScanErrorMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string' && detail.trim() !== '') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string' && message.trim() !== '') return message
    }
  }
  return err instanceof Error ? err.message : 'Scan submission failed. Try again.'
}
