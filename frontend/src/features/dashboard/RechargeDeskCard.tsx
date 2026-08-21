/**
 * RechargeDeskCard — top-up desk performance for the live event.
 *
 * System design rationale (Jun 21 2026):
 * The recharge desk is Omar's own operation (his staff, his Slesh devices,
 * his money flow). Attendees walk up with cash or card, tap their wristband
 * on a cashier's device, and load balance to spend at the bars. Sundance 14
 * ran 4 cashier devices and processed €26,735 across ~1,168 top-ups.
 *
 * What Omar needs to see live:
 *   1. Total loaded — top-line money-in number, anchors reconciliation
 *   2. Payment-method split — Stripe TTP vs cash, must reconcile against
 *      Stripe statement and physical till count at event end. A wild swing
 *      (e.g. 90% cash) signals a card-terminal outage.
 *   3. Cashier leaderboard — €-loaded AND top-up count per device. A low
 *      €-amount with normal top-up count means small-ticket customers; a
 *      low top-up count means a slow, broken, or absent cashier. Sundance
 *      14 shows Op·2 doing 142 top-ups vs Op·4 doing 449 — a 3.2× gap
 *      worth investigating live.
 *   4. Device active/total — broken device = no top-ups = no spend = no
 *      bar revenue. Same Staff-tile pattern as BarCard/FoodBarCard.
 *   5. Average per top-up — useful baseline. Roma natural is ~€20-25.
 *
 * Intentionally OUT of scope:
 *   - "Omar's cut" — there is no cut. Every euro loaded becomes a euro of
 *     spendable wristband balance.
 *   - Money-in-vs-money-out reconciliation — that's a dashboard-level KPI
 *     belonging in the top strip, not on this card.
 *
 * Loads via useRechargeStations(eventId). Renders nothing if the event
 * has no recharge stations configured (e.g. sim events, pre-wizard data).
 */
import type { RechargeStationKpi } from '@/lib/mockData'

import { useRechargeStations } from '@/features/recharge/hooks'
import { EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

interface RechargeDeskCardProps {
  eventId: string
}

function formatEur(cents: number): string {
  return '€' + Math.round(cents / 100).toLocaleString()
}

function pctOf(part: number, whole: number): string {
  if (whole === 0) return '0%'
  return ((part / whole) * 100).toFixed(1) + '%'
}

/** Shorten "Ss-ricarica-3@slesh.it" → "Op·3" for the leaderboard.
 *  Falls back to the raw email if the pattern doesn't match. */
function shortCashier(email: string | null): string {
  if (!email) return 'Unknown'
  const m = email.match(/-(\d+)@/)
  return m ? `Op·${m[1]}` : email.split('@')[0]
}

// Shared "card title" convention — matches every other panel on the
// Dashboard (Event Revenue, Forecast, Customer Intelligence).
function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-semibold tracking-wide uppercase" style={{ color: 'var(--v-text-muted)' }}>
      {children}
    </span>
  )
}

function PaymentSplitRow({
  label,
  amountCents,
  totalCents,
  dotColor,
}: {
  label: string
  amountCents: number
  totalCents: number
  dotColor: string
}) {
  return (
    <div className="flex items-center justify-between text-xs py-1">
      <span className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-sm" style={{ background: dotColor }} />
        <span style={{ color: 'var(--v-text-muted)' }}>{label}</span>
      </span>
      <span className="tabular-nums">
        <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{formatEur(amountCents)}</span>
        <span className="ml-2" style={{ color: 'var(--v-text-dim)' }}>({pctOf(amountCents, totalCents)})</span>
      </span>
    </div>
  )
}

function CashierRow({ device }: { device: RechargeStationKpi['devices'][number] }) {
  return (
    <li className="flex items-center justify-between text-xs py-0.5">
      <span style={{ color: 'var(--v-text-muted)' }}>{shortCashier(device.slesh_operator_email)}</span>
      <span className="tabular-nums">
        <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{formatEur(device.total_amount_cents)}</span>
        <span style={{ color: 'var(--v-text-dim)' }}> · </span>
        <span style={{ color: 'var(--v-text-muted)' }}>{device.total_transactions.toLocaleString()} top-ups</span>
      </span>
    </li>
  )
}

