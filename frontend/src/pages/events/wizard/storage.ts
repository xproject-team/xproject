/**
 * Draft persistence for the Create Event wizard.
 *
 * We use localStorage with a per-user key so multiple users on the same
 * machine don't step on each other's drafts. Drafts are cleared on
 * successful finalize, and on explicit "discard draft" action.
 *
 * Schema versioning: the key includes a version (`v1`). If the WizardState
 * shape changes in a backwards-incompatible way, bump the version and
 * old drafts are silently abandoned (rather than crashing).
 */
import type { WizardState } from "./types"

const VERSION = "v2"

function keyFor(userId: string): string {
  return `xproject:wizard:${VERSION}:${userId}`
}

export function saveDraft(userId: string, state: WizardState): void {
  try {
    const json = JSON.stringify(state)
    localStorage.setItem(keyFor(userId), json)
  } catch (err) {
    // Quota exceeded, private mode, etc — non-fatal. Log and continue;
    // the wizard still works, just without draft persistence.
    console.warn("wizard: could not save draft to localStorage:", err)
  }
}

export function loadDraft(userId: string): WizardState | null {
  try {
    const json = localStorage.getItem(keyFor(userId))
    if (!json) return null
    return JSON.parse(json) as WizardState
  } catch (err) {
    console.warn("wizard: could not parse stored draft, discarding:", err)
    return null
  }
}

export function clearDraft(userId: string): void {
  try {
    localStorage.removeItem(keyFor(userId))
  } catch {
    /* non-fatal */
  }
}
