/**
 * MetricsGrid — summary grid of key post-event metrics (total sales, top SKUs, anomaly count).
 */
export function MetricsGrid() {
  // TODO: use useReport hook and render metric cards
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {['Total Sales', 'Top SKU', 'Anomalies', 'Avg Consumption'].map((label) => (
        <div key={label} className="bg-white border border-[#E2E8F0] rounded-lg p-4">
          <p className="text-xs text-[#4A5568] uppercase tracking-wide">{label}</p>
          <p className="text-xl font-bold text-[#1A202C] mt-1">—</p>
        </div>
      ))}
    </div>
  )
}
