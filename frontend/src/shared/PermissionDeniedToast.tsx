/**
 * PermissionDeniedToast — global permission-denied notifier.
 *
 * Listens for the 'permission:denied' custom event dispatched by
 * <RequirePermission> in routes.tsx when a user navigates to a route
 * they're not authorized for. Shows a top-center toast for 4 seconds,
 * dismissible by click. Pure presentation; the redirect itself is
 * handled by RequirePermission via <Navigate>.
 *
 * Mounted once at the App root (next to SessionExpiredModal) so it
 * overlays every route. Pattern mirrors SessionExpiredModal verbatim —
 * codebase consistency over framework novelty.
 *
 * Sundance-safety: a silent redirect would leave Marco the Bartender
 * staring at /dashboard wondering why he can't reach /scan/arrivals.
 * This toast tells the truth: "You don't have access to /scan/arrivals".
 * No mystery, no support ticket.
 *
 * Accessibility: role="status" + aria-live="assertive" so screen
 * readers announce the toast immediately on appearance.
 */
import { useEffect, useState } from 'react'

const TOAST_DURATION_MS = 4000

interface DeniedPayload {
  attemptedPath: string
}

export function PermissionDeniedToast() {
  const [payload, setPayload] = useState<DeniedPayload | null>(null)

  useEffect(() => {
    function onDenied(event: Event) {
      const ce = event as CustomEvent<DeniedPayload>
      // Defensive: if the event was dispatched without a payload (e.g.
      // a test fires window.dispatchEvent(new Event('permission:denied'))),
      // we fall back to a generic message.
      const next: DeniedPayload = ce.detail ?? { attemptedPath: '' }
      setPayload(next)
    }
    window.addEventListener('permission:denied', onDenied)
    return () => window.removeEventListener('permission:denied', onDenied)
  }, [])

  // Auto-dismiss after TOAST_DURATION_MS. Reset the timer if a new
  // event fires while the toast is already showing.
  useEffect(() => {
    if (!payload) return
    const id = setTimeout(() => setPayload(null), TOAST_DURATION_MS)
    return () => clearTimeout(id)
  }, [payload])

  if (!payload) return null

  const pathLabel = payload.attemptedPath ? ` ${payload.attemptedPath}` : ''

  return (
    <div
      role="status"
      aria-live="assertive"
      className="fixed top-6 left-1/2 -translate-x-1/2 z-[90]
                 bg-[#FEE2E2] border border-[#EF4444] text-[#991B1B]
                 rounded-xl shadow-lg px-4 py-3 max-w-md w-[92%]
                 flex items-start gap-3 cursor-pointer
                 animate-[slideDown_0.2s_ease-out]"
      onClick={() => setPayload(null)}
    >
      <svg
        className="w-5 h-5 mt-0.5 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
      </svg>
      <div className="text-sm leading-tight">
        <p className="font-semibold">Access denied</p>
        <p className="opacity-90">
          You don&apos;t have permission to view{pathLabel}.
        </p>
      </div>
    </div>
  )
}
