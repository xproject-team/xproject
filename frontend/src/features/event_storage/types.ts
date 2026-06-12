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
