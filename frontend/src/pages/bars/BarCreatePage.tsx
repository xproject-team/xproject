import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

import { useCreateBar, type BarCreatePayload } from '@/features/bars/hooks'
import { useEvents } from '@/features/events/hooks'
import type { BarType } from '@/lib/mockData'

const TYPE_OPTIONS: { value: BarType; label: string }[] = [
  { value: 'drinks',  label: 'Drinks'  },
  { value: 'food',    label: 'Food'    },
  { value: 'mixed',   label: 'Mixed'   },
  { value: 'merch',   label: 'Merch'   },
  { value: 'service', label: 'Service' },
]

interface FormErrors {
  event_id?: string
  name?:     string
}

export default function BarCreatePage() {
  const navigate = useNavigate()
  const createMutation = useCreateBar()

  const { data: events = [], isLoading: eventsLoading } = useEvents()

  const [eventId,        setEventId]        = useState<string>('')
  const [name,           setName]           = useState('')
  const [barType,        setBarType]        = useState<BarType>('drinks')
  const [sleshNegozioId, setSleshNegozioId] = useState('')
  const [isActive,       setIsActive]       = useState(true)
  const [errors,         setErrors]         = useState<FormErrors>({})

  const validate = (): FormErrors => {
    const e: FormErrors = {}
    if (!eventId)        e.event_id = 'Pick an event'
    if (!name.trim())    e.name     = 'Name is required'
    return e
  }

  const handleSubmit = async () => {
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    const payload: BarCreatePayload = {
      event_id:         eventId,
      name:             name.trim(),
      bar_type:         barType,
      slesh_negozio_id: sleshNegozioId.trim() || null,
      is_active:        isActive,
    }
    try {
      const created = await createMutation.mutateAsync(payload)
      navigate(`/bars/${created.id}`)
    } catch (err) {
      console.error('Failed to create bar:', err)
      alert(`Create failed: ${(err as Error)?.message ?? 'unknown error'}`)
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
          <h1 className="text-xl font-bold text-[#1A202C]">Create Bar</h1>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate('/bars')}
            className="text-sm font-medium text-[#4A5568] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={createMutation.isPending}
            className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors disabled:bg-[#A0AEC0]"
          >
            {createMutation.isPending ? 'Creating…' : 'Create bar'}
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl space-y-5">
          <Field label="Event" error={errors.event_id} required>
            <select
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
              disabled={eventsLoading}
              className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
            >
              <option value="">— pick an event —</option>
              {events.map((ev) => (
                <option key={ev.id} value={ev.id}>{ev.name}</option>
              ))}
            </select>
          </Field>

          <Field label="Name" error={errors.name} required>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
              placeholder="e.g. Cocktail Bar"
              autoFocus
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
            hint="Optional. If you have the Slesh shop ID, paste it here so live POS orders sync to this bar. You can also leave it blank now and add it later from the bar detail page."
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
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label:    string
  hint?:    string
  error?:   string
  required?: boolean
  children:  React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-1">
        {label}{required && <span className="text-[#E53E3E] ml-0.5">*</span>}
      </label>
      {children}
      {error && <p className="text-[11px] text-[#E53E3E] mt-1">{error}</p>}
      {hint  && !error && <p className="text-[11px] text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}
