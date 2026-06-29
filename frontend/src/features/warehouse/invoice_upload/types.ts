/**
 * Types for the invoice-upload pipeline.
 *
 * Mirror of the backend Pydantic schemas — keep these in sync with:
 *   - backend/app/modules/warehouse/invoice_pdf_parser/schemas.py
 *     (ParsedInvoice, ParsedInvoiceHeader, ParsedInvoiceItem)
 *   - backend/app/modules/products/schemas.py
 *     (ProductMatchBatchRequest/Response, ProductMatchCandidate)
 *   - backend/app/modules/warehouse/schemas.py
 *     (InvoiceCreate / InvoiceItemCreate — what we POST after the user
 *      confirms the preview).
 *
 * Decimal handling: backend serializes Decimal to JSON string for
 * precision. We type those fields as `string` here, not number. The
 * modal will parse with `Number(value)` only at display time.
 */

// ─── Parsed invoice (from POST /warehouse/invoices/parse-pdf) ────────

export interface ParsedInvoiceHeader {
  supplier_name:    string | null
  supplier_vat:     string | null
  customer_name:    string | null
  customer_vat:     string | null
  invoice_number:   string | null
  invoice_date:     string | null     // ISO date string from backend
  total_imponibile: string | null     // serialized Decimal
  total_iva:        string | null
  total_document:   string | null
}

export interface ParsedInvoiceItem {
  line_num:        number
  code:            string
  description:     string
  qty:             string             // serialized Decimal
  unit:            string              // BO | KAR | FS | BM | CT | PZ | VP
  unit_price_eur:  string
  discount_pct:    string | null
  discount_eur:    string | null
  line_total_eur:  string
  iva_pct:         number
}

export interface ParsedInvoice {
  header:   ParsedInvoiceHeader
  items:    ParsedInvoiceItem[]
  raw_text: string
}

// ─── Fuzzy product matching (POST /products/match-batch) ─────────────

export interface ProductMatchCandidate {
  product_id: string                 // UUID
  name:       string
  score:      number                  // 0..100
}

export interface ProductMatchResult {
  query:   string
  matches: ProductMatchCandidate[]
}

export interface ProductMatchBatchRequest {
  queries:    string[]
  threshold?: number                  // default 70 on backend
  top_k?:     number                  // default 3 on backend
}

export interface ProductMatchBatchResponse {
  results: ProductMatchResult[]
}

// ─── Invoice create (POST /warehouse/invoices) ───────────────────────
// The frontend builds this from the parsed preview + the user's edits
// + the user's match choices. Sent only after the user clicks "Save".

export interface InvoiceItemCreatePayload {
  // Either product_id (link to existing) OR miscellaneous_description
  // (one-off item, will create a placeholder product server-side).
  kind: 'product' | 'miscellaneous'
  product_id?: string | null         // UUID
  miscellaneous_description?: string | null
  expected_qty: number
  unit_price_cents?: number | null
  line_total_cents?: number | null
}

export interface InvoiceCreatePayload {
  invoice_number?:        string | null
  supplier_name:          string
  expected_arrival_date:  string      // ISO date
  notes?:                 string | null
  items:                  InvoiceItemCreatePayload[]
}

// ─── UI-local enrichment (not sent to backend) ───────────────────────
// During the preview, we keep extra state per parsed item:
//   - the fuzzy-match suggestions
//   - the user's link choice (link to existing or create new)
// This stays in the modal\'s React state, not in any API payload.

export type ItemLinkChoice =
  | { kind: 'create_new' }
  | { kind: 'link'; product_id: string; product_name: string }

export interface PreviewItem extends ParsedInvoiceItem {
  /** Suggestions returned by /products/match-batch, ranked by score */
  suggestions: ProductMatchCandidate[]
  /** What the user chose for this item (defaults to create_new). */
  link: ItemLinkChoice
}
