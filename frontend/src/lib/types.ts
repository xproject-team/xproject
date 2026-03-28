/**
 * TypeScript interfaces that MUST mirror the Pydantic schemas in the backend.
 * Rules: snake_case, datetime → string (ISO), Optional[X] → X | undefined.
 * Keep in sync with backend/app/modules/<module>/schemas.py.
 */

// --- Auth ---
export interface UserResponse {
  id: number
  email: string
  full_name: string
  role: 'owner' | 'manager' | 'bartender' | 'warehouse'
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

// --- Events ---
export interface EventResponse {
  id: number
  name: string
  venue: string
  status: 'pending' | 'active' | 'ended'
  created_at?: string
  started_at?: string
  ended_at?: string
}

// --- Inventory ---
export interface InventoryItemResponse {
  id: number
  event_id: number
  bar_id: number
  sku: string
  name: string
  quantity: number
  unit: string
  low_stock_threshold: number
}

// --- Alerts ---
export interface AlertResponse {
  id: number
  event_id: number
  rule_name: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  acknowledged: boolean
  created_at?: string
}

// --- Predictions ---
export interface PredictionResponse {
  id: number
  event_id: number
  sku: string
  predicted_demand: number
  confidence: number
  horizon_hours: number
  created_at?: string
}

// --- Anomaly ---
export interface AnomalyEventResponse {
  id: number
  event_id: number
  detector: string
  sku?: string
  score: number
  description: string
  detected_at?: string
}

// --- Warehouse ---
export interface ScanEventResponse {
  id: number
  event_id: number
  barcode: string
  sku?: string
  action: string
  quantity: number
  scanned_at?: string
}

// --- Reports ---
export interface ReportResponse {
  id: number
  event_id: number
  title: string
  narrative?: string
  pdf_path?: string
  generated_at?: string
}

// --- Chat ---
export interface ChatMessageResponse {
  id: number
  event_id: number
  user_id: number
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}
