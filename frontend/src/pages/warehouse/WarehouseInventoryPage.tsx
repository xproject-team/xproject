/**
 * WarehouseInventoryPage — warehouse stock overview with item counts.
 * Thin page: layout + composition only, no business logic.
 */
import { StockTable } from '@/features/inventory/StockTable'

export default function WarehouseInventoryPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-[#1A202C] mb-4">Warehouse Inventory</h1>
      <StockTable />
    </div>
  )
}
