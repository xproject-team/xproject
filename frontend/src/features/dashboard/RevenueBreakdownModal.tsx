/**
 * RevenueBreakdownModal — full post-event revenue breakdown popup.
 *
 * Surfaces the comprehensive financial picture per the Revenue Calculation
 * Bible (docs/revenue-calculation-bible.md): total customer spending (gross,
 * no deductions) and owner net take-home as the headline hero, then per-bar
 * sales, deposit flow, VAT/fiscal compliance, wristband cash flow, and the
 * step-by-step owner waterfall showing how gross becomes net.
 *
 * Backed by GET /events/{id}/revenue-breakdown.
 */
import { useEffect } from 'react'

import type { RevenueBreakdownDTO } from '@/features/dashboard/hooks'

interface Props {
  data: RevenueBreakdownDTO | null
  open: boolean
  onClose: () => void
}

const SECTION_HEADER = 'text-[11px] font-bold uppercase tracking-widest text-[#A0AEC0] mb-2'
const ROW            = 'flex items-center justify-between py-1 text-sm'
const ROW_MUTED      = 'text-[#4A5568]'
const ROW_VALUE      = 'font-semibold text-[#1A202C] tabular-nums'

function eur(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined) return '—'
  const n = typeof amount === 'string' ? parseFloat(amount) : amount
  if (Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: 2,
  }).format(n)
}

function int(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat('it-IT').format(n)
}

function Help({ text }: { text: string }) {
  return (
    <span
      className="ml-1 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#E2E8F0] text-[#4A5568] text-[9px] font-bold cursor-help align-middle"
      title={text}
    >
      i
    </span>
  )
}

