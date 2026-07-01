/**
 * EventWizardPage — the redesigned Create Event flow (Phase 4).
 *
 * Mounted at /events/create-v2 during development so it runs in parallel
 * to the existing /events/create page. Once the wizard is fully working
 * end-to-end, a small swap commit renames it to /events/create and
 * deletes the old page.
 *
 * Responsibilities:
 *   \u2022 Hold the WizardState; pass slices to each step
 *   \u2022 Persist draft to localStorage on every change (debounced)
 *   \u2022 Restore draft on mount if one exists
 *   \u2022 Navigate between steps (tabs + back/continue buttons)
 *   \u2022 Guard against accidental loss with a "discard draft" prompt
 *
 * What this page does NOT do (yet):
 *   \u2022 Submit / finalize — the Finalize step is a placeholder until
 *     the backend finalize endpoint lands
 *   \u2022 Real-time validation — each step component owns its own
 *     validation; the page only walks them through
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { useAuth } from "@/features/auth/useAuth"
import { buildEmptyWizardState, type WizardState } from "./types"
import { clearDraft, loadDraft, saveDraft } from "./storage"
import { buildFullEventPayload } from "./payload"
import { hydrateWizardState } from "./hydrate"
import { useFullEvent } from "@/features/events/useFullEvent"
import {
  useCreateFullEvent,
  useUpdateFullEvent,
  extractFullEventErrors,
  type FullEventItemError,
} from "@/features/events/useCreateFullEvent"

import { WizardStep1Basics }   from "./steps/WizardStep1Basics"
import { WizardStep2Upload }   from "./steps/WizardStep2Upload"
import { WizardStep3Bars }     from "./steps/WizardStep3Bars"
import { WizardStep4Recharge } from "./steps/WizardStep4Recharge"
import { WizardStep5Invoices } from "./steps/WizardStep5Invoices"

// Tabs metadata — keep in sync with current_step (1..5).
const TABS: { num: 1 | 2 | 3 | 4 | 5; label: string }[] = [
  { num: 1, label: "Basics"   },
  { num: 2, label: "Upload"   },
  { num: 3, label: "Bars"     },
  { num: 4, label: "Recharge" },
  { num: 5, label: "Invoices" },

]

/**
 * Outer wrapper — gates the wizard mount on `useAuth` having resolved.
 *
 * If we render the inner Content before `user` loads, `useState(init)` runs
 * once with userId="anon", and localStorage save/load use the wrong key.
 * On refresh, the same race plays out and the draft never persists. By
 * gating render on a real user, useState init runs ONCE with the correct
 * userId and persistence behaves.
 */
export default function EventWizardPage() {
  const { user, loading } = useAuth()
  const { id: routeEventId } = useParams<{ id?: string }>()
  if (loading) return null
  if (!user) return null   // RequireAuth already guards this, but defensive
  // Key on hydrateEventId so A→B route-param changes force a remount;
  // otherwise React Router v6 keeps state (including hasHydrated) across
  // param changes and B never hydrates.
  return (
    <EventWizardContent
      key={routeEventId ?? "create"}
      userId={user.id}
      hydrateEventId={routeEventId ?? null}
    />
  )
}

interface ContentProps {
  userId: string
  /** When set, wizard mounts in EDIT mode: fetches GET /events/{id}/full,
   *  hydrates WizardState from the response, disables draft persistence,
   *  and (Chunk 3b, next commit) writes via PUT instead of POST. */
  hydrateEventId: string | null
}

