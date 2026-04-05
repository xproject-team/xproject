/**
 * mockData.ts — Single source of truth for all mock data.
 * Import from here in every component/hook.
 * When real APIs are ready, swap only the hooks — not the components.
 *
 * Field names match the Backend Bible database schema exactly.
 */

// ─── Interfaces ───────────────────────────────────────────────────────────────

export interface Event {
  id: number
  name: string
  date: string
  /** Backend ENUM: draft / active / live / completed */
  status: 'live' | 'active' | 'completed' | 'draft'
  /** Matches backend column expected_guest_count */
  expected_guest_count: number
  bars_count: number
  /** Matches backend column location */
  location: string
  created_at: string
  updated_at?: string
}

export interface DrinksBreakdown {
  B: number
  S: number
  P: number
  U: number
}

export type BarStatus = 'healthy' | 'warning' | 'critical'
export type BurnTrend = 'up' | 'stable' | 'down'

export interface Bar {
  id: number
  name: string
  status: BarStatus
  revenue: number
  drinks_sold: number
  drinks_breakdown: DrinksBreakdown
  initial_stock: number
  current_stock: number
  burn_rate: number
  burn_trend: BurnTrend
  /** Matches backend column time_to_depletion_min */
  time_to_depletion_min: number
  staff_count: number
  last_alert: string | null
}

export type AlertSeverity = 'critical' | 'warning' | 'anomaly'
/** Backend ENUM: depletion / anomaly / discrepancy / system */
export type AlertType = 'depletion' | 'anomaly' | 'discrepancy' | 'system'

export interface Alert {
  id: number
  event_id: number
  /** ISO time string e.g. "22:14" or full ISO datetime */
  created_at: string
  bar_name: string
  bar_id: number
  severity: AlertSeverity
  /** Matches backend column alert_type */
  alert_type: AlertType
  message: string
  /** Matches backend column is_acknowledged */
  is_acknowledged: boolean
}

export type ProductCategory = 'Spirits' | 'Beer' | 'Wine' | 'Mixers' | 'Other'
export type ProductStatus = 'healthy' | 'warning' | 'critical' | 'depleted'

export interface Product {
  id: number
  bar_id: number
  product_name: string
  category: ProductCategory
  current_stock: number
  initial_stock: number
  reorder_level: number
  status: ProductStatus
  consumption_rate: number
  estimated_depletion_minutes: number
  unit_price: number
}

export type WarehouseUnit = 'bottles' | 'cases' | 'kegs'

export interface WarehouseItem {
  id: number
  product_name: string
  brand: string
  category: ProductCategory
  quantity_in_warehouse: number
  allocated_to_event: number
  unit: WarehouseUnit
}

export type PredictionTrend = 'up' | 'stable' | 'down'

export interface PredictionItem {
  product: string
  predicted_demand_2h: number
  trend: PredictionTrend
  confidence: number
}

export interface Predictions {
  generated_at: string
  /** Backend ENUM: pre_event / live */
  model_type: 'pre_event' | 'live'
  predictions: PredictionItem[]
}

export type ProductTier = 'B' | 'S' | 'P' | 'U'
export type PaymentMethod = 'nfc' | 'card' | 'cash'

export interface Transaction {
  id: number
  event_id: number
  timestamp: string
  bar_id: number
  bar_name: string
  product_name: string
  product_tier: ProductTier
  quantity: number
  unit_price: number
  total_price: number
  payment_method: PaymentMethod
  pos_reference?: string
}

export type SenderRole = 'owner' | 'manager' | 'bartender'

export interface ChatMessage {
  id: number
  sender_role: SenderRole
  sender_name: string
  bar_id: number | null
  bar_name: string | null
  message: string
  timestamp: string
  read: boolean
}

// ─── 1. MOCK_EVENT ────────────────────────────────────────────────────────────

export const MOCK_EVENT: Event = {
  id: 1,
  name: 'Sundance 2026',
  date: '2026-06-15',
  status: 'live',
  expected_guest_count: 350,
  bars_count: 4,
  location: 'Villa Roma',
  created_at: '2026-06-01',
}

// ─── 1b. MOCK_EVENTS (list) ───────────────────────────────────────────────────

