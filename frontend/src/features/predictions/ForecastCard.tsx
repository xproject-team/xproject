/**
 * ForecastCard — displays the top predicted high-demand items for the next N hours.
 */
export function ForecastCard() {
  // TODO: use usePredictions, render top-5 SKUs with predicted demand and confidence bar
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4 mt-4">
      <h3 className="font-semibold text-[#1A202C] mb-3">Demand Forecast</h3>
      <p className="text-sm text-[#4A5568]">Predictions not yet available.</p>
    </div>
  )
}
