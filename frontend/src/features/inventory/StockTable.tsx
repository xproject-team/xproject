/**
 * StockTable — table of inventory items with quantity, unit, and stock-health indicator.
 */
import type { InventoryItemResponse } from '@/lib/types'

interface StockTableProps {
  items?: InventoryItemResponse[]
}

export function StockTable({ items = [] }: StockTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-xs text-[#4A5568] uppercase bg-[#F7FAFC] border-b border-[#E2E8F0]">
          <tr>
            <th className="px-4 py-3">SKU</th>
            <th className="px-4 py-3">Name</th>
            <th className="px-4 py-3">Qty</th>
            <th className="px-4 py-3">Unit</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b border-[#E2E8F0]">
              <td className="px-4 py-3 font-mono">{item.sku}</td>
              <td className="px-4 py-3">{item.name}</td>
              <td className="px-4 py-3">{item.quantity}</td>
              <td className="px-4 py-3">{item.unit}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
