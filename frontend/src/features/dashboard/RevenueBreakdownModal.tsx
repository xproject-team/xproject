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
import { Badge, EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

interface Props {
  data: RevenueBreakdownDTO | null
  open: boolean
  onClose: () => void
}

const SECTION_HEADER = 'text-[11px] font-semibold uppercase tracking-[0.06em] mb-2'
const ROW            = 'flex items-center justify-between py-1 text-sm'

// Semantic color roles (locked Day 4/5): positive / owner take-home /
// collected / forfeited-to-owner -> green. negative / deductions /
// returned / VAT rows -> pink. Everything else stays plain --v-text.
const C_POSITIVE = 'var(--v-green)'
const C_NEGATIVE = 'var(--v-pink)'
const C_NEUTRAL  = 'var(--v-text)'
const C_MUTED    = 'var(--v-text-muted)'
const C_DIM      = 'var(--v-text-dim)'

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

function Row({ label, value, color = C_NEUTRAL, help }: { label: string; value: string; color?: string; help?: string }) {
  return (
    <div className={ROW}>
      <span style={{ color: C_MUTED }}>
        {label}
        {help && <Help text={help} />}
      </span>
      <span className="font-medium tabular-nums" style={{ color }}>{value}</span>
    </div>
  )
}

function Help({ text }: { text: string }) {
  return (
    <span
      className="ml-1 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help align-middle transition-colors"
      style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', color: C_DIM }}
      onMouseEnter={(e) => (e.currentTarget.style.color = C_MUTED)}
      onMouseLeave={(e) => (e.currentTarget.style.color = C_DIM)}
      title={text}
    >
      i
    </span>
  )
}

function CheckIcon() {
  return (
    <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke={C_POSITIVE} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
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

  const backdropStyle: React.CSSProperties = {
    background: 'rgba(8,9,13,0.72)',
    backdropFilter: 'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
  }
  const panelStyle: React.CSSProperties = {
    background: 'var(--v-surface-raised)',
    border: '0.5px solid var(--v-border)',
    borderRadius: 'var(--v-radius-lg)',
  }

  if (!data) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={backdropStyle} onClick={onClose}>
        <div className="p-10" style={panelStyle} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
          <p className="text-sm" style={{ color: C_MUTED }}>Loading revenue breakdown…</p>
        </div>
      </div>
    )
  }

  const { sales, deposits, fiscal, cash_flow: cashFlow, owner_waterfall: waterfall, diagnostics: diag } = data

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={backdropStyle} onClick={onClose}>
      <div
        className="max-w-4xl w-full max-h-[90vh] overflow-y-auto"
        style={panelStyle}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* ───── Header ───── */}
        <div
          className="flex items-center justify-between px-6 py-4 sticky top-0 z-10"
          style={{ borderBottom: '0.5px solid var(--v-border)', background: 'var(--v-surface-raised)', borderRadius: 'var(--v-radius-lg) var(--v-radius-lg) 0 0' }}
        >
          <div>
            <h2 className="text-base font-medium" style={{ color: C_NEUTRAL }}>Revenue breakdown</h2>
            <p className="text-xs mt-0.5" style={{ color: C_MUTED }}>{data.event_name}</p>
          </div>
          <button
            onClick={onClose}
            className="text-2xl leading-none px-1 transition-colors"
            style={{ color: C_MUTED }}
            onMouseEnter={(e) => (e.currentTarget.style.color = C_NEUTRAL)}
            onMouseLeave={(e) => (e.currentTarget.style.color = C_MUTED)}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="p-6 space-y-6">

          {/* ───── Hero: two big numbers ───── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
              <div className={SECTION_HEADER} style={{ color: C_MUTED }}>
                Total customer spending
                <Help text="What customers paid at the till across all non-refunded orders. Already includes VAT and deposits. No deductions applied — this is the gross revenue figure." />
              </div>
              <div className="text-2xl font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(data.total_billed_eur)}</div>
              <div className="text-xs mt-1" style={{ color: C_DIM }}>
                {int(data.transaction_count)} transactions · gross (VAT included)
              </div>
            </div>
            <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
              <div className={SECTION_HEADER} style={{ color: C_POSITIVE }}>
                Owner net take-home
                <Help text="Net cash kept by owner after subtracting deposits returned, VAT to Stato, and food vendor share. Before staff, venue, and supplier costs." />
              </div>
              <div className="text-2xl font-medium tabular-nums" style={{ color: C_POSITIVE }}>{eur(waterfall.net_takehome_eur)}</div>
              <div className="text-xs mt-1" style={{ color: C_MUTED }}>
                before staff / venue / supplier costs
              </div>
            </div>
          </div>

          {/* ───── Sales by bar ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>
              Sales by bar
              <Help text="Gross subtotals (includes VAT and any cup deposits). Per-bar drill-down of where the money came from." />
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: C_NEUTRAL }}>Drinks</span>
                  <span className="text-sm font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(sales.drinks_total_eur)}</span>
                </div>
                {sales.drinks_by_bar.length === 0 ? (
                  <EmptyState headline="No drinks bars" body="No drinks bars." />
                ) : sales.drinks_by_bar.map((b) => (
                  <div key={b.bar_id} className={ROW}>
                    <span style={{ color: C_MUTED }}>{b.bar_name}</span>
                    <span className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(b.revenue_eur)}</span>
                  </div>
                ))}
              </div>

              <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: C_NEUTRAL }}>
                    Food
                    <Help text={`Food-truck partners. Vendor takes ${waterfall.food_vendor_share_pct}% · owner keeps ${waterfall.food_owner_share_pct}%.`} />
                  </span>
                  <span className="text-sm font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(sales.food_total_eur)}</span>
                </div>
                {sales.food_by_bar.length === 0 ? (
                  <EmptyState headline="No food bars" body="No food bars." />
                ) : sales.food_by_bar.map((b) => (
                  <div key={b.bar_id} className={ROW}>
                    <span style={{ color: C_MUTED }}>{b.bar_name}</span>
                    <span className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(b.revenue_eur)}</span>
                  </div>
                ))}
                <div className="mt-2 pt-2 text-[11px] italic" style={{ borderTop: '0.5px solid var(--v-border)', color: C_DIM }}>
                  → <span style={{ color: C_NEGATIVE }}>{eur(waterfall.minus_food_vendor_share_eur)}</span> to vendor ·{' '}
                  <span style={{ color: C_POSITIVE }}>{eur(waterfall.food_owner_share_eur)}</span> to owner
                </div>
              </div>
            </div>

            <div className="mt-3 pt-3 flex items-center justify-between text-sm" style={{ borderTop: '0.5px solid var(--v-border)' }}>
              <span style={{ color: C_MUTED }}>
                Cash desk
                <Help text="Direct cash purchases at the cash-desk (not via wristband). E.g. tickets, merch." />
              </span>
              <span className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(sales.cash_desk_eur)}</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <span className="text-sm font-semibold" style={{ color: C_NEUTRAL }}>Subtotal</span>
              <span className="text-base font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(sales.subtotal_eur)}</span>
            </div>
          </section>

          {/* ───── Deposits ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>
              Cup deposits
              <Help text="Cup/bottle deposits collected at sale (already included in customer spending). Refunded on return, owner keeps the rest." />
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
                <div className="text-[10px] uppercase tracking-[0.06em]" style={{ color: C_MUTED }}>Collected</div>
                <div className="text-base font-medium tabular-nums" style={{ color: C_POSITIVE }}>{eur(deposits.collected_eur)}</div>
                <div className="text-[10px] mt-0.5" style={{ color: C_DIM }}>{int(deposits.collected_units)} cups/bottles</div>
              </div>
              <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
                <div className="text-[10px] uppercase tracking-[0.06em]" style={{ color: C_MUTED }}>Returned</div>
                <div className="text-base font-medium tabular-nums" style={{ color: C_NEGATIVE }}>{eur(deposits.returned_eur)}</div>
                <div className="text-[10px] mt-0.5" style={{ color: C_DIM }}>{int(deposits.returned_units)} returned</div>
              </div>
              <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
                <div className="text-[10px] uppercase tracking-[0.06em]" style={{ color: C_MUTED }}>Forfeited (owner)</div>
                <div className="text-base font-medium tabular-nums" style={{ color: C_POSITIVE }}>{eur(deposits.forfeited_eur)}</div>
                <div className="text-[10px] mt-0.5" style={{ color: C_DIM }}>
                  {int(deposits.forfeited_units)} kept · {deposits.return_rate_pct != null ? `${deposits.return_rate_pct.toFixed(1)}% return rate` : 'no data'}
                </div>
              </div>
            </div>
          </section>

          {/* ───── Fiscal ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>VAT &amp; fiscal compliance</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              <Row label="VAT collected" value={eur(fiscal.vat_eur)} color={C_NEGATIVE} help="VAT extracted from gross sales (~10% on drinks/food). Owner must remit this to Italian Stato — not owner income." />
              <Row label="Discounts" value={eur(fiscal.discounts_eur)} color={C_NEGATIVE} />
              <Row label="Fiscal gross" value={eur(fiscal.fiscal_gross_eur)} help="Revenue reported to fiscal authorities = total gross minus deposits (deposits aren't fiscally taxable until forfeited)." />
              <Row label="Fiscal net" value={eur(fiscal.fiscal_net_eur)} />
            </div>
          </section>

          {/* ───── Wristband cash flow ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>
              Wristband cash flow
              <Help text="How money flowed through the wristband system. Ricariche (top-ups) are not exposed by Slesh's public API — requires manual entry from dash.slesh.it." />
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              <div className={ROW}>
                <span style={{ color: C_MUTED }}>
                  Ricariche (top-ups)
                  {cashFlow.ricariche_eur === null && (
                    <span className="ml-2 inline-block align-middle"><Badge variant="warning">manual entry pending</Badge></span>
                  )}
                </span>
                <span className="font-medium tabular-nums" style={{ color: C_POSITIVE }}>{eur(cashFlow.ricariche_eur)}</span>
              </div>
              <Row label="Cash desk in" value={eur(cashFlow.cash_desk_in_eur)} color={C_POSITIVE} />
              <Row label="Spent at bars" value={eur(cashFlow.spent_at_bars_eur)} />
              <div className={ROW}>
                <span style={{ color: C_MUTED }}>
                  Unspent balance
                  {cashFlow.unspent_balance_eur === null && (
                    <span className="ml-2 inline-block align-middle"><Badge variant="warning">requires ricariche</Badge></span>
                  )}
                </span>
                <span className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(cashFlow.unspent_balance_eur)}</span>
              </div>
            </div>
          </section>

          {/* ───── Owner Waterfall ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>
              Owner waterfall
              <Help text="Step-by-step: how total customer spending becomes owner's net cash after all obligations." />
            </h3>
            <div className="p-4" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
              <div className="space-y-1">
                <div className={ROW}>
                  <span className="font-medium" style={{ color: C_NEUTRAL }}>Total customer spending</span>
                  <span className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{eur(waterfall.gross_revenue_eur)}</span>
                </div>
                <div className={ROW}>
                  <span style={{ color: C_MUTED }}>
                    − Deposits returned
                    <Help text="Cup/bottle refunds paid back to customers who returned their cups." />
                  </span>
                  <span className="font-medium tabular-nums" style={{ color: C_NEGATIVE }}>−{eur(waterfall.minus_deposits_returned_eur)}</span>
                </div>
                <div className={ROW}>
                  <span style={{ color: C_MUTED }}>
                    − VAT to Stato
                    <Help text="Italian VAT obligation. Legal requirement, must be remitted to government. Not owner income." />
                  </span>
                  <span className="font-medium tabular-nums" style={{ color: C_NEGATIVE }}>−{eur(waterfall.minus_vat_eur)}</span>
                </div>
                <div className={ROW}>
                  <span style={{ color: C_MUTED }}>
                    − Food vendor share ({waterfall.food_vendor_share_pct}%)
                    <Help text={`Per-event contract: food trucks keep ${waterfall.food_vendor_share_pct}%, venue keeps ${waterfall.food_owner_share_pct}% of food gross.`} />
                  </span>
                  <span className="font-medium tabular-nums" style={{ color: C_NEGATIVE }}>−{eur(waterfall.minus_food_vendor_share_eur)}</span>
                </div>
              </div>
              <div className="mt-3 pt-3 flex items-center justify-between" style={{ borderTop: '0.5px solid var(--v-border)' }}>
                <span className="flex items-center gap-1.5 text-sm font-semibold" style={{ color: C_POSITIVE }}>
                  <CheckIcon /> Owner net take-home
                </span>
                <span className="text-xl font-medium tabular-nums" style={{ color: C_POSITIVE }}>{eur(waterfall.net_takehome_eur)}</span>
              </div>
              <p className="text-[10px] italic mt-2" style={{ color: C_DIM }}>
                Net cash before staff, venue, and supplier costs.
              </p>
            </div>
          </section>

          {/* ───── Diagnostics ───── */}
          <section>
            <h3 className={SECTION_HEADER} style={{ color: C_MUTED }}>Diagnostics</h3>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
              <div><div style={{ color: C_DIM }}>Orders</div><div className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{int(diag.order_count)}</div></div>
              <div><div style={{ color: C_DIM }}>Experience</div><div className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{int(diag.experience_order_count)}</div></div>
              <div><div style={{ color: C_DIM }}>Cash-desk</div><div className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{int(diag.cash_desk_order_count)}</div></div>
              <div><div style={{ color: C_DIM }}>Cart lines</div><div className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{int(diag.cart_line_count)}</div></div>
              <div><div style={{ color: C_DIM }}>Refunded</div><div className="font-medium tabular-nums" style={{ color: C_NEUTRAL }}>{int(diag.refunded_order_count)}</div></div>
            </div>
          </section>

          {/* ───── Footer note about Slesh dashboard ───── */}
          <div className="mt-2 text-[11px] italic leading-relaxed p-3" style={{ color: C_MUTED, background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}>
            <strong className="not-italic font-semibold" style={{ color: C_NEUTRAL }}>ⓘ Slesh dashboard difference:</strong>{' '}
            Slesh's "Transato" includes the unspent wristband balance (ricariche minus consumption),
            which Slesh's public API does not expose. The gap between this report's total customer
            spending and Slesh's dashboard equals the unspent balance — see Revenue Calculation Bible.
          </div>

        </div>
      </div>
    </div>
  )
}