export const MOCK_EVENTS: Event[] = [
  {
    id: 1,
    name: 'Sundance 2026',
    date: '2026-06-15',
    status: 'live',
    expected_guest_count: 350,
    bars_count: 4,
    location: 'Villa Roma',
    created_at: '2026-06-01',
  },
  {
    id: 2,
    name: 'Summer Gala',
    date: '2026-07-20',
    status: 'draft',
    expected_guest_count: 200,
    bars_count: 3,
    location: 'Rooftop Terrace',
    created_at: '2026-03-15',
  },
  {
    id: 3,
    name: 'NYE Party 2026',
    date: '2026-12-31',
    status: 'draft',
    expected_guest_count: 500,
    bars_count: 6,
    location: 'Grand Ballroom',
    created_at: '2026-03-20',
  },
]

// ─── 2. MOCK_BARS ─────────────────────────────────────────────────────────────

export const MOCK_BARS: Bar[] = [
  {
    id: 1,
    name: 'Main Bar',
    status: 'healthy',
    revenue: 8240,
    drinks_sold: 156,
    drinks_breakdown: { B: 72, S: 44, P: 28, U: 12 },
    initial_stock: 60,
    current_stock: 45,
    burn_rate: 4.2,
    burn_trend: 'stable',
    time_to_depletion_min: 643,
    staff_count: 3,
    last_alert: null,
  },
  {
    id: 2,
    name: 'VIP Lounge',
    status: 'warning',
    revenue: 7890,
    drinks_sold: 112,
    drinks_breakdown: { B: 18, S: 30, P: 42, U: 22 },
    initial_stock: 50,
    current_stock: 18,
    burn_rate: 5.1,
    burn_trend: 'up',
    time_to_depletion_min: 52,
    staff_count: 2,
    last_alert: 'Champagne approaching reorder level',
  },
  {
    id: 3,
    name: 'Pool Bar',
    status: 'healthy',
    revenue: 4120,
    drinks_sold: 134,
    drinks_breakdown: { B: 38, S: 52, P: 30, U: 14 },
    initial_stock: 55,
    current_stock: 38,
    burn_rate: 3.8,
    burn_trend: 'stable',
    time_to_depletion_min: 600,
    staff_count: 2,
    last_alert: null,
  },
  {
    id: 4,
    name: 'DJ Booth',
    status: 'critical',
    revenue: 4100,
    drinks_sold: 85,
    drinks_breakdown: { B: 14, S: 26, P: 30, U: 15 },
    initial_stock: 45,
    current_stock: 8,
    burn_rate: 6.3,
    burn_trend: 'up',
    time_to_depletion_min: 76,
    staff_count: 2,
    last_alert: 'Vodka critically low',
  },
]

// ─── 3. MOCK_ALERTS ───────────────────────────────────────────────────────────

export const MOCK_ALERTS: Alert[] = [
  {
    id: 1,
    event_id: 1,
    created_at: '22:14',
    bar_name: 'DJ Booth',
    bar_id: 4,
    severity: 'critical',
    alert_type: 'depletion',
    message: 'Vodka stock critically low (3 bottles remaining)',
    is_acknowledged: false,
  },
  {
    id: 2,
    event_id: 1,
    created_at: '22:08',
    bar_name: 'VIP Lounge',
    bar_id: 2,
    severity: 'warning',
    alert_type: 'depletion',
    message: 'Champagne approaching reorder threshold',
    is_acknowledged: false,
  },
  {
    id: 3,
    event_id: 1,
    created_at: '21:55',
    bar_name: 'Main Bar',
    bar_id: 1,
    severity: 'anomaly',
    alert_type: 'anomaly',
    message: 'Unusual spike in beer consumption detected',
    is_acknowledged: false,
  },
  {
    id: 4,
    event_id: 1,
    created_at: '21:42',
    bar_name: 'DJ Booth',
    bar_id: 4,
    severity: 'critical',
    alert_type: 'depletion',
    message: 'Tonic water depleted',
    is_acknowledged: false,
  },
  {
    id: 5,
    event_id: 1,
    created_at: '21:30',
    bar_name: 'Pool Bar',
    bar_id: 3,
    severity: 'warning',
    alert_type: 'depletion',
    message: 'Ice supply below 40%',
    is_acknowledged: true,
  },
  {
    id: 6,
    event_id: 1,
    created_at: '21:15',
    bar_name: 'VIP Lounge',
    bar_id: 2,
    severity: 'warning',
    alert_type: 'depletion',
    message: 'Premium gin below reorder level',
    is_acknowledged: true,
  },
  {
    id: 7,
    event_id: 1,
    created_at: '20:45',
    bar_name: 'Main Bar',
    bar_id: 1,
    severity: 'anomaly',
    alert_type: 'anomaly',
    message: 'Revenue deviation -18% from prediction',
    is_acknowledged: true,
  },
  {
    id: 8,
    event_id: 1,
    created_at: '20:30',
    bar_name: 'Pool Bar',
    bar_id: 3,
    severity: 'critical',
    alert_type: 'depletion',
    message: 'Coconut water depleted — 0 units remaining',
    is_acknowledged: false,
  },
  {
    id: 9,
    event_id: 1,
    created_at: '20:10',
    bar_name: 'Main Bar',
    bar_id: 1,
    severity: 'warning',
    alert_type: 'depletion',
    message: 'Lime juice approaching reorder level (8 units)',
    is_acknowledged: false,
  },
  {
    id: 10,
    event_id: 1,
    created_at: '19:55',
    bar_name: 'VIP Lounge',
    bar_id: 2,
    severity: 'anomaly',
    alert_type: 'anomaly',
    message: 'Premium spirits consumption 2.3× above predicted rate',
    is_acknowledged: false,
  },
]

