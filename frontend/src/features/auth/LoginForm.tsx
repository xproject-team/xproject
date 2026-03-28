import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export function LoginForm() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!email || !password) {
      setError('Please enter your email and password.')
      return
    }
    setLoading(true)
    // Mock login — navigate to dashboard
    await new Promise((r) => setTimeout(r, 600))
    setLoading(false)
    navigate('/dashboard')
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5">
          Email address
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full border border-[#E2E8F0] rounded-lg px-4 py-2.5 text-sm text-[#1A202C] placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5">
          Password
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          className="w-full border border-[#E2E8F0] rounded-lg px-4 py-2.5 text-sm text-[#1A202C] placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition"
        />
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-[#6C63FF] hover:bg-[#5a52e0] disabled:opacity-60 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
      >
        {loading ? 'Signing in…' : 'Sign in'}
      </button>

      <p className="text-xs text-center text-[#4A5568]">
        Demo: enter any email + password
      </p>
    </form>
  )
}
