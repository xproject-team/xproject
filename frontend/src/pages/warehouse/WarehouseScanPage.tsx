/**
 * WarehouseScanPage — barcode/QR scanner interface for warehouse staff.
 * Thin page: layout + composition only, no business logic.
 */
import { ScannerView } from '@/features/warehouse/ScannerView'
import { ScanHistory } from '@/features/warehouse/ScanHistory'

export default function WarehouseScanPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-4">Warehouse Scan</h1>
      <ScannerView />
      <ScanHistory />
    </div>
  )
}
