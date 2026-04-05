/**
 * WarehouseScanPage — barcode/QR scan interface with recent scan history.
 * Thin page: layout + composition only, no business logic.
 */

const MOCK_SCANS = [
  { id: 1, item: 'Absolut Vodka 1L',   action: 'Intake',    qty: 24, time: '18:30', by: 'Warehouse A' },
  { id: 2, item: 'Heineken 330ml',      action: 'Dispatch',  qty: 48, time: '18:15', by: 'Warehouse B' },
  { id: 3, item: 'Red Bull 250ml',      action: 'Intake',    qty: 36, time: '17:58', by: 'Warehouse A' },
  { id: 4, item: 'Tonic Water 500ml',   action: 'Dispatch',  qty: 12, time: '17:40', by: 'Warehouse A' },
  { id: 5, item: 'Hendricks Gin 700ml', action: 'Intake',    qty: 6,  time: '17:22', by: 'Warehouse B' },
]

export default function WarehouseScanPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[#1A202C]">Warehouse</h1>
        <p className="text-sm text-[#4A5568] mt-1">Scan barcodes to log stock intake and dispatch</p>
      </div>

      {/* Scanner area */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm p-8 mb-6 flex flex-col items-center gap-5">
        <div className="w-20 h-20 rounded-full bg-[#F7FAFC] border-2 border-[#E2E8F0] flex items-center justify-center">
          <svg className="w-9 h-9 text-[#1E5A8D]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4v1m0 14v1M4 12h1m14 0h1M6.343 6.343l.707.707M16.95 16.95l.707.707M6.343 17.657l.707-.707M16.95 7.05l.707-.707" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7V5a2 2 0 012-2h2M17 3h2a2 2 0 012 2v2M21 17v2a2 2 0 01-2 2h-2M7 21H5a2 2 0 01-2-2v-2" />
          </svg>
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-[#1A202C]">Ready to scan</p>
          <p className="text-xs text-[#4A5568] mt-0.5">Point camera at barcode or QR code</p>
        </div>
        <button className="bg-[#1E5A8D] hover:bg-[#174a78] text-white font-semibold px-8 py-3 rounded-xl transition-colors text-sm shadow-md">
          Scan Barcode
        </button>
        <div className="flex gap-3">
          <button className="text-xs text-[#4A5568] border border-[#E2E8F0] px-4 py-1.5 rounded-lg hover:bg-[#F7FAFC] transition-colors">
            Manual Entry
          </button>
          <button className="text-xs text-[#4A5568] border border-[#E2E8F0] px-4 py-1.5 rounded-lg hover:bg-[#F7FAFC] transition-colors">
            Scan QR Code
          </button>
        </div>
      </div>

      {/* Recent scans */}
      <div>
        <h2 className="text-base font-semibold text-[#1A202C] mb-3">Recent Scans</h2>
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F7FAFC]">
                <th className="text-left px-5 py-3 font-semibold text-[#4A5568]">Item</th>
                <th className="text-left px-5 py-3 font-semibold text-[#4A5568]">Action</th>
                <th className="text-right px-5 py-3 font-semibold text-[#4A5568]">Qty</th>
                <th className="text-left px-5 py-3 font-semibold text-[#4A5568]">Time</th>
                <th className="text-left px-5 py-3 font-semibold text-[#4A5568]">Scanned By</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_SCANS.map((scan, i) => (
                <tr
                  key={scan.id}
                  className={`border-b border-[#E2E8F0] last:border-0 hover:bg-[#F7FAFC] transition-colors ${i % 2 === 1 ? 'bg-[#FAFBFC]' : ''}`}
                >
                  <td className="px-5 py-3.5 font-medium text-[#1A202C]">{scan.item}</td>
                  <td className="px-5 py-3.5">
                    <span
                      className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                        scan.action === 'Intake'
                          ? 'bg-green-100 text-green-700 border border-green-200'
                          : 'bg-blue-100 text-blue-700 border border-blue-200'
                      }`}
                    >
                      {scan.action}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-[#1A202C]">{scan.qty}</td>
                  <td className="px-5 py-3.5 text-[#4A5568]">Today {scan.time}</td>
                  <td className="px-5 py-3.5 text-[#4A5568]">{scan.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
