/**
 * React Query hooks for the invoice-upload pipeline.
 *
 * Three mutations in sequence:
 *   useParseInvoicePdf       POST /warehouse/invoices/parse-pdf
 *   useMatchProductsBatch    POST /products/match-batch
 *   useCreateInvoice         POST /warehouse/invoices
 *
 * The modal calls them in that order:
 *   1. User drops PDF -> parse it -> ParsedInvoice
 *   2. Pass the item descriptions to match-batch -> suggestions per item
 *   3. User reviews + confirms -> POST /warehouse/invoices to save
 *
 * All three are isolated mutations, not coupled — the modal can show
 * partial state (parsed but matching pending, etc) cleanly.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  InvoiceCreatePayload,
  ParsedInvoice,
  ProductMatchBatchRequest,
  ProductMatchBatchResponse,
} from './types'


// ─── Parse PDF ───────────────────────────────────────────────────────

/**
 * Upload a PDF fattura, get back a ParsedInvoice preview.
 * Multipart upload — the api client handles the Content-Type header.
 *
 * Backend error envelope (any non-200) is rethrown by axios so the
 * modal can show specific messages for 415 / 413 / 422.
 */
export function useParseInvoicePdf() {
  return useMutation({
    mutationFn: async (file: File): Promise<ParsedInvoice> => {
      const form = new FormData()
      form.append('file', file)
      const res = await api.post<ParsedInvoice>(
        '/warehouse/invoices/parse-pdf',
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      return res.data
    },
  })
}


// ─── Fuzzy match batch ───────────────────────────────────────────────

/**
 * Given a batch of description strings, return suggested existing
 * Catalog products per description. Used right after parse-pdf to
 * pre-populate the preview table\'s "link to existing product" column.
 */
export function useMatchProductsBatch() {
  return useMutation({
    mutationFn: async (req: ProductMatchBatchRequest): Promise<ProductMatchBatchResponse> => {
      const res = await api.post<ProductMatchBatchResponse>(
        '/products/match-batch',
        req,
      )
      return res.data
    },
  })
}


// ─── Create invoice (save after preview confirmed) ───────────────────

/**
 * Save the user-confirmed invoice. Backend creates DeliveryInvoice +
 * InvoiceItem rows atomically (single transaction). On success we
 * invalidate any cached invoice + warehouse inventory queries so
 * the warehouse page reflects the new pool immediately.
 */
export function useCreateInvoice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: InvoiceCreatePayload) => {
      const res = await api.post('/warehouse/invoices', payload)
      return res.data
    },
    onSuccess: () => {
      // Anything keyed under these scopes refetches. Specific keys are
      // owned by features/warehouse — using a broad prefix invalidation
      // keeps this hook unaware of those internals.
      qc.invalidateQueries({ queryKey: ['warehouse'] })
      qc.invalidateQueries({ queryKey: ['inventory'] })
    },
  })
}