// ─── 4. MOCK_PRODUCTS ─────────────────────────────────────────────────────────

export const MOCK_PRODUCTS: Product[] = [
  // Main Bar (bar_id: 1)
  { id: 1,  bar_id: 1, product_name: 'Heineken',          category: 'Beer',    current_stock: 48, initial_stock: 60, reorder_level: 15, status: 'healthy',  consumption_rate: 3.8, estimated_depletion_minutes: 758, unit_price: 6.0  },
  { id: 2,  bar_id: 1, product_name: 'Absolut Vodka',     category: 'Spirits', current_stock: 12, initial_stock: 20, reorder_level: 5,  status: 'warning',  consumption_rate: 2.1, estimated_depletion_minutes: 343, unit_price: 9.5  },
  { id: 3,  bar_id: 1, product_name: 'Jack Daniel\'s',    category: 'Spirits', current_stock: 9,  initial_stock: 15, reorder_level: 4,  status: 'warning',  consumption_rate: 1.8, estimated_depletion_minutes: 300, unit_price: 10.0 },
  { id: 4,  bar_id: 1, product_name: 'Tonic Water',       category: 'Mixers',  current_stock: 36, initial_stock: 48, reorder_level: 12, status: 'healthy',  consumption_rate: 4.2, estimated_depletion_minutes: 514, unit_price: 3.0  },
  { id: 5,  bar_id: 1, product_name: 'House Red Wine',    category: 'Wine',    current_stock: 22, initial_stock: 30, reorder_level: 8,  status: 'healthy',  consumption_rate: 1.4, estimated_depletion_minutes: 943, unit_price: 8.0  },
  { id: 6,  bar_id: 1, product_name: 'Lime Juice',        category: 'Mixers',  current_stock: 8,  initial_stock: 24, reorder_level: 6,  status: 'warning',  consumption_rate: 2.5, estimated_depletion_minutes: 192, unit_price: 2.5  },

  // VIP Lounge (bar_id: 2)
  { id: 7,  bar_id: 2, product_name: 'Moët & Chandon',    category: 'Wine',    current_stock: 6,  initial_stock: 24, reorder_level: 6,  status: 'critical', consumption_rate: 2.8, estimated_depletion_minutes: 129, unit_price: 45.0 },
  { id: 8,  bar_id: 2, product_name: 'Hendrick\'s Gin',   category: 'Spirits', current_stock: 4,  initial_stock: 12, reorder_level: 3,  status: 'critical', consumption_rate: 1.9, estimated_depletion_minutes: 126, unit_price: 12.0 },
  { id: 9,  bar_id: 2, product_name: 'Grey Goose Vodka',  category: 'Spirits', current_stock: 8,  initial_stock: 15, reorder_level: 4,  status: 'warning',  consumption_rate: 2.2, estimated_depletion_minutes: 218, unit_price: 14.0 },
  { id: 10, bar_id: 2, product_name: 'Fever-Tree Tonic',  category: 'Mixers',  current_stock: 18, initial_stock: 36, reorder_level: 9,  status: 'warning',  consumption_rate: 3.5, estimated_depletion_minutes: 309, unit_price: 5.0  },
  { id: 11, bar_id: 2, product_name: 'Perrier-Jouët',     category: 'Wine',    current_stock: 3,  initial_stock: 12, reorder_level: 3,  status: 'critical', consumption_rate: 1.5, estimated_depletion_minutes: 120, unit_price: 65.0 },
  { id: 12, bar_id: 2, product_name: 'Cointreau',         category: 'Spirits', current_stock: 5,  initial_stock: 8,  reorder_level: 2,  status: 'warning',  consumption_rate: 1.2, estimated_depletion_minutes: 250, unit_price: 11.0 },

  // Pool Bar (bar_id: 3)
  { id: 13, bar_id: 3, product_name: 'Corona Extra',      category: 'Beer',    current_stock: 40, initial_stock: 60, reorder_level: 12, status: 'healthy',  consumption_rate: 4.5, estimated_depletion_minutes: 533, unit_price: 6.5  },
  { id: 14, bar_id: 3, product_name: 'Bacardi Rum',       category: 'Spirits', current_stock: 10, initial_stock: 18, reorder_level: 4,  status: 'warning',  consumption_rate: 2.0, estimated_depletion_minutes: 300, unit_price: 9.0  },
  { id: 15, bar_id: 3, product_name: 'Rosé Wine',         category: 'Wine',    current_stock: 20, initial_stock: 24, reorder_level: 6,  status: 'healthy',  consumption_rate: 1.6, estimated_depletion_minutes: 750, unit_price: 9.0  },
  { id: 16, bar_id: 3, product_name: 'Soda Water',        category: 'Mixers',  current_stock: 30, initial_stock: 48, reorder_level: 10, status: 'healthy',  consumption_rate: 3.2, estimated_depletion_minutes: 563, unit_price: 2.0  },
  { id: 17, bar_id: 3, product_name: 'Coconut Water',     category: 'Other',   current_stock: 14, initial_stock: 24, reorder_level: 6,  status: 'healthy',  consumption_rate: 1.8, estimated_depletion_minutes: 467, unit_price: 4.0  },

  // DJ Booth (bar_id: 4)
  { id: 18, bar_id: 4, product_name: 'Smirnoff Vodka',    category: 'Spirits', current_stock: 3,  initial_stock: 20, reorder_level: 4,  status: 'critical', consumption_rate: 4.8, estimated_depletion_minutes: 38,  unit_price: 8.5  },
  { id: 19, bar_id: 4, product_name: 'Tonic Water',       category: 'Mixers',  current_stock: 0,  initial_stock: 24, reorder_level: 6,  status: 'depleted', consumption_rate: 3.9, estimated_depletion_minutes: 0,   unit_price: 3.0  },
  { id: 20, bar_id: 4, product_name: 'Red Bull',          category: 'Mixers',  current_stock: 12, initial_stock: 36, reorder_level: 9,  status: 'warning',  consumption_rate: 5.2, estimated_depletion_minutes: 138, unit_price: 4.5  },
  { id: 21, bar_id: 4, product_name: 'Jägermeister',      category: 'Spirits', current_stock: 4,  initial_stock: 10, reorder_level: 3,  status: 'critical', consumption_rate: 2.6, estimated_depletion_minutes: 92,  unit_price: 9.5  },
  { id: 22, bar_id: 4, product_name: 'Stella Artois',     category: 'Beer',    current_stock: 20, initial_stock: 36, reorder_level: 9,  status: 'warning',  consumption_rate: 4.1, estimated_depletion_minutes: 293, unit_price: 6.0  },
  { id: 23, bar_id: 4, product_name: 'Coca-Cola',         category: 'Mixers',  current_stock: 18, initial_stock: 48, reorder_level: 12, status: 'warning',  consumption_rate: 6.0, estimated_depletion_minutes: 180, unit_price: 3.5  },
  { id: 24, bar_id: 4, product_name: 'Sambuca',           category: 'Spirits', current_stock: 6,  initial_stock: 12, reorder_level: 3,  status: 'warning',  consumption_rate: 2.3, estimated_depletion_minutes: 157, unit_price: 8.0  },
  { id: 25, bar_id: 4, product_name: 'Ice Bucket Packs',  category: 'Other',   current_stock: 5,  initial_stock: 30, reorder_level: 8,  status: 'critical', consumption_rate: 3.5, estimated_depletion_minutes: 86,  unit_price: 1.5  },
]

