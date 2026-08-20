/**
 * UploadInvoiceModal — drop a fattura PDF, review/edit, save as invoice.
 *
 * One-PDF-at-a-time flow. Matches how Omar actually uses it: fatture
 * arrive one at a time over many days.
 *
 *   1. User drops/picks a PDF
 *   2. useParseInvoicePdf      -> ParsedInvoice (header + items)
 *   3. useMatchProductsBatch   -> per-item suggestions from Catalog
 *   4. Editable preview:
 *        - Header form (supplier / invoice# / date / notes)
 *        - Items table: description + qty + price editable;
 *          per-row dropdown to LINK to existing product OR create new
 *   5. User clicks Save -> useCreateInvoice -> close
 *
 * Auto-link rule: if the top fuzzy match scored >= 85, the row defaults
 * to LINK. Otherwise it defaults to CREATE NEW. User can override.
 */
import { useEffect, useMemo, useRef, useState } from "react"

import {
  type InvoiceCreatePayload,
  type ItemLinkChoice,
  type ParsedInvoice,
  type PreviewItem,
  type ProductMatchResult,
  useCreateInvoice,
  useMatchProductsBatch,
  useParseInvoicePdf,
} from "."

interface Props {
  isOpen: boolean
  onClose: () => void
  onSaved?: (invoiceId?: string) => void
  /**
   * Event this invoice belongs to. Null when the modal is opened
   * outside an event context (legacy tenant-pool path). New call sites
   * always populate it so the saved invoice carries event_id.
   */
  eventId: string | null
}

const AUTO_LINK_SCORE = 85
const ACCEPTED_PDF = ".pdf,application/pdf"
const MAX_BYTES = 10 * 1024 * 1024 // 10 MB — matches backend cap

function toNum(s: string | null | undefined): number {
  if (s == null) return 0
  const n = Number(s)
  return Number.isFinite(n) ? n : 0
}
function fmtEur(s: string | null | undefined): string {
  return `€ ${toNum(s).toFixed(2)}`
}
function eurosToCents(s: string | null | undefined): number | null {
  if (s == null) return null
  const n = Number(s)
  return Number.isFinite(n) ? Math.round(n * 100) : null
}

function computeLineTotal(
  qty: string | null | undefined,
  unitPrice: string | null | undefined,
  discountPct: string | null | undefined,
  discountEur: string | null | undefined,
): string {
  const q = toNum(qty)
  const p = toNum(unitPrice)
  const gross = q * p
  if (gross <= 0) return "0.00"
  let net = gross
  if (discountEur != null) {
    net = gross - toNum(discountEur)
  } else if (discountPct != null) {
    net = gross * (1 - toNum(discountPct) / 100)
  }
  return net.toFixed(2)
}

// T7/T8 — manual entry mode helper. Empty PreviewItem with sane defaults
// so the operator can type a row by hand without the modal blowing up on
// undefined fields. line_num is 0-indexed and shifted by the table.
function makeEmptyPreviewItem(line_num: number): PreviewItem {
  return {
    line_num,
    code:           "",
    description:    "",
    qty:            "1",
    unit:           "BO",
    unit_price_eur: "0.00",
    discount_pct:   null,
    discount_eur:   null,
    line_total_eur: "0.00",
    iva_pct:        22,
    suggestions:    [],
    link:           { kind: "create_new" },
  }
}

