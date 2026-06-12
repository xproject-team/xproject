export interface SupplierProduct {
  id: string
  tenant_id: string
  supplier_name: string
  supplier_sku: string
  item_name: string
  category: string
  default_unit: string
  units_per_pack: number
  volume_per_unit_ml: number | null
  last_unit_price_eur: string | null
  created_at: string
  updated_at: string
}

export interface EventStockItem {
  id: string
  tenant_id: string
  event_id: string
  supplier_product_id: string
  qty_received: string
  unit: string
  unit_price_eur: string | null
  discount_amount_eur: string | null
  line_total_eur: string | null
  vat_pct: number | null
  invoice_number: string | null
  invoice_date: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface EventStockItemCreate {
  supplier_product_id: string
  qty_received: string
  unit: string
  unit_price_eur?: string | null
  line_total_eur?: string | null
}

// ─── Storage summary (warehouse + inventory pages) ────────────────────

export interface StorageSummaryRow {
  supplier_product_id: string
  item_name: string
  category: string
  unit: string
  qty_received: string
  qty_allocated: string
  qty_available: string
  line_total_eur: string | null
}

export interface StorageSummary {
  event_id: string
  total_items: number
  total_qty_received: string
  total_qty_allocated: string
  total_line_value_eur: string | null
  by_category: Record<string, number>
  rows: StorageSummaryRow[]
}

// ─── Dispatch (event_stock_bar_allocations) ───────────────────────────

export interface DispatchCreate {
  supplier_product_id: string
  bar_id: string
  qty_allocated: string
  notes?: string | null
}

export interface DispatchResponse {
  id: string
  tenant_id: string
  event_id: string
  supplier_product_id: string
  bar_id: string
  qty_allocated: string
  dispatched_by_user_id: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface ActivityFeedRow {
  id: string
  qty_allocated: string
  item_name: string
  item_unit: string
  bar_name: string
  user_name: string | null
  user_role: string | null
  dispatched_at: string
}

export interface BarAllocationItem {
  supplier_product_id: string
  item_name: string
  unit: string
  qty_total_allocated: string
}

export interface BarAllocationSummary {
  bar_id: string
  bar_name: string
  items: BarAllocationItem[]
}
