/**
 * EventWizardPage \u2014 the redesigned Create Event flow (Phase 4).
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
 *   \u2022 Submit / finalize \u2014 the Finalize step is a placeholder until
 *     the backend finalize endpoint lands
 *   \u2022 Real-time validation \u2014 each step component owns its own
 *     validation; the page only walks them through
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useAuth } from "@/features/auth/useAuth"
import { buildEmptyWizardState, type WizardState } from "./types"
import { clearDraft, loadDraft, saveDraft } from "./storage"

import { WizardStep1Basics }   from "./steps/WizardStep1Basics"
import { WizardStep2Upload }   from "./steps/WizardStep2Upload"
import { WizardStep3Bars }     from "./steps/WizardStep3Bars"
import { WizardStep4Recharge } from "./steps/WizardStep4Recharge"

// Tabs metadata \u2014 keep in sync with current_step (1..4).
const TABS: { num: 1 | 2 | 3 | 4; label: string }[] = [
  { num: 1, label: "Basics"   },
  { num: 2, label: "Upload"   },
  { num: 3, label: "Bars"     },
  { num: 4, label: "Recharge" },
]

/**
 * Outer wrapper \u2014 gates the wizard mount on `useAuth` having resolved.
 *
 * If we render the inner Content before `user` loads, `useState(init)` runs
 * once with userId="anon", and localStorage save/load use the wrong key.
 * On refresh, the same race plays out and the draft never persists. By
 * gating render on a real user, useState init runs ONCE with the correct
 * userId and persistence behaves.
 */
export default function EventWizardPage() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return null   // RequireAuth already guards this, but defensive
  return <EventWizardContent userId={user.id} />
}

interface ContentProps {
  userId: string
}

function EventWizardContent({ userId }: ContentProps) {
  const navigate = useNavigate()

  // ── State init: restore draft if one exists, otherwise empty
  const [state, setState] = useState<WizardState>(() => {
    const draft = loadDraft(userId)
    return draft ?? buildEmptyWizardState()
  })

  // ── Draft persistence: debounced save on every state change.
  // We deliberately do NOT gate on state.is_dirty here. is_dirty is a UI
  // flag for the "Draft auto-saved" indicator; gating the save itself on
  // it would mean step-navigation changes (which go through setState
  // directly, not the onChange wrapper) never persist. Bug caught
  // Jun 21 2026 \u2014 the first version had `if (!is_dirty) return`
  // and refresh always reset to step 1.
  const saveTimer = useRef<number | null>(null)
  const hasMounted = useRef(false)
  useEffect(() => {
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
  }, [state, userId])

  // ── Wraps setState to auto-flag is_dirty so the draft save fires.
  const onChange = (next: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...next, is_dirty: true }))
  }

  // ── Navigation helpers
  const goToStep = (num: 1 | 2 | 3 | 4) => {
    setState((prev) => ({ ...prev, current_step: num }))
  }

  const goBack = () => {
    if (state.current_step > 1) {
      goToStep((state.current_step - 1) as 1 | 2 | 3 | 4)
    }
  }

  const goForward = () => {
    if (state.current_step < 4) {
      goToStep((state.current_step + 1) as 1 | 2 | 3 | 4)
    }
  }

  const onDiscard = () => {
    const confirmed = window.confirm(
      "Discard this draft? Anything you\u2019ve entered will be lost."
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
    }
  }, [state.current_step, state])

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">Create Event</h1>
          <p className="text-sm text-[#4A5568] mt-1">
            New wizard flow \u00B7 work-in-progress preview
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state.is_dirty && (
            <span className="text-xs text-[#A0AEC0]">Draft auto-saved</span>
          )}
          <button
            onClick={onDiscard}
            className="text-sm text-[#718096] hover:text-[#E53E3E] px-3 py-1.5"
          >
            Discard draft
          </button>
        </div>
      </div>

      {/* Step tabs */}
      <div className="flex items-center gap-2 mb-6 border-b border-[#E2E8F0]">
        {TABS.map((tab) => {
          const isActive   = state.current_step === tab.num
          const isReachable = tab.num <= state.current_step
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

      {/* Footer */}
      <div className="flex items-center justify-between">
        <button
          onClick={goBack}
          disabled={state.current_step === 1}
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
          onClick={state.current_step < 4 ? goForward : undefined}
          disabled={state.current_step === 4}
          className={[
            "px-5 py-2 text-sm font-semibold rounded-lg transition-colors text-white",
            state.current_step < 4
              ? "bg-[#1ABC9C] hover:bg-[#17a589]"
              : "bg-[#CBD5E0] cursor-not-allowed",
          ].join(" ")}
        >
          {state.current_step < 4 ? "Save & Continue" : "Finalize (coming soon)"}
        </button>
      </div>
    </div>
  )
}