// ─── 5. MOCK_WAREHOUSE_ITEMS ──────────────────────────────────────────────────

export const MOCK_WAREHOUSE_ITEMS: WarehouseItem[] = [
  { id: 1,  product_name: 'Heineken',          brand: 'Heineken',          category: 'Beer',    quantity_in_warehouse: 12, allocated_to_event: 60,  unit: 'cases'   },
  { id: 2,  product_name: 'Stella Artois',     brand: 'AB InBev',          category: 'Beer',    quantity_in_warehouse: 8,  allocated_to_event: 36,  unit: 'cases'   },
  { id: 3,  product_name: 'Corona Extra',      brand: 'Corona',            category: 'Beer',    quantity_in_warehouse: 10, allocated_to_event: 60,  unit: 'cases'   },
  { id: 4,  product_name: 'Craft IPA',         brand: 'Local Brew Co.',    category: 'Beer',    quantity_in_warehouse: 4,  allocated_to_event: 24,  unit: 'kegs'    },
  { id: 5,  product_name: 'Absolut Vodka',     brand: 'Absolut',           category: 'Spirits', quantity_in_warehouse: 6,  allocated_to_event: 20,  unit: 'bottles' },
  { id: 6,  product_name: 'Grey Goose Vodka',  brand: 'Grey Goose',        category: 'Spirits', quantity_in_warehouse: 4,  allocated_to_event: 15,  unit: 'bottles' },
  { id: 7,  product_name: 'Smirnoff Vodka',    brand: 'Smirnoff',          category: 'Spirits', quantity_in_warehouse: 3,  allocated_to_event: 20,  unit: 'bottles' },
  { id: 8,  product_name: 'Hendrick\'s Gin',   brand: 'Hendrick\'s',       category: 'Spirits', quantity_in_warehouse: 5,  allocated_to_event: 12,  unit: 'bottles' },
  { id: 9,  product_name: 'Jack Daniel\'s',    brand: 'Jack Daniel\'s',    category: 'Spirits', quantity_in_warehouse: 4,  allocated_to_event: 15,  unit: 'bottles' },
  { id: 10, product_name: 'Bacardi White Rum', brand: 'Bacardi',           category: 'Spirits', quantity_in_warehouse: 5,  allocated_to_event: 18,  unit: 'bottles' },
  { id: 11, product_name: 'Jägermeister',      brand: 'Jägermeister',      category: 'Spirits', quantity_in_warehouse: 3,  allocated_to_event: 10,  unit: 'bottles' },
  { id: 12, product_name: 'Moët & Chandon',    brand: 'Moët & Chandon',    category: 'Wine',    quantity_in_warehouse: 2,  allocated_to_event: 24,  unit: 'bottles' },
  { id: 13, product_name: 'Perrier-Jouët',     brand: 'Perrier-Jouët',     category: 'Wine',    quantity_in_warehouse: 1,  allocated_to_event: 12,  unit: 'bottles' },
  { id: 14, product_name: 'House Red Wine',    brand: 'Merlot Reserve',    category: 'Wine',    quantity_in_warehouse: 10, allocated_to_event: 30,  unit: 'bottles' },
  { id: 15, product_name: 'Rosé Wine',         brand: 'Côtes de Provence', category: 'Wine',    quantity_in_warehouse: 8,  allocated_to_event: 24,  unit: 'bottles' },
  { id: 16, product_name: 'Fever-Tree Tonic',  brand: 'Fever-Tree',        category: 'Mixers',  quantity_in_warehouse: 15, allocated_to_event: 36,  unit: 'cases'   },
  { id: 17, product_name: 'Soda Water',        brand: 'Generic',           category: 'Mixers',  quantity_in_warehouse: 20, allocated_to_event: 48,  unit: 'cases'   },
  { id: 18, product_name: 'Coca-Cola',         brand: 'Coca-Cola',         category: 'Mixers',  quantity_in_warehouse: 14, allocated_to_event: 48,  unit: 'cases'   },
  { id: 19, product_name: 'Red Bull',          brand: 'Red Bull',          category: 'Mixers',  quantity_in_warehouse: 10, allocated_to_event: 36,  unit: 'cases'   },
  { id: 20, product_name: 'Lime Juice',        brand: 'Finest Call',       category: 'Mixers',  quantity_in_warehouse: 6,  allocated_to_event: 24,  unit: 'bottles' },
]