function RechargeDeskCardInner({ station }: { station: RechargeStationKpi }) {
  // ── Derived totals ──
  // Backend has already rolled up these aggregates across devices + payment
  // methods; we just read them straight off the station object.
  const totalCents = station.total_amount_cents
  const totalTopUps = station.total_transactions
  const avgPerTopUpCents = totalTopUps === 0 ? 0 : Math.round(totalCents / totalTopUps)

  // Devices sorted by amount descending — biggest contributors at the top.
  const cashiers = [...station.devices].sort(
    (a, b) => b.total_amount_cents - a.total_amount_cents,
  )

  return (
    <div className="v-card p-4">
      <CardTitle>Recharge Desk</CardTitle>

      {/* Header: name + cashier/top-up summary + LOADED total */}
      <div className="flex items-start justify-between mt-2 mb-1">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: 'var(--v-cyan)' }} />
          <h3 className="font-medium text-base leading-tight" style={{ color: 'var(--v-text)' }}>
            {station.name}
          </h3>
        </div>
        <div className="text-right shrink-0 ml-3">
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Loaded</p>
          <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>{formatEur(totalCents)}</p>
        </div>
      </div>
      <p className="text-xs mb-3" style={{ color: 'var(--v-text-muted)' }}>
        {station.devices_total} {station.devices_total === 1 ? 'cashier' : 'cashiers'}
        {' · '}
        {totalTopUps.toLocaleString()} top-ups
      </p>

      {/* Payment-method split */}
      <div className="mb-4">
        <p className="text-[10px] uppercase tracking-wide mb-1.5" style={{ color: 'var(--v-text-muted)' }}>
          Payment split
        </p>
        <PaymentSplitRow
          label="Stripe TTP"
          amountCents={station.stripe_ttp_amount_cents}
          totalCents={totalCents}
          dotColor="var(--v-cyan)"
        />
        <PaymentSplitRow
          label="Contanti (cash)"
          amountCents={station.contanti_amount_cents}
          totalCents={totalCents}
          dotColor="var(--v-green)"
        />
      </div>

      {/* Cashier leaderboard */}
      <div className="mb-4">
        <p className="text-[10px] uppercase tracking-wide mb-1.5" style={{ color: 'var(--v-text-muted)' }}>
          Cashier performance
        </p>
        {cashiers.length === 0 ? (
          <EmptyState headline="No cashiers yet" body="No cashier devices configured yet." />
        ) : (
          <ul className="space-y-0.5">
            {cashiers.map((d) => (
              <CashierRow key={d.id} device={d} />
            ))}
          </ul>
        )}
      </div>

      {/* Footer tiles: Avg / Desks */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Avg / Top-up</p>
          <p className="text-sm font-medium mt-0.5" style={{ color: 'var(--v-text)' }}>
            {formatEur(avgPerTopUpCents)}
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>
            {totalTopUps.toLocaleString()} top-ups
          </p>
        </div>

        <div className="rounded-[var(--v-radius-sm)] px-2.5 py-2 text-center" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>Desks</p>
          <p className="text-sm font-medium mt-0.5 flex items-center justify-center gap-0.5" style={{ color: 'var(--v-text)' }}>
            <svg className="w-3.5 h-3.5" style={{ color: 'var(--v-text-dim)' }} fill="currentColor" viewBox="0 0 20 20">
              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
            </svg>
            <span>
              <span style={{ color: station.devices_active > 0 ? 'var(--v-green)' : 'var(--v-text-dim)' }}>
                {station.devices_active}
              </span>
              <span style={{ color: 'var(--v-text-dim)' }}>/</span>
              {station.devices_total}
            </span>
          </p>
          <p className="text-[9px]" style={{ color: 'var(--v-text-dim)' }}>active</p>
        </div>
      </div>
    </div>
  )
}

export function RechargeDeskCard({ eventId }: RechargeDeskCardProps) {
  const { data: stations, isLoading, error } = useRechargeStations(eventId)

  // Loading skeleton — match height of real card so layout doesn't shift
  if (isLoading) {
    return (
      <div className="v-card p-4 animate-pulse">
        <div className="h-5 w-40 rounded mb-3" style={{ background: 'var(--v-border)' }} />
        <div className="h-3 w-32 rounded mb-4" style={{ background: 'var(--v-border)' }} />
        <div className="h-3 w-full rounded mb-1" style={{ background: 'var(--v-surface-raised)' }} />
        <div className="h-3 w-full rounded" style={{ background: 'var(--v-surface-raised)' }} />
      </div>
    )
  }

  // Network error — render nothing rather than a noisy banner. The bar grid
  // beneath is the operationally critical view; a transient recharge fetch
  // failure shouldn't push it below the fold.
  if (error) return null

  // No station configured (sim events, pre-wizard data) → hide entirely.
  // Phase 4 Create Event wizard will guarantee a station exists for every
  // new event, at which point this branch becomes "should never happen".
  if (!stations || stations.length === 0) return null

  // MVP — render only the first station. Single-station setup matches
  // Sundance reality. Multi-station support is a future feature once we
  // see events with multiple recharge locations (festival entrances).
  return <RechargeDeskCardInner station={stations[0]} />
}
