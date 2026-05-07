/**
 * SessionExpiredModal — global session-expiry handler.
 *
 * Listens for the 'auth:session-expired' custom event dispatched by
 * api.ts when a 401 hits any non-login request. Shows a modal explaining
 * the situation, then on OK navigates to /login and restores lastPath
 * after re-auth.
 *
 * Mounted once at the App root so it overlays every route.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export function SessionExpiredModal() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    function onExpired() {
      // Don't show the modal if the user is already on /login (e.g. they
      // just got redirected and a stale request fires another 401)
      if (window.location.pathname === '/login') return
      // Save the page they were on so we can return them after re-auth.
      try {
        localStorage.setItem('lastPath', location.pathname + location.search)
      } catch { /* quota */ }
      setOpen(true)
    }
    window.addEventListener('auth:session-expired', onExpired)
    return () => window.removeEventListener('auth:session-expired', onExpired)
  }, [location])

  function handleConfirm() {
    setOpen(false)
    navigate('/login', { replace: true })
  }

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <div className="bg-white rounded-2xl shadow-xl border border-[#E2E8F0] max-w-sm w-[90%] p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-[#FEF3C7] flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-[#D97706]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
            </svg>
          </div>
          <h2 id="session-expired-title" className="text-base font-semibold text-[#1A202C]">
            Your session has expired
          </h2>
        </div>
        <p className="text-sm text-[#4A5568] leading-relaxed">
          For your security, we ended your session after a period of inactivity.
          Please sign in again to continue. We'll bring you back to where you were.
        </p>
        <button
          type="button"
          onClick={handleConfirm}
          autoFocus
          className="w-full bg-[#1E5A8D] hover:bg-[#174a78] text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
        >
          Sign in again
        </button>
      </div>
    </div>
  )
}