// ─── 6. MOCK_PREDICTIONS ─────────────────────────────────────────────────────

export const MOCK_PREDICTIONS: Predictions = {
  generated_at: '2026-06-15T18:00',
  model_type: 'live',
  predictions: [
    { product: 'Beer (all types)',     predicted_demand_2h: 145, trend: 'up',     confidence: 0.82 },
    { product: 'Spirits (all types)',  predicted_demand_2h: 89,  trend: 'stable', confidence: 0.78 },
    { product: 'Mixers',               predicted_demand_2h: 210, trend: 'up',     confidence: 0.85 },
    { product: 'Wine',                 predicted_demand_2h: 34,  trend: 'down',   confidence: 0.71 },
    { product: 'Premium cocktails',    predicted_demand_2h: 67,  trend: 'up',     confidence: 0.74 },
  ],
}

// ─── 7. MOCK_TRANSACTIONS ─────────────────────────────────────────────────────

export const MOCK_TRANSACTIONS: Transaction[] = [
  { id: 1,  event_id: 1, timestamp: '22:13', bar_id: 4, bar_name: 'DJ Booth',   product_name: 'Smirnoff Vodka',   product_tier: 'B', quantity: 2, unit_price: 8.5,  total_price: 17.0, payment_method: 'nfc'  },
  { id: 2,  event_id: 1, timestamp: '22:11', bar_id: 2, bar_name: 'VIP Lounge', product_name: 'Grey Goose Vodka', product_tier: 'P', quantity: 1, unit_price: 14.0, total_price: 14.0, payment_method: 'nfc'  },
  { id: 3,  event_id: 1, timestamp: '22:09', bar_id: 1, bar_name: 'Main Bar',   product_name: 'Heineken',         product_tier: 'B', quantity: 3, unit_price: 6.0,  total_price: 18.0, payment_method: 'card' },
  { id: 4,  event_id: 1, timestamp: '22:07', bar_id: 3, bar_name: 'Pool Bar',   product_name: 'Corona Extra',     product_tier: 'B', quantity: 2, unit_price: 6.5,  total_price: 13.0, payment_method: 'nfc'  },
  { id: 5,  event_id: 1, timestamp: '22:05', bar_id: 2, bar_name: 'VIP Lounge', product_name: 'Moët & Chandon',   product_tier: 'P', quantity: 1, unit_price: 45.0, total_price: 45.0, payment_method: 'nfc'  },
  { id: 6,  event_id: 1, timestamp: '22:02', bar_id: 4, bar_name: 'DJ Booth',   product_name: 'Red Bull',         product_tier: 'U', quantity: 4, unit_price: 4.5,  total_price: 18.0, payment_method: 'cash' },
  { id: 7,  event_id: 1, timestamp: '21:58', bar_id: 1, bar_name: 'Main Bar',   product_name: 'Jack Daniel\'s',   product_tier: 'S', quantity: 2, unit_price: 10.0, total_price: 20.0, payment_method: 'nfc'  },
  { id: 8,  event_id: 1, timestamp: '21:55', bar_id: 3, bar_name: 'Pool Bar',   product_name: 'Bacardi Rum',      product_tier: 'S', quantity: 1, unit_price: 9.0,  total_price: 9.0,  payment_method: 'card' },
  { id: 9,  event_id: 1, timestamp: '21:51', bar_id: 2, bar_name: 'VIP Lounge', product_name: 'Hendrick\'s Gin',  product_tier: 'P', quantity: 2, unit_price: 12.0, total_price: 24.0, payment_method: 'nfc'  },
  { id: 10, event_id: 1, timestamp: '21:48', bar_id: 4, bar_name: 'DJ Booth',   product_name: 'Jägermeister',     product_tier: 'S', quantity: 3, unit_price: 9.5,  total_price: 28.5, payment_method: 'nfc'  },
  { id: 11, event_id: 1, timestamp: '21:44', bar_id: 1, bar_name: 'Main Bar',   product_name: 'House Red Wine',   product_tier: 'B', quantity: 1, unit_price: 8.0,  total_price: 8.0,  payment_method: 'card' },
  { id: 12, event_id: 1, timestamp: '21:41', bar_id: 3, bar_name: 'Pool Bar',   product_name: 'Rosé Wine',        product_tier: 'S', quantity: 2, unit_price: 9.0,  total_price: 18.0, payment_method: 'nfc'  },
  { id: 13, event_id: 1, timestamp: '21:38', bar_id: 4, bar_name: 'DJ Booth',   product_name: 'Stella Artois',    product_tier: 'B', quantity: 4, unit_price: 6.0,  total_price: 24.0, payment_method: 'nfc'  },
  { id: 14, event_id: 1, timestamp: '21:35', bar_id: 2, bar_name: 'VIP Lounge', product_name: 'Perrier-Jouët',    product_tier: 'P', quantity: 1, unit_price: 65.0, total_price: 65.0, payment_method: 'nfc'  },
  { id: 15, event_id: 1, timestamp: '21:30', bar_id: 1, bar_name: 'Main Bar',   product_name: 'Absolut Vodka',    product_tier: 'S', quantity: 2, unit_price: 9.5,  total_price: 19.0, payment_method: 'card' },
  { id: 16, event_id: 1, timestamp: '21:26', bar_id: 3, bar_name: 'Pool Bar',   product_name: 'Coconut Water',    product_tier: 'U', quantity: 3, unit_price: 4.0,  total_price: 12.0, payment_method: 'cash' },
  { id: 17, event_id: 1, timestamp: '21:22', bar_id: 4, bar_name: 'DJ Booth',   product_name: 'Coca-Cola',        product_tier: 'U', quantity: 5, unit_price: 3.5,  total_price: 17.5, payment_method: 'nfc'  },
  { id: 18, event_id: 1, timestamp: '21:18', bar_id: 2, bar_name: 'VIP Lounge', product_name: 'Cointreau',        product_tier: 'P', quantity: 1, unit_price: 11.0, total_price: 11.0, payment_method: 'nfc'  },
  { id: 19, event_id: 1, timestamp: '21:14', bar_id: 1, bar_name: 'Main Bar',   product_name: 'Tonic Water',      product_tier: 'U', quantity: 3, unit_price: 3.0,  total_price: 9.0,  payment_method: 'card' },
  { id: 20, event_id: 1, timestamp: '21:10', bar_id: 3, bar_name: 'Pool Bar',   product_name: 'Soda Water',       product_tier: 'U', quantity: 4, unit_price: 2.0,  total_price: 8.0,  payment_method: 'cash' },
]

