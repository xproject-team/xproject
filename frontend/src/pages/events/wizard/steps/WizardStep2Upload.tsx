/**
 * Wizard Step 2 \u2014 Upload
 *
 * Placeholder. Real implementation lands in a follow-up commit.
 * For now this renders a single message so the wizard shell is navigable
 * end-to-end and Omar can see the structure during design review.
 */
import type { WizardState } from "../types"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

export function WizardStep2Upload({ state: _state, onChange: _onChange }: Props) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-8 text-center">
      <p className="text-[#718096] text-sm">
        Step 2 \u00B7 Upload
      </p>
      <p className="text-[#A0AEC0] text-xs mt-2">
        Coming in the next commit \u2014 Upload the Slesh project-plan .xlsx and preview parsed contents
      </p>
    </div>
  )
}
