import { useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'

import {
  useBar,
  useUpdateBar,
  useDeleteBar,
  type BarUpdatePayload,
} from '@/features/bars/hooks'
import { useEvent } from '@/features/events/hooks'
import type { BarRow, BarType } from '@/lib/mockData'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_OPTIONS: { value: BarType; label: string }[] = [
  { value: 'drinks',  label: 'Drinks'  },
  { value: 'food',    label: 'Food'    },
  { value: 'mixed',   label: 'Mixed'   },
  { value: 'merch',   label: 'Merch'   },
  { value: 'service', label: 'Service' },
]

// ─── Wrapper ──────────────────────────────────────────────────────────────────
// Loading/error/not-found gate. Inner content gets a guaranteed bar object.

export default function BarDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: bar, isLoading, isError, error } = useBar(id)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[#718096]">
        Loading bar…
      </div>
    )
  }
  if (isError) {
    return (
      <div className="m-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
        Failed to load bar: {(error as Error)?.message ?? 'unknown error'}
      </div>
    )
  }
  if (!bar) {
    return (
      <div className="m-6 text-sm text-[#718096]">
        Bar not found.
      </div>
    )
  }

  return <BarDetailContent bar={bar} />
}

// ─── Inner content (guaranteed non-null bar) ──────────────────────────────────

function BarDetailContent({ bar }: { bar: BarRow }) {
  const navigate = useNavigate()

  const updateMutation = useUpdateBar()
  const deleteMutation = useDeleteBar()

  // Edit form state — controlled inputs.
  const [name,             setName]             = useState(bar.name)
  const [barType,          setBarType]          = useState<BarType>(bar.bar_type)
  const [sleshNegozioId,   setSleshNegozioId]   = useState(bar.slesh_negozio_id ?? '')
  const [isActive,         setIsActive]         = useState(bar.is_active)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Look up the parent event name (cheap; React Query cache).
  const { data: event } = useEvent(bar.event_id)

  // ── Detect dirty state ──
  const dirty =
    name              !== bar.name              ||
    barType           !== bar.bar_type          ||
    (sleshNegozioId || null) !== (bar.slesh_negozio_id ?? null) ||
    isActive          !== bar.is_active

  // ── Handlers ──
  const handleSave = async () => {
    if (!dirty) return
    const payload: BarUpdatePayload = {}
    if (name              !== bar.name)              payload.name              = name.trim()
    if (barType           !== bar.bar_type)          payload.bar_type          = barType
    if ((sleshNegozioId || null) !== (bar.slesh_negozio_id ?? null)) {
      payload.slesh_negozio_id = sleshNegozioId.trim() || null
    }
    if (isActive          !== bar.is_active)         payload.is_active         = isActive
    try {
      await updateMutation.mutateAsync({ id: bar.id, payload })
    } catch (err) {
      console.error('Failed to update bar:', err)
      alert(`Update failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(bar.id)
      navigate('/bars')
    } catch (err) {
      console.error('Failed to delete bar:', err)
      alert(`Delete failed: ${(err as Error)?.message ?? 'unknown error'}`)
      setShowDeleteConfirm(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <button
            onClick={() => navigate('/bars')}
            className="text-xs text-[#1E5A8D] hover:underline mb-1"
          >
            ← Back to Bars
          </button>
          <h1 className="text-xl font-bold text-[#1A202C]">{bar.name}</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            Event: {event?.name ?? '(loading…)'} · Type: {bar.bar_type}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={!dirty || updateMutation.isPending}
            className={`text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
              dirty && !updateMutation.isPending
                ? 'text-white bg-[#1E5A8D] hover:bg-[#174870]'
                : 'text-[#A0AEC0] bg-[#F7FAFC] cursor-not-allowed'
            }`}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </button>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={deleteMutation.isPending}
            className="text-sm font-medium text-[#E53E3E] border border-[#E53E3E] px-4 py-2 rounded-lg hover:bg-red-50 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Body — edit form */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl space-y-5">
          <Field label="Name">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
              placeholder="Bar name"
            />
          </Field>

          <Field label="Type">
            <select
              value={barType}
              onChange={(e) => setBarType(e.target.value as BarType)}
              className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
            >
              {TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>

          <Field
            label="Slesh shop ID"
            hint="The Slesh _id for this shop. Used by the polling worker to map orders to this bar."
          >
            <input
              type="text"
              value={sleshNegozioId}
              onChange={(e) => setSleshNegozioId(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm font-mono"
              placeholder="e.g. 687f4dfb2bedfeed66a5f33f"
            />
          </Field>

          <Field label="Status">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4"
              />
              Active
            </label>
          </Field>

          {/* Read-only metadata */}
          <div className="pt-4 border-t border-[#E2E8F0]">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-2">
              Metadata
            </h2>
            <div className="grid grid-cols-2 gap-3 text-xs text-[#4A5568]">
              <div><span className="font-medium">ID:</span> <span className="font-mono">{bar.id}</span></div>
              <div><span className="font-medium">Event ID:</span> <span className="font-mono">{bar.event_id}</span></div>
            </div>
          </div>
        </div>
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-[#1A202C] mb-2">Delete bar?</h3>
            <p className="text-sm text-[#4A5568] mb-4">
              Deleting <span className="font-semibold">{bar.name}</span> is permanent.
              All transactions and stock rows for this bar will also be removed.
              This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="text-sm font-medium text-[#4A5568] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="text-sm font-medium text-white bg-[#E53E3E] px-4 py-2 rounded-lg hover:bg-[#C53030] transition-colors"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete bar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Tiny field wrapper ───────────────────────────────────────────────────────

function Field({
  label,
  hint,
  children,
}: {
  label:   string
  hint?:   string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-1">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}