export function RevenueBreakdownModal({ data, open, onClose }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  if (!data) {
    return (
      <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
        <div
          className="bg-white rounded-2xl shadow-xl p-10"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
        >
          <p className="text-sm text-[#A0AEC0]">Loading revenue breakdown…</p>
        </div>
      </div>
    )
  }

  const { sales, deposits, fiscal, cash_flow: cashFlow, owner_waterfall: waterfall, diagnostics: diag } = data

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* ───── Header ───── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E2E8F0] sticky top-0 bg-white rounded-t-2xl z-10">
          <div>
            <h2 className="text-base font-bold text-[#1A202C]">Revenue breakdown</h2>
            <p className="text-xs text-[#4A5568] mt-0.5">{data.event_name}</p>
          </div>
          <button
            onClick={onClose}
            className="text-[#A0AEC0] hover:text-[#1A202C] text-2xl leading-none px-1"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="p-6 space-y-6">

          {/* ───── Hero: two big numbers ───── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-[#F7FAFC] rounded-xl p-4">
              <div className={SECTION_HEADER}>
                Total customer spending
                <Help text="What customers paid at the till across all non-refunded orders. Already includes VAT and deposits. No deductions applied — this is the gross revenue figure." />
              </div>
              <div className="text-2xl font-bold text-[#1A202C] tabular-nums">{eur(data.total_billed_eur)}</div>
              <div className="text-xs text-[#A0AEC0] mt-1">
                {int(data.transaction_count)} transactions · gross (VAT included)
              </div>
            </div>
            <div className="bg-[#E6F4EC] rounded-xl p-4 border border-[#2F9E6E]/30">
              <div className={SECTION_HEADER + ' !text-[#1A6F4D]'}>
                Owner net take-home
                <Help text="Net cash kept by owner after subtracting deposits returned, VAT to Stato, and food vendor share. Before staff, venue, and supplier costs." />
              </div>
              <div className="text-2xl font-bold text-[#1A6F4D] tabular-nums">{eur(waterfall.net_takehome_eur)}</div>
              <div className="text-xs text-[#1A6F4D]/70 mt-1">
                before staff / venue / supplier costs
              </div>
            </div>
          </div>

          {/* ───── Sales by bar ───── */}
          <section>
            <h3 className={SECTION_HEADER}>
              Sales by bar
              <Help text="Gross subtotals (includes VAT and any cup deposits). Per-bar drill-down of where the money came from." />
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="border border-[#E2E8F0] rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#2F9E6E]">Drinks</span>
                  <span className="text-sm font-bold text-[#1A202C] tabular-nums">{eur(sales.drinks_total_eur)}</span>
                </div>
                {sales.drinks_by_bar.length === 0 ? (
                  <p className="text-xs text-[#A0AEC0]">No drinks bars.</p>
                ) : sales.drinks_by_bar.map((b) => (
                  <div key={b.bar_id} className={ROW}>
                    <span className={ROW_MUTED}>{b.bar_name}</span>
                    <span className={ROW_VALUE}>{eur(b.revenue_eur)}</span>
                  </div>
                ))}
              </div>

              <div className="border border-[#E2E8F0] rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#DD8C1E]">
                    Food
                    <Help text={`Food-truck partners. Vendor takes ${waterfall.food_vendor_share_pct}% · owner keeps ${waterfall.food_owner_share_pct}%.`} />
                  </span>
                  <span className="text-sm font-bold text-[#1A202C] tabular-nums">{eur(sales.food_total_eur)}</span>
                </div>
                {sales.food_by_bar.length === 0 ? (
                  <p className="text-xs text-[#A0AEC0]">No food bars.</p>
                ) : sales.food_by_bar.map((b) => (
                  <div key={b.bar_id} className={ROW}>
                    <span className={ROW_MUTED}>{b.bar_name}</span>
                    <span className={ROW_VALUE}>{eur(b.revenue_eur)}</span>
                  </div>
                ))}
                <div className="mt-2 pt-2 border-t border-[#E2E8F0] text-[11px] text-[#A0AEC0] italic">
                  → {eur(waterfall.minus_food_vendor_share_eur)} to vendor · {eur(waterfall.food_owner_share_eur)} to owner
                </div>
              </div>
            </div>

            <div className="mt-3 border-t border-[#E2E8F0] pt-3 flex items-center justify-between text-sm">
              <span className="text-[#4A5568]">
                Cash desk
                <Help text="Direct cash purchases at the cash-desk (not via wristband). E.g. tickets, merch." />
              </span>
              <span className={ROW_VALUE}>{eur(sales.cash_desk_eur)}</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <span className="text-sm font-semibold text-[#1A202C]">Subtotal</span>
              <span className="text-base font-bold text-[#1A202C] tabular-nums">{eur(sales.subtotal_eur)}</span>
            </div>
          </section>

          {/* ───── Deposits ───── */}
          <section>
            <h3 className={SECTION_HEADER}>
              Cup deposits
              <Help text="Cup/bottle deposits collected at sale (already included in customer spending). Refunded on return, owner keeps the rest." />
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="bg-[#F7FAFC] rounded-xl p-3">
                <div className="text-[10px] text-[#A0AEC0] uppercase tracking-wide">Collected</div>
                <div className="text-base font-bold text-[#1A202C] tabular-nums">{eur(deposits.collected_eur)}</div>
                <div className="text-[10px] text-[#A0AEC0] mt-0.5">{int(deposits.collected_units)} cups/bottles</div>
              </div>
              <div className="bg-[#FFF5F0] rounded-xl p-3">
                <div className="text-[10px] text-[#C53030] uppercase tracking-wide">Returned</div>
                <div className="text-base font-bold text-[#C53030] tabular-nums">{eur(deposits.returned_eur)}</div>
                <div className="text-[10px] text-[#C53030]/70 mt-0.5">{int(deposits.returned_units)} returned</div>
              </div>
              <div className="bg-[#E6F4EC] rounded-xl p-3">
                <div className="text-[10px] text-[#1A6F4D] uppercase tracking-wide">Forfeited (owner)</div>
                <div className="text-base font-bold text-[#1A6F4D] tabular-nums">{eur(deposits.forfeited_eur)}</div>
                <div className="text-[10px] text-[#1A6F4D]/70 mt-0.5">
                  {int(deposits.forfeited_units)} kept · {deposits.return_rate_pct != null ? `${deposits.return_rate_pct.toFixed(1)}% return rate` : 'no data'}
                </div>
              </div>
            </div>
          </section>

          {/* ───── Fiscal ───── */}
          <section>
            <h3 className={SECTION_HEADER}>VAT &amp; fiscal compliance</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              <div className={ROW}>
                <span className={ROW_MUTED}>
                  VAT collected
                  <Help text="VAT extracted from gross sales (~10% on drinks/food). Owner must remit this to Italian Stato — not owner income." />
                </span>
                <span className={ROW_VALUE}>{eur(fiscal.vat_eur)}</span>
              </div>
              <div className={ROW}><span className={ROW_MUTED}>Discounts</span><span className={ROW_VALUE}>{eur(fiscal.discounts_eur)}</span></div>
              <div className={ROW}>
                <span className={ROW_MUTED}>
                  Fiscal gross
                  <Help text="Revenue reported to fiscal authorities = total gross minus deposits (deposits aren't fiscally taxable until forfeited)." />
                </span>
                <span className={ROW_VALUE}>{eur(fiscal.fiscal_gross_eur)}</span>
              </div>
              <div className={ROW}><span className={ROW_MUTED}>Fiscal net</span><span className={ROW_VALUE}>{eur(fiscal.fiscal_net_eur)}</span></div>
            </div>
          </section>

          {/* ───── Wristband cash flow ───── */}
          <section>
            <h3 className={SECTION_HEADER}>
              Wristband cash flow
              <Help text="How money flowed through the wristband system. Ricariche (top-ups) are not exposed by Slesh's public API — requires manual entry from dash.slesh.it." />
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              <div className={ROW}>
                <span className={ROW_MUTED}>
                  Ricariche (top-ups)
                  {cashFlow.ricariche_eur === null && (
                    <span className="ml-2 inline-block text-[10px] text-[#DD8C1E] font-semibold bg-[#FFF5E6] px-1.5 py-0.5 rounded">manual entry pending</span>
                  )}
                </span>
                <span className={ROW_VALUE}>{eur(cashFlow.ricariche_eur)}</span>
              </div>
              <div className={ROW}><span className={ROW_MUTED}>Cash desk in</span><span className={ROW_VALUE}>{eur(cashFlow.cash_desk_in_eur)}</span></div>
              <div className={ROW}><span className={ROW_MUTED}>Spent at bars</span><span className={ROW_VALUE}>{eur(cashFlow.spent_at_bars_eur)}</span></div>
              <div className={ROW}>
                <span className={ROW_MUTED}>
                  Unspent balance
                  {cashFlow.unspent_balance_eur === null && (
                    <span className="ml-2 inline-block text-[10px] text-[#DD8C1E] font-semibold bg-[#FFF5E6] px-1.5 py-0.5 rounded">requires ricariche</span>
                  )}
                </span>
                <span className={ROW_VALUE}>{eur(cashFlow.unspent_balance_eur)}</span>
              </div>
            </div>
          </section>

          {/* ───── Owner Waterfall ───── */}
          <section>
            <h3 className={SECTION_HEADER}>
              Owner waterfall
              <Help text="Step-by-step: how total customer spending becomes owner's net cash after all obligations." />
            </h3>
            <div className="border border-[#2F9E6E]/30 bg-[#F0F9F4] rounded-xl p-4">
              <div className="space-y-1">
                <div className={ROW}>
                  <span className="text-[#1A202C] font-medium">Total customer spending</span>
                  <span className={ROW_VALUE}>{eur(waterfall.gross_revenue_eur)}</span>
                </div>
                <div className={ROW}>
                  <span className={ROW_MUTED}>
                    − Deposits returned
                    <Help text="Cup/bottle refunds paid back to customers who returned their cups." />
                  </span>
                  <span className="font-semibold text-[#C53030] tabular-nums">−{eur(waterfall.minus_deposits_returned_eur)}</span>
                </div>
                <div className={ROW}>
                  <span className={ROW_MUTED}>
                    − VAT to Stato
                    <Help text="Italian VAT obligation. Legal requirement, must be remitted to government. Not owner income." />
                  </span>
                  <span className="font-semibold text-[#C53030] tabular-nums">−{eur(waterfall.minus_vat_eur)}</span>
                </div>
                <div className={ROW}>
                  <span className={ROW_MUTED}>
                    − Food vendor share ({waterfall.food_vendor_share_pct}%)
                    <Help text={`Per-event contract: food trucks keep ${waterfall.food_vendor_share_pct}%, venue keeps ${waterfall.food_owner_share_pct}% of food gross.`} />
                  </span>
                  <span className="font-semibold text-[#C53030] tabular-nums">−{eur(waterfall.minus_food_vendor_share_eur)}</span>
                </div>
              </div>
              <div className="border-t border-[#2F9E6E]/30 mt-3 pt-3 flex items-center justify-between">
                <span className="text-sm font-bold text-[#1A6F4D]">✅ Owner net take-home</span>
                <span className="text-xl font-bold text-[#1A6F4D] tabular-nums">{eur(waterfall.net_takehome_eur)}</span>
              </div>
              <p className="text-[10px] text-[#1A6F4D]/60 italic mt-2">
                Net cash before staff, venue, and supplier costs.
              </p>
            </div>
          </section>

          {/* ───── Diagnostics ───── */}
          <section>
            <h3 className={SECTION_HEADER}>Diagnostics</h3>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
              <div><div className="text-[#A0AEC0]">Orders</div><div className="font-semibold text-[#1A202C] tabular-nums">{int(diag.order_count)}</div></div>
              <div><div className="text-[#A0AEC0]">Experience</div><div className="font-semibold text-[#1A202C] tabular-nums">{int(diag.experience_order_count)}</div></div>
              <div><div className="text-[#A0AEC0]">Cash-desk</div><div className="font-semibold text-[#1A202C] tabular-nums">{int(diag.cash_desk_order_count)}</div></div>
              <div><div className="text-[#A0AEC0]">Cart lines</div><div className="font-semibold text-[#1A202C] tabular-nums">{int(diag.cart_line_count)}</div></div>
              <div><div className="text-[#A0AEC0]">Refunded</div><div className="font-semibold text-[#1A202C] tabular-nums">{int(diag.refunded_order_count)}</div></div>
            </div>
          </section>

          {/* ───── Footer note about Slesh dashboard ───── */}
          <div className="mt-2 text-[11px] text-[#4A5568] bg-[#F7FAFC] border border-[#E2E8F0] rounded-xl p-3 italic leading-relaxed">
            <strong className="not-italic font-semibold text-[#1A202C]">ⓘ Slesh dashboard difference:</strong>{' '}
            Slesh's "Transato" includes the unspent wristband balance (ricariche minus consumption),
            which Slesh's public API does not expose. The gap between this report's total customer
            spending and Slesh's dashboard equals the unspent balance — see Revenue Calculation Bible.
          </div>

        </div>
      </div>
    </div>
  )
}
