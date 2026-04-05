/**
 * AlertPanel — scrollable list of active alerts with severity colour-coding.
 */
export function AlertPanel() {
  // TODO: use useAlerts hook and render AlertToast rows
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4">
      <h3 className="font-semibold text-[#1A202C] mb-3">Active Alerts</h3>
      <p className="text-sm text-[#4A5568]">No active alerts.</p>
    </div>
  )
}