function EventWizardContent({ userId, hydrateEventId }: ContentProps) {
  const navigate = useNavigate()
  const isEditMode = hydrateEventId !== null

  // Edit-mode fetch (disabled when hydrateEventId === null)
  const fullEventQuery = useFullEvent(hydrateEventId)
  const [hasHydrated, setHasHydrated] = useState(false)

  // ── State init: restore draft if one exists, otherwise empty.
  // In edit mode we ignore any pre-existing create-mode draft — the
  // hydration effect below fills state from GET /events/{id}/full.
  const [state, setState] = useState<WizardState>(() => {
    if (hydrateEventId !== null) return buildEmptyWizardState()
    const draft = loadDraft(userId)
    return draft ?? buildEmptyWizardState()
  })

  // ── Edit-mode hydration: on first successful fetch, populate state
  //    from the FullEventDetail response. Guarded so re-fetches never
  //    wipe user edits (refetchOnWindowFocus is off, but belt & braces).
  useEffect(() => {
    if (!isEditMode) return
    if (hasHydrated) return
    if (!fullEventQuery.data) return
    setState(hydrateWizardState(fullEventQuery.data))
    setHasHydrated(true)
  }, [isEditMode, hasHydrated, fullEventQuery.data])

  // ── Draft persistence: debounced save on every state change.
  // We deliberately do NOT gate on state.is_dirty here. is_dirty is a UI
  // flag for the "Draft auto-saved" indicator; gating the save itself on
  // it would mean step-navigation changes (which go through setState
  // directly, not the onChange wrapper) never persist. Bug caught
  // Jun 21 2026 — the first version had `if (!is_dirty) return`
  // and refresh always reset to step 1.
  const saveTimer = useRef<number | null>(null)
  const hasMounted = useRef(false)
  useEffect(() => {
    // Edit mode: no draft persistence. Server state is the source of
    // truth; drafting an edit would confuse "did I save?" semantics.
    if (isEditMode) return
    // Skip the very first effect run (right after mount, when state was
    // freshly loaded from storage). Saving the just-loaded state back to
    // storage is harmless but wasteful and confuses the log.
    if (!hasMounted.current) {
      hasMounted.current = true
      return
    }
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      saveDraft(userId, state)
    }, 400)
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
    }
  }, [state, userId, isEditMode])

  // ── Wraps setState to auto-flag is_dirty so the draft save fires.
  const onChange = (next: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...next, is_dirty: true }))
  }

  // ── Navigation helpers
  const goToStep = (num: 1 | 2 | 3 | 4 | 5) => {
    setState((prev) => ({ ...prev, current_step: num }))
  }

  const goBack = () => {
    if (state.current_step > 1) {
      goToStep((state.current_step - 1) as 1 | 2 | 3 | 4 | 5)
    }
  }

  const goForward = () => {
    if (state.current_step < 5) {
      goToStep((state.current_step + 1) as 1 | 2 | 3 | 4 | 5)
    }
  }

  const onDiscard = () => {
    const confirmed = window.confirm(
      "Discard this draft? Anything you’ve entered will be lost."
    )
    if (!confirmed) return
    clearDraft(userId)
    setState(buildEmptyWizardState())
    navigate("/events")
  }

  // ── Render the active step body
  const StepBody = useMemo(() => {
    switch (state.current_step) {
      case 1: return <WizardStep1Basics   state={state} onChange={onChange} />
      case 2: return <WizardStep2Upload   state={state} onChange={onChange} />
      case 3: return <WizardStep3Bars     state={state} onChange={onChange} />
      case 4: return <WizardStep4Recharge state={state} onChange={onChange} />
      case 5: return <WizardStep5Invoices state={state} onChange={onChange} />
    }
  }, [state.current_step, state])

  // ── Phase 4 step 10: Finalize wiring ───────────────────────────────
  // Builds an atomic FullEventCreatePayload from the wizard state and
  // POSTs to /events/full. On success: clear draft + redirect to the
  // newly-created event\'s detail page. On 422: surface per-item errors.
  const createFull = useCreateFullEvent()
  const updateFull = useUpdateFullEvent()
  const [finalizeBanner, setFinalizeBanner] = useState<string | null>(null)
  const [finalizeItemErrors, setFinalizeItemErrors] = useState<FullEventItemError[]>([])

  function onFinalize() {
    setFinalizeBanner(null)
    setFinalizeItemErrors([])
    const { payload, preErrors } = buildFullEventPayload(state)
    if (payload === null) {
      setFinalizeBanner(preErrors.join(" · "))
      // Jump back to the earliest step that has an error so Omar can fix it
      const stepGuess: 1 | 2 | 3 | 4 | 5 =
        preErrors.some((e) => e.startsWith("Basics:")) ? 1 :
        preErrors.some((e) => e.startsWith("Bars:"))   ? 3 :
        state.current_step
      if (stepGuess !== state.current_step) goToStep(stepGuess)
      return
    }
    createFull.mutate(payload, {
      onSuccess: (result) => {
        // T5 change: do NOT navigate away yet. Step 5 (invoices) still
        // needs the event_id we just got back. Stash it in state +
        // advance the wizard. The "Done" button on Step 5 (added in
        // the JSX patch below) handles final navigation + clearDraft.
        setState((prev) => ({
          ...prev,
          event_id: result.event.id,
          current_step: 5,
          is_dirty: false,
        }))
      },
      onError: (err: unknown) => {
        const items = extractFullEventErrors(err)
        if (items && items.length > 0) {
          setFinalizeItemErrors(items)
          setFinalizeBanner(
            `Server rejected ${items.length} item${items.length === 1 ? "" : "s"}. See details below.`,
          )
        } else {
          const msg = (err as Error)?.message ?? "Unknown error"
          setFinalizeBanner(`Could not create event: ${msg}`)
        }
      },
    })
  }

  // Chunk 3b — Edit-mode save. Same shape as onFinalize but PUTs
  // instead of POSTs, targeting the hydrated event id. On success we
  // advance to Step 5 (invoice attach), matching create-mode UX.
  function onSaveEdit() {
    if (!hydrateEventId) return  // defensive; button is hidden otherwise
    setFinalizeBanner(null)
    setFinalizeItemErrors([])
    const { payload, preErrors } = buildFullEventPayload(state)
    if (payload === null) {
      setFinalizeBanner(preErrors.join(" · "))
      const stepGuess: 1 | 2 | 3 | 4 | 5 =
        preErrors.some((e) => e.startsWith("Basics:")) ? 1 :
        preErrors.some((e) => e.startsWith("Bars:"))   ? 3 :
        state.current_step
      if (stepGuess !== state.current_step) goToStep(stepGuess)
      return
    }
    updateFull.mutate(
      { eventId: hydrateEventId, payload },
      {
        onSuccess: () => {
          setState((prev) => ({
            ...prev,
            current_step: 5,
            is_dirty: false,
          }))
        },
        onError: (err: unknown) => {
          const items = extractFullEventErrors(err)
          if (items && items.length > 0) {
            setFinalizeItemErrors(items)
            setFinalizeBanner(
              `Server rejected ${items.length} item${items.length === 1 ? "" : "s"}. See details below.`,
            )
          } else {
            const msg = (err as Error)?.message ?? "Unknown error"
            setFinalizeBanner(`Could not save event: ${msg}`)
          }
        },
      },
    )
  }

  // T5 — Step 5 final navigation. Once the event has been created
  // (event_id set by onFinalize), the user uploads invoices through
  // Step 5; clicking "Done" clears the draft and lands them on the
  // brand-new event's detail page.
  function onDone() {
    if (state.event_id === null) return  // safety; button is disabled in this case
    clearDraft(userId)
    navigate(`/events/${state.event_id}`, { replace: true })
  }

  // ── Edit mode: gate render on hydration ready
  if (isEditMode && !hasHydrated) {
    if (fullEventQuery.isError) {
      return (
        <div className="max-w-4xl mx-auto px-6 py-8">
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-900 font-semibold">
              Could not load event: {(fullEventQuery.error as Error)?.message ?? "unknown error"}
            </p>
          </div>
        </div>
      )
    }
    return (
      <div className="max-w-4xl mx-auto px-6 py-8 text-center text-[#718096]">
        Loading event…
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">
            {isEditMode ? "Edit Event" : "Create Event"}
          </h1>
          <p className="text-sm text-[#4A5568] mt-1">
            {isEditMode
              ? `${state.name || "(loading…)"} · draft`
              : "New wizard flow · work-in-progress preview"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isEditMode && state.is_dirty && (
            <span className="text-xs text-[#A0AEC0]">Draft auto-saved</span>
          )}
          <button
            onClick={
              isEditMode
                ? () => {
                    if (state.is_dirty) {
                      const ok = window.confirm(
                        "Discard unsaved changes and return to the event?",
                      )
                      if (!ok) return
                    }
                    navigate(`/events/${hydrateEventId}`)
                  }
                : onDiscard
            }
            className="text-sm text-[#718096] hover:text-[#E53E3E] px-3 py-1.5"
          >
            {isEditMode ? "Cancel" : "Discard draft"}
          </button>
        </div>
      </div>


      {/* Step tabs */}
      <div className="flex items-center gap-2 mb-6 border-b border-[#E2E8F0]">
        {TABS.map((tab) => {
          const isActive   = state.current_step === tab.num
          // Edit mode: all tabs reachable from the start; the whole
          // event is already loaded. Create mode: gate to reached steps.
          const isReachable = isEditMode || tab.num <= state.current_step
          return (
            <button
              key={tab.num}
              onClick={() => isReachable && goToStep(tab.num)}
              disabled={!isReachable}
              className={[
                "flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px",
                isActive
                  ? "text-[#1E5A8D] border-[#1E5A8D]"
                  : isReachable
                    ? "text-[#718096] border-transparent hover:text-[#4A5568] hover:border-[#CBD5E0]"
                    : "text-[#CBD5E0] border-transparent cursor-not-allowed",
              ].join(" ")}
            >
              <span
                className={[
                  "w-6 h-6 rounded-full flex items-center justify-center text-xs",
                  isActive
                    ? "bg-[#1E5A8D] text-white"
                    : isReachable
                      ? "bg-[#E2E8F0] text-[#4A5568]"
                      : "bg-[#F7FAFC] text-[#CBD5E0]",
                ].join(" ")}
              >
                {tab.num}
              </span>
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Step body */}
      <div className="mb-6">{StepBody}</div>

      {/* Finalize error banner */}
      {finalizeBanner && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-900 font-semibold">{finalizeBanner}</p>
          {finalizeItemErrors.length > 0 && (
            <ul className="mt-2 text-xs text-red-900 list-disc list-inside space-y-0.5">
              {finalizeItemErrors.map((e, i) => (
                <li key={i}>
                  <span className="font-semibold">{e.section} #{e.index}:</span> {e.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between">
        <button
          onClick={goBack}
          disabled={
            state.current_step === 1 ||
            (state.current_step === 5 && state.event_id !== null)
          }
          className={[
            "px-4 py-2 text-sm font-semibold rounded-lg transition-colors",
            state.current_step === 1
              ? "text-[#CBD5E0] cursor-not-allowed"
              : "text-[#4A5568] hover:bg-[#F7FAFC]",
          ].join(" ")}
        >
          Back
        </button>
        <button
          onClick={
            isEditMode
              ? state.current_step < 4
                ? goForward
                : state.current_step === 4
                  ? onSaveEdit
                  : onDone   // Step 5
              : state.current_step < 4
                ? goForward
                : state.current_step === 4
                  ? onFinalize
                  : onDone   // Step 5
          }
          disabled={
            (state.current_step === 4 && createFull.isPending) ||
            (state.current_step === 4 && updateFull.isPending) ||
            (state.current_step === 5 && state.event_id === null)
          }
          className={[
            "px-5 py-2 text-sm font-semibold rounded-lg transition-colors text-white",
            createFull.isPending || updateFull.isPending
              ? "bg-[#CBD5E0] cursor-not-allowed"
              : "bg-[#1ABC9C] hover:bg-[#17a589]",
          ].join(" ")}
        >
          {isEditMode
            ? state.current_step < 4
              ? "Continue"
              : state.current_step === 4
                ? updateFull.isPending ? "Saving…" : "Save Changes"
                : "Done"
            : state.current_step < 4
              ? "Save & Continue"
              : state.current_step === 4
                ? createFull.isPending ? "Creating Event…" : "Create Event"
                : "Done"}
        </button>
      </div>
    </div>
  )
}
