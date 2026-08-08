/**
 * Wizard Step 5 — Warehouse / Invoices.
 *
 * Lets Omar upload supplier fatture (PDF) during event setup, instead
 * of doing it later from the standalone Warehouse page. Same modal,
 * same backend pipeline -- this step is pure UX convenience.
 *
 * As of T5 (event-scoped architecture rewrite): invoices saved here
 * attach to the wizard's event_id — set when the user clicks "Create
 * Event" at the end of Step 4. Step 5 only becomes interactive once
 * that round-trip succeeds; before that, the Upload button has no real
 * event to attach to and the create flow is gated by the wizard
 * itself.
 *
 *   - Invoices attach to THIS event only — fresh start for the next one
 *   - This step is still optional: Omar can click "Done" to skip
 *     uploads and add them later from the Warehouse page
 *
 * The visible list here is purely a confirmation of what the user
 * uploaded during THIS wizard session, not authoritative state.
 */
import { useState } from "react"

import { UploadInvoiceModal } from "@/features/warehouse/invoice_upload"
import type { WizardState } from "../types"
import { stepCardCls } from "@/design-system/wizardForm"
import { Button, EmptyState } from "@/design-system/components"
import "@/design-system/components/components.css"

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
export function WizardStep5Invoices({ state }: Props) {
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
    <div className={stepCardCls}>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-medium" style={{ color: "var(--v-text)" }}>Warehouse invoices</h2>
          <p className="mt-1 text-sm" style={{ color: "var(--v-text-muted)" }}>
            Upload supplier fatture (PDF) to grow the tenant warehouse pool.
            Items added here are available to every event going forward, not
            just this Sundance.
          </p>
          <p className="mt-1 text-xs" style={{ color: "var(--v-text-dim)" }}>
            This step is optional. You can also upload invoices from the
            standalone Warehouse page any time.
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          <span className="flex items-center gap-1.5">
            <span className="text-base leading-none">+</span> Upload Invoice
          </span>
        </Button>
      </div>

      {/* Uploaded list — empty state vs filled */}
      {uploaded.length === 0 ? (
        <div className="rounded-[var(--v-radius)] p-8" style={{ border: "1px dashed var(--v-border)" }}>
          <EmptyState headline="No invoices uploaded yet" body='Click "+ Upload Invoice" to drop a PDF.' />
        </div>
      ) : (
        <div className="overflow-hidden rounded-[var(--v-radius)]" style={{ border: "0.5px solid var(--v-border)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--v-surface-raised)" }}>
              <tr>
                <th className="px-4 py-2 text-left text-xs uppercase font-semibold" style={{ color: "var(--v-text-muted)" }}>Invoice</th>
                <th className="px-4 py-2 text-right text-xs uppercase font-semibold w-32" style={{ color: "var(--v-text-muted)" }}>Uploaded at</th>
              </tr>
            </thead>
            <tbody>
              {uploaded.map((inv, i) => (
                <tr key={`${inv.id ?? i}`} style={{ borderTop: "0.5px solid var(--v-border)" }}>
                  <td className="px-4 py-2" style={{ color: "var(--v-text)" }}>
                    {inv.supplier_name}
                    {inv.invoice_number && (
                      <span className="ml-2 text-xs" style={{ color: "var(--v-text-muted)" }}>#{inv.invoice_number}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-xs" style={{ color: "var(--v-text-muted)" }}>{inv.uploaded_at}</td>
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
        eventId={state.event_id}
      />
    </div>
  )
}
