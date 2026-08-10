/**
 * ChargeBarCard — one bar's pre-event "charge" form (Chunk 3b).
 *
 * Omar builds a local "pending" list (bottle + qty rows), then clicks
 * "Charge {BAR NAME}" to fire one dispatch POST per row. Rows that
 * succeed disappear; rows that fail stay with a red error so Omar can
 * retry just those. Uses the same Card shell, padding and typography as
 * the dashboard's BarCard so a bar reads identically wherever it appears.
 */
import { useState } from 'react'

import type { BarRow } from '@/lib/mockData'
import type { SupplierProduct } from '@/features/event_storage/types'
import { useChargeBarDispatch } from '@/features/event_storage/useChargeBars'
import { inputCls, Label } from '@/design-system/wizardForm'
import { Badge, Button } from '@/design-system/components'
import '@/design-system/components/components.css'

interface PendingCharge {
  client_id: string
  supplier_product_id: string
  qty: number
  error?: string
}

interface Props {
  bar: BarRow
  eventId: string
  supplierProducts: SupplierProduct[]
  readOnly: boolean
  onToast: (message: string) => void
}

function makeClientId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `cb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function extractErrorMessage(err: unknown): string {
  const detail = (err as {
    response?: { data?: { detail?: { message?: string; error?: string } | string } }
  })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (err instanceof Error) return err.message
  return 'Failed to charge — try again'
}

export function ChargeBarCard({ bar, eventId, supplierProducts, readOnly, onToast }: Props) {
  const dispatchMutation = useChargeBarDispatch(eventId)

  const [pending, setPending] = useState<PendingCharge[]>([])
  const [selectedBottleId, setSelectedBottleId] = useState<string>(supplierProducts[0]?.id ?? '')
  const [qty, setQty] = useState<number>(1)
  const [isCharging, setIsCharging] = useState(false)

  const bottleName = (id: string) =>
    supplierProducts.find((sp) => sp.id === id)?.item_name ?? '(unknown bottle)'

  function addRow() {
    if (!selectedBottleId || qty <= 0) return
    setPending((prev) => [...prev, {
      client_id: makeClientId(),
      supplier_product_id: selectedBottleId,
      qty,
    }])
    setQty(1)
  }

  function removeRow(clientId: string) {
    setPending((prev) => prev.filter((p) => p.client_id !== clientId))
  }

  async function handleCharge() {
    if (pending.length === 0 || isCharging) return
    setIsCharging(true)

    const results = await Promise.allSettled(
      pending.map((p) =>
        dispatchMutation.mutateAsync({
          supplier_product_id: p.supplier_product_id,
          bar_id: bar.id,
          qty_allocated: String(p.qty),
        }),
      ),
    )

    const succeeded: PendingCharge[] = []
    const remaining: PendingCharge[] = []
    results.forEach((r, i) => {
      const row = pending[i]
      if (r.status === 'fulfilled') {
        succeeded.push(row)
      } else {
        remaining.push({ ...row, error: extractErrorMessage(r.reason) })
      }
    })

    setPending(remaining)
    setIsCharging(false)

    if (succeeded.length === 1) {
      onToast(`Charged ${succeeded[0].qty} × ${bottleName(succeeded[0].supplier_product_id)} to ${bar.name}`)
    } else if (succeeded.length > 1) {
      onToast(`Charged ${succeeded.length} item${succeeded.length === 1 ? '' : 's'} to ${bar.name}`)
    }
  }

  return (
    <div
      className="v-card p-4"
      style={{ borderLeft: `2px solid ${bar.slesh_negozio_id ? 'var(--v-cyan)' : 'var(--v-amber)'}` }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>{bar.name}</h3>
        {bar.slesh_negozio_id ? (
          <span className="text-xs" style={{ color: 'var(--v-text-muted)' }}>Slesh shop: {bar.slesh_negozio_id}</span>
        ) : (
          <Badge variant="warning">No Slesh shop linked</Badge>
        )}
      </div>

      {!readOnly && (
        <div className="grid grid-cols-12 gap-2 items-end mb-3">
          <div className="col-span-7">
            <Label>Bottle</Label>
            <select
              className={inputCls}
              value={selectedBottleId}
              onChange={(e) => setSelectedBottleId(e.target.value)}
            >
              <option value="">— select bottle —</option>
              {supplierProducts.map((sp) => (
                <option key={sp.id} value={sp.id}>{sp.item_name}</option>
              ))}
            </select>
          </div>
          <div className="col-span-3">
            <Label>Qty</Label>
            <input
              type="number"
              min={1}
              step={1}
              className={inputCls}
              value={qty}
              onChange={(e) => setQty(Math.max(1, Math.floor(Number(e.target.value) || 1)))}
            />
          </div>
          <div className="col-span-2">
            <button
              onClick={addRow}
              disabled={!selectedBottleId}
              className="w-full h-[38px] text-sm font-semibold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ color: 'var(--v-cyan)', border: '1px dashed var(--v-border)' }}
            >
              + Add row
            </button>
          </div>
        </div>
      )}

      {pending.length > 0 && (
        <div className="mb-3 rounded-[var(--v-radius)] p-3 space-y-1.5" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}>
          <p className="text-xs font-semibold" style={{ color: 'var(--v-text-muted)' }}>Pending charges (unsaved)</p>
          {pending.map((p) => (
            <div key={p.client_id}>
              <div className="flex items-center justify-between text-sm">
                <span style={{ color: 'var(--v-text)' }}>
                  {bottleName(p.supplier_product_id)} × {p.qty}
                </span>
                {!readOnly && (
                  <button
                    onClick={() => removeRow(p.client_id)}
                    className="rounded px-2 py-0.5 text-sm transition-colors"
                    style={{ color: 'var(--v-pink)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255, 61, 113, 0.08)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    aria-label={`Remove ${bottleName(p.supplier_product_id)}`}
                  >
                    ×
                  </button>
                )}
              </div>
              {p.error && <p className="text-xs" style={{ color: 'var(--v-pink)' }}>{p.error}</p>}
            </div>
          ))}
        </div>
      )}

      {!readOnly && (
        <Button
          variant="primary"
          onClick={handleCharge}
          disabled={pending.length === 0 || isCharging}
          style={{ width: '100%' }}
        >
          {isCharging ? 'Charging…' : `Charge ${bar.name}`}
        </Button>
      )}
    </div>
  )
}