// ─── 8. MOCK_WAREHOUSE_SCANS ─────────────────────────────────────────────────

export interface WarehouseScan {
  id: number
  event_id: number
  barcode_raw: string
  resolved_product_name: string
  /** Backend ENUM: intake / dispatch */
  scan_type: 'intake' | 'dispatch'
  quantity: number
  destination_bar_id?: number
  /** Display name of the warehouse operative */
  scanned_by: string
  created_at: string
}

export const MOCK_WAREHOUSE_SCANS: WarehouseScan[] = [
  { id: 1,  event_id: 1, barcode_raw: 'BAR-AV-001',  resolved_product_name: 'Absolut Vodka',     scan_type: 'intake',   quantity: 12, scanned_by: 'Ali W.',    created_at: '22:05' },
  { id: 2,  event_id: 1, barcode_raw: 'BAR-TV-004',  resolved_product_name: 'Tonic Water',        scan_type: 'dispatch', quantity: 12, destination_bar_id: 4, scanned_by: 'Reza W.',   created_at: '21:58' },
  { id: 3,  event_id: 1, barcode_raw: 'BAR-MC-012',  resolved_product_name: 'Moët & Chandon',     scan_type: 'dispatch', quantity: 6,  destination_bar_id: 2, scanned_by: 'Ali W.',    created_at: '21:50' },
  { id: 4,  event_id: 1, barcode_raw: 'BAR-PJ-013',  resolved_product_name: 'Perrier-Jouët',      scan_type: 'dispatch', quantity: 4,  destination_bar_id: 2, scanned_by: 'Ali W.',    created_at: '21:48' },
  { id: 5,  event_id: 1, barcode_raw: 'BAR-RB-019',  resolved_product_name: 'Red Bull',           scan_type: 'intake',   quantity: 24, scanned_by: 'Reza W.',   created_at: '21:40' },
  { id: 6,  event_id: 1, barcode_raw: 'BAR-SV-007',  resolved_product_name: 'Smirnoff Vodka',     scan_type: 'dispatch', quantity: 8,  destination_bar_id: 4, scanned_by: 'Reza W.',   created_at: '21:30' },
  { id: 7,  event_id: 1, barcode_raw: 'BAR-HG-008',  resolved_product_name: 'Hendrick\'s Gin',    scan_type: 'dispatch', quantity: 6,  destination_bar_id: 2, scanned_by: 'Ali W.',    created_at: '21:22' },
  { id: 8,  event_id: 1, barcode_raw: 'BAR-CE-003',  resolved_product_name: 'Corona Extra',       scan_type: 'intake',   quantity: 48, scanned_by: 'Nadia W.',  created_at: '20:55' },
  { id: 9,  event_id: 1, barcode_raw: 'BAR-HN-001',  resolved_product_name: 'Heineken',           scan_type: 'dispatch', quantity: 24, destination_bar_id: 1, scanned_by: 'Nadia W.',  created_at: '20:44' },
  { id: 10, event_id: 1, barcode_raw: 'BAR-GG-006',  resolved_product_name: 'Grey Goose Vodka',   scan_type: 'intake',   quantity: 6,  scanned_by: 'Ali W.',    created_at: '20:30' },
  { id: 11, event_id: 1, barcode_raw: 'BAR-BR-010',  resolved_product_name: 'Bacardi White Rum',  scan_type: 'dispatch', quantity: 12, destination_bar_id: 3, scanned_by: 'Reza W.',   created_at: '20:18' },
  { id: 12, event_id: 1, barcode_raw: 'BAR-JD-009',  resolved_product_name: 'Jack Daniel\'s',     scan_type: 'intake',   quantity: 12, scanned_by: 'Nadia W.',  created_at: '19:55' },
  { id: 13, event_id: 1, barcode_raw: 'BAR-CC-018',  resolved_product_name: 'Coca-Cola',          scan_type: 'dispatch', quantity: 48, destination_bar_id: 4, scanned_by: 'Nadia W.',  created_at: '19:40' },
  { id: 14, event_id: 1, barcode_raw: 'BAR-FT-016',  resolved_product_name: 'Fever-Tree Tonic',   scan_type: 'intake',   quantity: 36, scanned_by: 'Ali W.',    created_at: '19:25' },
  { id: 15, event_id: 1, barcode_raw: 'BAR-JG-011',  resolved_product_name: 'Jägermeister',       scan_type: 'dispatch', quantity: 6,  destination_bar_id: 4, scanned_by: 'Reza W.',   created_at: '19:10' },
]

