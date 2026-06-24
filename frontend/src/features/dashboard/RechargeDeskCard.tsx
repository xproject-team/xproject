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
        <span className={`w-2 h-2 rounded-sm ${dotColor}`} />
        <span className="text-[#1A202C]">{label}</span>
      </span>
      <span className="tabular-nums">
        <span className="font-semibold text-[#1A202C]">{formatEur(amountCents)}</span>
        <span className="text-[#A0AEC0] ml-2">({pctOf(amountCents, totalCents)})</span>
      </span>
    </div>
  )
}

function CashierRow({ device }: { device: RechargeStationKpi['devices'][number] }) {
  return (
    <li className="flex items-center justify-between text-xs py-0.5">
      <span className="text-[#1A202C]">{shortCashier(device.slesh_operator_email)}</span>
      <span className="tabular-nums">
        <span className="font-semibold text-[#1A202C]">{formatEur(device.total_amount_cents)}</span>
        <span className="text-[#A0AEC0]"> · </span>
        <span className="text-[#4A5568]">{device.total_transactions.toLocaleString()} top-ups</span>
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
    <div className="rounded-xl p-5 shadow-sm border bg-white border-[#E2E8F0]">
      {/* Header: name + cashier/top-up summary + LOADED total */}
      <div className="flex items-start justify-between mb-1">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#3182CE] shrink-0" />
          <h3 className="font-bold text-[#1A202C] text-base leading-tight">
            {station.name}
          </h3>
        </div>
        <div className="text-right shrink-0 ml-3">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Loaded</p>
          <p className="text-xl font-bold text-[#1A202C]">{formatEur(totalCents)}</p>
        </div>
      </div>
      <p className="text-xs text-[#4A5568] mb-3">
        {station.devices_total} {station.devices_total === 1 ? 'cashier' : 'cashiers'}
        {' · '}
        {totalTopUps.toLocaleString()} top-ups
      </p>

      {/* Payment-method split */}
      <div className="mb-4">
        <p className="text-[10px] text-[#4A5568] uppercase tracking-wide mb-1.5">
          Payment split
        </p>
        <PaymentSplitRow
          label="Stripe TTP"
          amountCents={station.stripe_ttp_amount_cents}
          totalCents={totalCents}
          dotColor="bg-[#3182CE]"
        />
        <PaymentSplitRow
          label="Contanti (cash)"
          amountCents={station.contanti_amount_cents}
          totalCents={totalCents}
          dotColor="bg-[#38A169]"
        />
      </div>

      {/* Cashier leaderboard */}
      <div className="mb-4">
        <p className="text-[10px] text-[#4A5568] uppercase tracking-wide mb-1.5">
          Cashier performance
        </p>
        {cashiers.length === 0 ? (
          <p className="text-[11px] text-[#A0AEC0] italic py-3 text-center">
            No cashier devices configured yet
          </p>
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
        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Avg / Top-up</p>
          <p className="text-sm font-bold mt-0.5 text-[#1A202C]">
            {formatEur(avgPerTopUpCents)}
          </p>
          <p className="text-[9px] text-[#4A5568]">
            {totalTopUps.toLocaleString()} top-ups
          </p>
        </div>

        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Desks</p>
          <p className="text-sm font-bold mt-0.5 flex items-center justify-center gap-0.5">
            <svg className="w-3.5 h-3.5 text-[#4A5568]" fill="currentColor" viewBox="0 0 20 20">
              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
            </svg>
            <span>
              <span className={station.devices_active > 0 ? 'text-[#38A169]' : 'text-[#A0AEC0]'}>
                {station.devices_active}
              </span>
              <span className="text-[#A0AEC0]">/</span>
              {station.devices_total}
            </span>
          </p>
          <p className="text-[9px] text-[#4A5568]">active</p>
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
      <div className="rounded-xl p-5 shadow-sm border bg-white border-[#E2E8F0] animate-pulse">
        <div className="h-5 w-40 bg-[#E2E8F0] rounded mb-3" />
        <div className="h-3 w-32 bg-[#E2E8F0] rounded mb-4" />
        <div className="h-3 w-full bg-[#F7FAFC] rounded mb-1" />
        <div className="h-3 w-full bg-[#F7FAFC] rounded" />
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
