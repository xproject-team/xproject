/**
 * TypeScript interfaces that MUST mirror the Pydantic schemas in the backend.
 * Rules: snake_case, datetime → string (ISO), Optional[X] → X | undefined.
 * Keep in sync with backend/app/modules/<module>/schemas.py.
 *
 * Field names match the Backend Bible database schema exactly.
 */

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface UserResponse {
  id: number
  email: string
  full_name: string
  /** Backend ENUM: owner / manager / staff / bartender  (NOT 'warehouse') */
  role: 'owner' | 'manager' | 'staff' | 'bartender'
  phone?: string
  is_active: boolean
  created_at?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

// ─── Events ───────────────────────────────────────────────────────────────────

export interface EventResponse {
  id: number
  name: string
  /** ISO date string e.g. "2026-06-15" */
  date: string
  /** Venue / address — backend column is `location` */
  location: string
  expected_guest_count: number
  /** Backend ENUM: draft / active / live / completed */
  status: 'draft' | 'active' | 'live' | 'completed'
  created_at?: string
  updated_at?: string
}

// ─── Bar Inventory (BAR_INVENTORY table) ─────────────────────────────────────

export interface InventoryItemResponse {
  id: number
  event_id: number
  bar_id: number
  product_name: string
  initial_stock: number
  current_stock: number
  last_updated?: string
}

// ─── Alerts ───────────────────────────────────────────────────────────────────

export interface AlertResponse {
  id: number
  event_id: number
  bar_id?: number
  product_name?: string
  /** Backend ENUM: depletion / anomaly / discrepancy / system */
  alert_type: 'depletion' | 'anomaly' | 'discrepancy' | 'system'
  /** Backend ENUM: info / warning / critical */
  severity: 'info' | 'warning' | 'critical'
  message: string
  /** Arbitrary JSON payload attached by the alert engine */
  data?: Record<string, unknown>
  time_to_depletion_min?: number
  is_acknowledged: boolean
  acknowledged_by?: number
  acknowledged_at?: string
  created_at?: string
}

// ─── Predictions ──────────────────────────────────────────────────────────────

export interface PredictionResponse {
  id: number
  event_id: number
  /** Backend ENUM: pre_event / live */
  model_type: 'pre_event' | 'live'
  /** Raw JSONB from the ML model — shape varies by model version */
  prediction_data: unknown
  confidence_score: number
  generated_at: string
  is_override: boolean
  override_by?: number
}

// ─── Anomaly ──────────────────────────────────────────────────────────────────

export interface AnomalyEventResponse {
  id: number
  event_id: number
  detector: string
  product_name?: string
  score: number
  description: string
  detected_at?: string
}

// ─── Warehouse Scans (WAREHOUSE_SCANS table) ─────────────────────────────────

export interface ScanEventResponse {
  id: number
  event_id: number
  barcode_raw: string
  resolved_product_name?: string
  /** Backend ENUM: intake / dispatch */
  scan_type: 'intake' | 'dispatch'
  quantity: number
  destination_bar_id?: number
  scanned_by?: number
  notes?: string
  created_at?: string
}

// ─── Reports ──────────────────────────────────────────────────────────────────

export interface ReportResponse {
  id: number
  event_id: number
  title: string
  narrative?: string
  pdf_path?: string
  generated_at?: string
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatMessageResponse {
  id: number
  event_id: number
  user_id: number
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}