// ─── 9. MOCK_CHAT_MESSAGES ────────────────────────────────────────────────────

export const MOCK_CHAT_MESSAGES: ChatMessage[] = [
  { id: 1,  sender_role: 'owner',     sender_name: 'Owner',     bar_id: null, bar_name: null,         message: 'Good evening everyone. Event is live. Stay sharp — expecting a spike after 22:00.',            timestamp: '20:05', read: true  },
  { id: 2,  sender_role: 'manager',   sender_name: 'Manager',   bar_id: 2,    bar_name: 'VIP Lounge', message: 'VIP Lounge is open. Champagne service started. Headcount looking strong.',                      timestamp: '20:08', read: true  },
  { id: 3,  sender_role: 'manager',   sender_name: 'Manager',   bar_id: 1,    bar_name: 'Main Bar',   message: 'Main Bar fully stocked and ready. All staff on shift.',                                         timestamp: '20:10', read: true  },
  { id: 4,  sender_role: 'bartender', sender_name: 'Bartender', bar_id: 4,    bar_name: 'DJ Booth',   message: 'DJ Booth is getting busy already. Going to need a vodka restock before midnight.',              timestamp: '21:32', read: true  },
  { id: 5,  sender_role: 'owner',     sender_name: 'Owner',     bar_id: null, bar_name: null,         message: 'DJ Booth — acknowledged. Warehouse has been notified. Restock ETA 30 min.',                     timestamp: '21:35', read: true  },
  { id: 6,  sender_role: 'manager',   sender_name: 'Manager',   bar_id: 2,    bar_name: 'VIP Lounge', message: 'Champagne is going fast. We\'re already at 25% stock. Requesting restock now.',                 timestamp: '21:50', read: true  },
  { id: 7,  sender_role: 'owner',     sender_name: 'Owner',     bar_id: null, bar_name: null,         message: 'VIP Lounge — restock approved. Sending 6 bottles Moët and 4 Perrier-Jouët.',                    timestamp: '21:52', read: true  },
  { id: 8,  sender_role: 'bartender', sender_name: 'Bartender', bar_id: 4,    bar_name: 'DJ Booth',   message: 'Tonic water is completely out. Crowd is still asking for gin-tonics. Need urgent restock.',      timestamp: '22:01', read: true  },
  { id: 9,  sender_role: 'manager',   sender_name: 'Manager',   bar_id: 1,    bar_name: 'Main Bar',   message: 'Main Bar is handling overflow from DJ Booth. Burn rate up. Watching lime juice — running low.',  timestamp: '22:10', read: false },
  { id: 10, sender_role: 'owner',     sender_name: 'Owner',     bar_id: null, bar_name: null,         message: 'All managers: anomaly alert on beer consumption at Main Bar. Monitor and report in 15.',         timestamp: '22:15', read: false },
]