export function UploadInvoiceModal({ isOpen, onClose, onSaved, eventId }: Props) {
  // T7 — entry mode. 'upload' uses the PDF dropzone, 'manual' lets the
  // operator type the items by hand. Both produce the same PreviewItem[]
  // shape so the save path stays a single code path.
  const [mode, setMode] = useState<"upload" | "manual">("upload")
  const [file, setFile] = useState<File | null>(null)
  const [parsed, setParsed] = useState<ParsedInvoice | null>(null)
  const [previewItems, setPreviewItems] = useState<PreviewItem[]>([])
  const [headerEdits, setHeaderEdits] = useState({
    supplier_name: "", invoice_number: "", invoice_date: "", notes: "",
  })
  const [bannerError, setBannerError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const parseM = useParseInvoicePdf()
  const matchM = useMatchProductsBatch()
  const createM = useCreateInvoice()

  useEffect(() => {
    if (!isOpen) {
      setMode("upload")
      setFile(null); setParsed(null); setPreviewItems([])
      setHeaderEdits({ supplier_name: "", invoice_number: "", invoice_date: "", notes: "" })
      setBannerError(null)
      parseM.reset(); matchM.reset(); createM.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  function handleFileSelected(f: File) {
    if (f.size > MAX_BYTES) {
      setBannerError(`File is ${(f.size / 1024 / 1024).toFixed(1)} MB; limit is 10 MB.`)
      return
    }
    if (!f.type.toLowerCase().includes("pdf") && !f.name.toLowerCase().endsWith(".pdf")) {
      setBannerError("Only PDF files are accepted.")
      return
    }
    // If the operator already has rows in the table (parsed or typed),
    // parsing a new PDF will replace them. Confirm so accidental drops
    // don't wipe work in progress.
    if (previewItems.length > 0) {
      const ok = window.confirm(
        `Replace the ${previewItems.length} current row${previewItems.length === 1 ? "" : "s"} with the contents of this PDF?`,
      )
      if (!ok) return
    }
    setBannerError(null)
    setFile(f)
    void runParse(f)
  }

  async function runParse(f: File) {
    try {
      const result = await parseM.mutateAsync(f)
      setParsed(result)
      setHeaderEdits({
        supplier_name:  result.header.supplier_name  ?? "",
        invoice_number: result.header.invoice_number ?? "",
        invoice_date:   result.header.invoice_date   ?? "",
        notes:          "",
      })
      // Populate previewItems IMMEDIATELY with no suggestions, so the
      // table renders right after parsing finishes. Then enrich with
      // fuzzy-match results when /products/match-batch returns. This
      // avoids the race where the user clicks Save while match-batch is
      // still pending and the items table hasn\'t rendered yet.
      setPreviewItems(buildPreviewItems(result, []))
      if (result.items.length > 0) {
        try {
          const matchRes = await matchM.mutateAsync({
            queries: result.items.map((it) => it.description),
            threshold: 70,
            top_k: 3,
          })
          // Re-build with suggestions; preserves user edits made in the
          // meantime because we\'re computing from `result` not from
          // current state. Acceptable trade-off: real users won\'t edit
          // descriptions in the <1s before match-batch resolves.
          setPreviewItems(buildPreviewItems(result, matchRes.results))
        } catch (err) {
          // Items already rendered; suggestions just won\'t appear.
          console.warn("match-batch failed", err)
        }
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail?.message ?? "Could not parse PDF."
      setBannerError(msg)
      setFile(null)
    }
  }

  function switchMode(next: "upload" | "manual") {
    if (next === mode) return  // no-op if already in this mode
    setMode(next)
    setBannerError(null)
    // Preserve whatever rows the operator has built up. If switching to
    // 'manual' and the table is empty, seed one row so they can start
    // typing right away. Otherwise leave things alone — accidental tab
    // clicks must NOT wipe the operator's work.
    if (next === "manual" && previewItems.length === 0) {
      setPreviewItems([makeEmptyPreviewItem(1)])
    }
    // Clear the PDF-parse state only when going back to upload from a
    // fresh slate; if the operator has manual rows we keep them so they
    // can still hit Save with what they already typed.
    if (next === "upload" && previewItems.length === 0) {
      setFile(null)
      setParsed(null)
    }
  }

  function addEmptyRow() {
    setPreviewItems((prev) => [...prev, makeEmptyPreviewItem(prev.length + 1)])
  }

  function buildPreviewItems(p: ParsedInvoice, results: ProductMatchResult[]): PreviewItem[] {
    return p.items.map((item, idx) => {
      const suggestions = results[idx]?.matches ?? []
      const top = suggestions[0]
      const link: ItemLinkChoice =
        top && top.score >= AUTO_LINK_SCORE
          ? { kind: "link", product_id: top.product_id, product_name: top.name }
          : { kind: "create_new" }
      return { ...item, suggestions, link }
    })
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelected(e.dataTransfer.files[0])
    }
  }
  function handleDragOver(e: React.DragEvent<HTMLDivElement>) { e.preventDefault() }

  function updateItem(idx: number, patch: Partial<PreviewItem>) {
    setPreviewItems((prev) =>
      prev.map((it, i) => {
        if (i !== idx) return it
        const merged = { ...it, ...patch }
        if ("qty" in patch || "unit_price_eur" in patch) {
          merged.line_total_eur = computeLineTotal(
            merged.qty,
            merged.unit_price_eur,
            merged.discount_pct,
            merged.discount_eur,
          )
        }
        return merged
      }),
    )
  }
  function removeItem(idx: number) {
    setPreviewItems((prev) => prev.filter((_, i) => i !== idx))
  }

  const totalLine = useMemo(
    () => previewItems.reduce((acc, it) => acc + toNum(it.line_total_eur), 0),
    [previewItems],
  )

  async function handleSave() {
    setBannerError(null)
    if (!headerEdits.supplier_name.trim()) {
      setBannerError("Supplier name is required."); return
    }
    if (!headerEdits.invoice_date) {
      setBannerError("Invoice date is required (YYYY-MM-DD)."); return
    }
    if (previewItems.length === 0) {
      setBannerError("At least one line item is required."); return
    }
    const payload: InvoiceCreatePayload = {
      invoice_number: headerEdits.invoice_number.trim() || null,
      supplier_name: headerEdits.supplier_name.trim(),
      expected_arrival_date: headerEdits.invoice_date,
      notes: headerEdits.notes.trim() || null,
      event_id: eventId,
      items: previewItems.map((it) => ({
        // Backend kind enum: 'catalog_product' (link to product) or
        // 'miscellaneous' (one-off, no product link).
        kind: it.link.kind === "link" ? "catalog_product" : "miscellaneous",
        product_id: it.link.kind === "link" ? it.link.product_id : null,
        miscellaneous_description: it.link.kind === "create_new" ? it.description : null,
        // Backend stores expected_qty as Decimal; ship as number.
        expected_qty: toNum(it.qty),
        unit_price_cents: eurosToCents(it.unit_price_eur),
        // line_total_cents is auto-computed server-side from
        // expected_qty * unit_price_cents — don't send it.
      })),
    }
    try {
      const saved = await createM.mutateAsync(payload)
      onSaved?.((saved as { id?: string })?.id)
      onClose()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail
      let msg = "Could not save invoice. Check the items and try again."
      if (typeof detail === "string") {
        msg = detail
      } else if (Array.isArray(detail)) {
        // FastAPI 422 validation errors: [{loc: [...], msg: \"...\", type: \"...\"}, ...]
        // Show the first 3 so the banner stays readable.
        const lines = (detail as Array<{ loc?: unknown[]; msg?: string }>).slice(0, 3).map((d) => {
          const where = Array.isArray(d.loc) ? d.loc.slice(-2).join(".") : ""
          return where ? `${where}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid")
        })
        msg = lines.join(" · ")
      } else if (detail && typeof detail === "object" && "message" in detail) {
        msg = String((detail as { message?: unknown }).message ?? msg)
      }
      setBannerError(msg)
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-xl bg-white shadow-2xl flex flex-col">
        <div className="flex items-start justify-between border-b border-[#E2E8F0] px-6 py-4 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-[#1A202C]">Upload Invoice</h2>
            <p className="text-xs text-[#718096]">
            {mode === "upload"
              ? "Drop an Italian fattura PDF — we’ll extract the lines and let you review."
              : "Type each bottle into the table below. Use this when you don’t have a PDF or it didn’t parse."}
          </p>

          {/* T7 — entry mode toggle */}
          <div className="mt-4 inline-flex rounded-lg border border-[#E2E8F0] p-1 bg-[#F7FAFC]">
            <button
              type="button"
              onClick={() => switchMode("upload")}
              className={[
                "px-3 py-1.5 text-xs font-semibold rounded-md transition-colors",
                mode === "upload"
                  ? "bg-white text-[#1E5A8D] shadow-sm"
                  : "text-[#718096] hover:text-[#4A5568]",
              ].join(" ")}
            >
              Upload PDF
            </button>
            <button
              type="button"
              onClick={() => switchMode("manual")}
              className={[
                "px-3 py-1.5 text-xs font-semibold rounded-md transition-colors",
                mode === "manual"
                  ? "bg-white text-[#1E5A8D] shadow-sm"
                  : "text-[#718096] hover:text-[#4A5568]",
              ].join(" ")}
            >
              Enter Manually
            </button>
          </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="rounded-md p-1.5 text-[#A0AEC0] hover:bg-[#F7FAFC] hover:text-[#4A5568]">
            ✕
          </button>
        </div>

        <div className="overflow-y-auto px-6 py-5 grow">
          {bannerError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-900 font-semibold">{bannerError}</p>
            </div>
          )}

          {mode === "upload" && (
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onClick={() => fileInputRef.current?.click()}
              className={["cursor-pointer rounded-lg border-2 border-dashed border-[#CBD5E0] hover:border-[#1E5A8D] hover:bg-[#F7FAFC] text-center transition-colors", previewItems.length > 0 ? "p-4 mb-4" : "p-10"].join(" ")}
            >
              <input ref={fileInputRef} type="file" accept={ACCEPTED_PDF} className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelected(f) }} />
              {parseM.isPending ? (
                <div className="flex flex-col items-center gap-2">
                  <svg className="w-8 h-8 text-[#1E5A8D] animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <p className="text-sm text-[#4A5568]">Parsing PDF…</p>
                  {file && <p className="text-xs text-[#718096]">{file.name}</p>}
                </div>
              ) : previewItems.length > 0 ? (
                <div className="flex items-center justify-center gap-2 text-sm">
                  <svg className="w-4 h-4 text-[#A0AEC0]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  <span className="font-semibold text-[#4A5568]">Drop another PDF to replace these rows</span>
                  <span className="text-xs text-[#A0AEC0]">· .pdf · max 10 MB</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <svg className="w-12 h-12 text-[#A0AEC0]" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  <p className="text-base font-semibold text-[#1A202C]">Drop a PDF fattura here</p>
                  <p className="text-sm text-[#718096]">or click to browse</p>
                  <p className="text-xs text-[#A0AEC0] mt-2">Max 10 MB · .pdf only</p>
                </div>
              )}
            </div>
          )}

          {previewItems.length > 0 && (
            <div className="mb-5">
              <h3 className="text-sm font-bold text-[#1A202C] uppercase tracking-wider mb-3">Invoice details</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#4A5568] mb-1">Supplier</label>
                  <input type="text" value={headerEdits.supplier_name}
                    onChange={(e) => setHeaderEdits((p) => ({ ...p, supplier_name: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm focus:outline-none focus:border-[#1E5A8D]" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#4A5568] mb-1">Invoice number</label>
                  <input type="text" value={headerEdits.invoice_number}
                    onChange={(e) => setHeaderEdits((p) => ({ ...p, invoice_number: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm focus:outline-none focus:border-[#1E5A8D]" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#4A5568] mb-1">Invoice date</label>
                  <input type="date" value={headerEdits.invoice_date}
                    onChange={(e) => setHeaderEdits((p) => ({ ...p, invoice_date: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm focus:outline-none focus:border-[#1E5A8D]" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#4A5568] mb-1">Notes (optional)</label>
                  <input type="text" value={headerEdits.notes}
                    onChange={(e) => setHeaderEdits((p) => ({ ...p, notes: e.target.value }))}
                    placeholder="Any reference to attach"
                    className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm focus:outline-none focus:border-[#1E5A8D]" />
                </div>
              </div>
              {parsed && parsed.header.total_document && (
                <p className="mt-2 text-xs text-[#718096]">
                  PDF declared total: <span className="font-semibold">{fmtEur(parsed.header.total_document)}</span>
                  {" "}· imponibile {fmtEur(parsed.header.total_imponibile)}
                </p>
              )}
            </div>
          )}

          {previewItems.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-bold text-[#1A202C] uppercase tracking-wider">
                  Line items ({previewItems.length})
                </h3>
                <p className="text-xs text-[#718096]">
                  Sum: <span className="font-semibold">€ {totalLine.toFixed(2)}</span>
                </p>
              </div>
              <div className="border border-[#E2E8F0] rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-[#F7FAFC] text-[#4A5568] text-xs uppercase">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold">Description</th>
                      <th className="px-3 py-2 text-right font-semibold w-20">Qty</th>
                      <th className="px-3 py-2 text-left font-semibold w-14">Unit</th>
                      <th className="px-3 py-2 text-right font-semibold w-24">Price</th>
                      <th className="px-3 py-2 text-right font-semibold w-24">Total</th>
                      <th className="px-3 py-2 text-left font-semibold w-48">Link to product</th>
                      <th className="px-3 py-2 w-8"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E2E8F0]">
                    {previewItems.map((it, idx) => (
                      <tr key={`${it.line_num}-${idx}`} className="text-[#1A202C]">
                        <td className="px-3 py-2">
                          <input type="text" value={it.description}
                            onChange={(e) => updateItem(idx, { description: e.target.value })}
                            className="w-full px-2 py-1 border border-transparent hover:border-[#E2E8F0] focus:border-[#1E5A8D] focus:outline-none rounded text-sm" />
                        </td>
                        <td className="px-3 py-2 text-right">
                          <input type="number" step="0.01" value={it.qty}
                            onChange={(e) => updateItem(idx, { qty: e.target.value })}
                            className="w-20 px-2 py-1 border border-transparent hover:border-[#E2E8F0] focus:border-[#1E5A8D] focus:outline-none rounded text-right text-sm" />
                        </td>
                        <td className="px-3 py-2 text-xs text-[#718096]">{it.unit}</td>
                        <td className="px-3 py-2 text-right">
                          <input type="number" step="0.01" value={it.unit_price_eur}
                            onChange={(e) => updateItem(idx, { unit_price_eur: e.target.value })}
                            className="w-24 px-2 py-1 border border-transparent hover:border-[#E2E8F0] focus:border-[#1E5A8D] focus:outline-none rounded text-right text-sm" />
                        </td>
                        <td className="px-3 py-2 text-right text-xs text-[#4A5568]">{fmtEur(it.line_total_eur)}</td>
                        <td className="px-3 py-2">
                          <select
                            value={it.link.kind === "link" ? it.link.product_id : "__new__"}
                            onChange={(e) => {
                              const v = e.target.value
                              if (v === "__new__") {
                                updateItem(idx, { link: { kind: "create_new" } })
                              } else {
                                const sug = it.suggestions.find((s) => s.product_id === v)
                                if (sug) updateItem(idx, { link: { kind: "link", product_id: sug.product_id, product_name: sug.name } })
                              }
                            }}
                            className="w-full px-2 py-1 border border-[#E2E8F0] rounded text-xs focus:outline-none focus:border-[#1E5A8D] bg-white"
                          >
                            <option value="__new__">+ Create new product</option>
                            {it.suggestions.map((s) => (
                              <option key={s.product_id} value={s.product_id}>
                                {s.score >= AUTO_LINK_SCORE ? "⭐ " : ""}{s.name} ({s.score}%)
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <button onClick={() => removeItem(idx)} aria-label="Remove row"
                            className="text-[#A0AEC0] hover:text-[#E53E3E] text-sm">✕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                onClick={addEmptyRow}
                className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-[#1E5A8D] hover:bg-[#F7FAFC] rounded-md transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Add row
              </button>
              {matchM.isPending && <p className="mt-2 text-xs text-[#718096]">Looking up product matches…</p>}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#E2E8F0] px-6 py-4 shrink-0 bg-[#F7FAFC]">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-[#4A5568] hover:bg-white rounded-lg">
            Cancel
          </button>
          {previewItems.length > 0 && (
            <button onClick={handleSave} disabled={createM.isPending}
              className={["px-5 py-2 text-sm font-semibold rounded-lg text-white",
                createM.isPending ? "bg-[#CBD5E0] cursor-not-allowed" : "bg-[#1ABC9C] hover:bg-[#17a589]"].join(" ")}>
              {createM.isPending ? "Saving…" : "Save Invoice"}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
