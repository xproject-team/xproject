/**
 * ScanHistory — recent scan events table showing barcode, action, quantity, and timestamp.
 */
export function ScanHistory() {
  // TODO: use useScanHistory hook and render rows
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4">
      <h3 className="font-semibold text-[#1A202C] mb-3">Recent Scans</h3>
      <p className="text-sm text-[#4A5568]">No scans yet.</p>
    </div>
  )
}
