/**
 * ScannerView — camera-based barcode/QR scanner using html5-qrcode.
 * On successful scan, calls useSubmitScan() to POST the result to the API.
 */
export function ScannerView() {
  // TODO: initialise Html5QrcodeScanner, wire to useSubmitScan mutation
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4 mb-4">
      <div id="qr-reader" className="w-full h-64 bg-[#F7FAFC] flex items-center justify-center">
        <p className="text-[#4A5568] text-sm">Scanner initialising…</p>
      </div>
    </div>
  )
}
