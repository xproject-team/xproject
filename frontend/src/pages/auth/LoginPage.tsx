/**
 * LoginPage — role-selector login for development.
 * No personal names or emails; roles only.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/features/auth/useAuth'
import {
  MOCK_USERS,
  BARS,
  getHomeRoute,
  setPendingBar,
  type MockUser,
} from '@/lib/mockUsers'

// ─── Role icons ───────────────────────────────────────────────────────────────

function RoleIcon({ role }: { role: MockUser['role'] }) {
  const cls = 'w-6 h-6 text-white'

  if (role === 'owner')
    return (
      <svg className={cls} viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2l2.582 7.953H22.5l-6.79 4.932 2.582 7.953L12 18.205l-6.291 4.633 2.582-7.953L2.5 9.953h7.918z" />
      </svg>
    )

  if (role === 'manager')
    return (
      <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )

  if (role === 'warehouse')
    return (
      <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
      </svg>
    )

  // bartender
  return (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
    </svg>
  )
}

// ─── Role card ────────────────────────────────────────────────────────────────

function RoleCard({
  user,
  selected,
  onClick,
}: {
  user: MockUser
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex flex-col items-center gap-3 p-5 rounded-xl border-2 transition-all',
        selected
          ? 'border-[#1E5A8D] bg-blue-50 shadow-sm'
          : 'border-[#E2E8F0] hover:border-[#CBD5E0] bg-white',
      ].join(' ')}
    >
      {/* Colored circle */}
      <div
        className="w-12 h-12 rounded-full flex items-center justify-center shadow-sm"
        style={{ backgroundColor: user.color }}
      >
        <RoleIcon role={user.role} />
      </div>

      {/* Label */}
      <span
        className={`text-sm font-semibold leading-tight text-center ${
          selected ? 'text-[#1E5A8D]' : 'text-[#1A202C]'
        }`}
      >
        {user.name}
      </span>
    </button>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()

  const [selectedId, setSelectedId] = useState<string>('usr-1')
  const [selectedBarId, setSelectedBarId] = useState<string>('')
  const [barError, setBarError] = useState(false)
  const [loading, setLoading] = useState(false)

  const selectedUser = MOCK_USERS.find((u) => u.id === selectedId)!
  const needsBar = selectedUser.role === 'manager' || selectedUser.role === 'bartender'

  function handleRoleSelect(id: string) {
    setSelectedId(id)
    setSelectedBarId('')
    setBarError(false)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    if (needsBar && !selectedBarId) {
      setBarError(true)
      return
    }

    setBarError(false)
    setLoading(true)
    await new Promise((r) => setTimeout(r, 350))

    if (needsBar && selectedBarId) {
      const bar = BARS.find((b) => b.id === selectedBarId)
      if (bar) setPendingBar(bar.id, bar.name)
    }

    login(selectedId)
    navigate(getHomeRoute(selectedUser.role))
  }

  return (
    <div className="min-h-screen bg-[#F7FAFC] flex flex-col">
      {/* Header */}
      <header className="bg-[#1E5A8D] py-4 px-8 shadow-md">
        <span className="text-white text-2xl font-bold tracking-tight">XProject</span>
      </header>

      {/* Centred card */}
      <main className="flex-1 flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-xl shadow-lg overflow-hidden">
            {/* Card header */}
            <div className="bg-[#1E5A8D] px-8 py-6">
              <h1 className="text-white text-xl font-semibold">Sign in to XProject</h1>
              <p className="text-blue-200 text-sm mt-1">Sundance 2026 · Operations Platform</p>
            </div>

            {/* Form */}
            <div className="px-8 py-8">
              <form onSubmit={handleSubmit} className="space-y-6">

                {/* Role selector */}
                <div>
                  <p className="text-sm font-medium text-[#4A5568] mb-3">Select your role</p>
                  <div className="grid grid-cols-2 gap-3">
                    {MOCK_USERS.map((user) => (
                      <RoleCard
                        key={user.id}
                        user={user}
                        selected={selectedId === user.id}
                        onClick={() => handleRoleSelect(user.id)}
                      />
                    ))}
                  </div>
                </div>

                {/* Bar assignment — manager and bartender only */}
                {needsBar && (
                  <div>
                    <label className="block text-sm font-medium text-[#4A5568] mb-1.5">
                      Bar assignment
                      <span className="text-[#E53E3E] ml-1">*</span>
                    </label>
                    <select
                      value={selectedBarId}
                      onChange={(e) => {
                        setSelectedBarId(e.target.value)
                        setBarError(false)
                      }}
                      className={[
                        'w-full border rounded-lg px-4 py-2.5 text-sm bg-white text-[#1A202C]',
                        'focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition',
                        barError ? 'border-[#E53E3E]' : 'border-[#E2E8F0]',
                      ].join(' ')}
                    >
                      <option value="">Select your bar…</option>
                      {BARS.map((bar) => (
                        <option key={bar.id} value={bar.id}>
                          {bar.name}
                        </option>
                      ))}
                    </select>
                    {barError && (
                      <p className="text-xs text-[#E53E3E] mt-1.5">
                        Please select your bar before signing in.
                      </p>
                    )}
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full text-white font-semibold py-3 rounded-xl transition-all text-sm shadow-sm disabled:opacity-60 hover:brightness-90"
                  style={{ backgroundColor: selectedUser.color }}
                >
                  {loading ? 'Signing in…' : `Sign in as ${selectedUser.name}`}
                </button>

                <p className="text-xs text-center text-[#4A5568]">
                  Development mode · No password required
                </p>
              </form>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
