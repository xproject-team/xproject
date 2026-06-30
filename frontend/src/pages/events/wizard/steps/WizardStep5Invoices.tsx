/**
 * Wizard Step 5 — Warehouse / Invoices.
 *
 * Lets Omar upload supplier fatture (PDF) during event setup, instead
 * of doing it later from the standalone Warehouse page. Same modal,
 * same backend pipeline -- this step is pure UX convenience.
 *
 * IMPORTANT: invoices are tenant-scoped (no event_id), so they go
 * straight into the warehouse pool the moment the user clicks "Save
 * Invoice" inside the modal. We do NOT defer them to the wizard
 * Finalize step. That means:
 *   - The invoices remain even if the user abandons the wizard draft
 *   - The warehouse pool carries forward to the next Sundance
 *   - This step is optional: Omar can skip it and upload later
 *
 * The visible list here is purely a confirmation of what the user
 * uploaded during THIS wizard session, not authoritative state.
 */
import { useState } from "react"

import { UploadInvoiceModal } from "@/features/warehouse/invoice_upload"
import type { WizardState } from "../types"

interface UploadedInvoice {
  id?: string
  supplier_name: string
  invoice_number: string | null
  uploaded_at: string  // local time, just for display
}

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

// NOTE: the wizard state doesn\'t persist `uploaded_invoices` across
// sessions because the invoices themselves are already saved on the
// server. We just track them in local component state for visual
// feedback during this setup session. If the user closes the wizard
// and reopens, the list resets -- but the invoices are still in the
// warehouse pool, accessible from the standalone /warehouse page.
export function WizardStep5Invoices(_props: Props) {
  const [modalOpen, setModalOpen] = useState(false)
  const [uploaded, setUploaded] = useState<UploadedInvoice[]>([])

  function handleSaved(id?: string) {
    // The modal closes itself; we just append to the visible list.
    // Backend already saved the invoice -- this is display-only.
    setUploaded((prev) => [
      ...prev,
      {
        id,
        supplier_name: "Saved invoice",   // we don\'t have the data here; modal doesn\'t expose it post-save
        invoice_number: null,
        uploaded_at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ])
  }

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-bold text-[#1A202C]">Warehouse invoices</h2>
          <p className="mt-1 text-sm text-[#718096]">
            Upload supplier fatture (PDF) to grow the tenant warehouse pool.
            Items added here are available to every event going forward, not
            just this Sundance.
          </p>
          <p className="mt-1 text-xs text-[#A0AEC0]">
            This step is optional. You can also upload invoices from the
            standalone Warehouse page any time.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-[#1ABC9C] hover:bg-[#17a589] px-4 py-2 text-sm font-semibold text-white"
        >
          <span className="text-base leading-none">+</span> Upload Invoice
        </button>
      </div>

      {/* Uploaded list — empty state vs filled */}
      {uploaded.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#CBD5E0] p-8 text-center">
          <p className="text-sm text-[#718096]">No invoices uploaded yet.</p>
          <p className="text-xs text-[#A0AEC0] mt-1">Click “+ Upload Invoice” to drop a PDF.</p>
        </div>
      ) : (
        <div className="border border-[#E2E8F0] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#F7FAFC] text-[#4A5568] text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Invoice</th>
                <th className="px-4 py-2 text-right font-semibold w-32">Uploaded at</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {uploaded.map((inv, i) => (
                <tr key={`${inv.id ?? i}`}>
                  <td className="px-4 py-2 text-[#1A202C]">
                    {inv.supplier_name}
                    {inv.invoice_number && (
                      <span className="ml-2 text-xs text-[#718096]">#{inv.invoice_number}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-[#718096]">{inv.uploaded_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <UploadInvoiceModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={handleSaved}
      />
    </div>
  )
}
