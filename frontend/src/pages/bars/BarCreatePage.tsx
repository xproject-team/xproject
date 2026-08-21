import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

import { useCreateBar, type BarCreatePayload } from '@/features/bars/hooks'
import { useEvents } from '@/features/events/hooks'
import type { BarType } from '@/lib/mockData'
import { Button } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label, HelperText } from '@/design-system/wizardForm'

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
    <div className="p-6 max-w-2xl mx-auto">
      <button
        onClick={() => navigate('/bars')}
        className="text-xs mb-3 hover:underline"
        style={{ color: 'var(--v-cyan)' }}
      >
        ← Back to Bars
      </button>

      <h1 className="text-2xl font-medium mb-6" style={{ color: 'var(--v-text)' }}>Create Bar</h1>

      <div className="space-y-5">
        <div>
          <Label>Event *</Label>
          <select
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
            disabled={eventsLoading}
            className={inputCls}
          >
            <option value="">— pick an event —</option>
            {events.map((ev) => (
              <option key={ev.id} value={ev.id}>{ev.name}</option>
            ))}
          </select>
          {errors.event_id && (
            <p className="text-[12px] mt-1" style={{ color: 'var(--v-pink)' }}>{errors.event_id}</p>
          )}
        </div>

        <div>
          <Label>Name *</Label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
            placeholder="e.g. Cocktail Bar"
            autoFocus
          />
          {errors.name && (
            <p className="text-[12px] mt-1" style={{ color: 'var(--v-pink)' }}>{errors.name}</p>
          )}
        </div>

        <div>
          <Label>Type</Label>
          <select
            value={barType}
            onChange={(e) => setBarType(e.target.value as BarType)}
            className={inputCls}
          >
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div>
          <Label>Slesh shop ID</Label>
          <input
            type="text"
            value={sleshNegozioId}
            onChange={(e) => setSleshNegozioId(e.target.value)}
            className={`${inputCls} font-mono`}
            placeholder="e.g. 687f4dfb2bedfeed66a5f33f"
          />
          <HelperText>
            Optional. If you have the Slesh shop ID, paste it here so live POS orders sync to this
            bar. You can also leave it blank now and add it later from the bar detail page.
          </HelperText>
        </div>

        <div>
          <Label>Status</Label>
          <label className="flex items-center gap-2 text-sm" style={{ color: 'var(--v-text)' }}>
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4"
            />
            Active
          </label>
        </div>

        <div className="flex gap-2 pt-2">
          <Button variant="primary" onClick={handleSubmit} disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Creating…' : 'Create bar'}
          </Button>
          <Button variant="ghost" onClick={() => navigate('/bars')}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  )
}
