import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from './useAuth'
import { MOCK_USERS, getHomeRoute, type MockUser } from '@/lib/mockUsers'

const ROLE_COLORS: Record<MockUser['role'], string> = {
  owner:     'bg-[#E6FBF6] text-[#1ABC9C] border-[#1ABC9C]/30',
  manager:   'bg-[#EBF5FB] text-[#3498DB] border-[#3498DB]/30',
  warehouse: 'bg-[#FEF9E7] text-[#D69E2E] border-[#D69E2E]/30',
  bartender: 'bg-[#FDEDEC] text-[#E74C3C] border-[#E74C3C]/30',
}

const ROLE_LABELS: Record<MockUser['role'], string> = {
  owner:     'Owner',
  manager:   'Manager',
  warehouse: 'Warehouse Staff',
  bartender: 'Bartender',
}

export function LoginForm() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [selectedId, setSelectedId] = useState<number>(MOCK_USERS[0].id)
  const [loading, setLoading] = useState(false)

  const selectedUser = MOCK_USERS.find((u) => u.id === selectedId)!

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    await new Promise((r) => setTimeout(r, 400))
    login(selectedId)
    setLoading(false)
    navigate(getHomeRoute(selectedUser.role))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5">
          Login as
        </label>
        <div className="space-y-2">
          {MOCK_USERS.map((user) => {
            const selected = user.id === selectedId
            return (
              <label
                key={user.id}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl border-2 cursor-pointer transition-all ${
                  selected
                    ? 'border-[#1E5A8D] bg-blue-50'
                    : 'border-[#E2E8F0] hover:border-[#CBD5E0] bg-white'
                }`}
              >
                <input
                  type="radio"
                  name="user"
                  value={user.id}
                  checked={selected}
                  onChange={() => setSelectedId(user.id)}
                  className="sr-only"
                />
                {/* Avatar */}
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0"
                  style={{ backgroundColor: roleColor(user.role) }}
                >
                  {initials(user.name)}
                </div>
                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm text-[#1A202C]">{user.name}</span>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${ROLE_COLORS[user.role]}`}>
                      {ROLE_LABELS[user.role]}
                    </span>
                  </div>
                  <p className="text-xs text-[#4A5568] truncate">{user.email}</p>
                  {user.assignedBarName && (
                    <p className="text-[10px] text-[#4A5568] mt-0.5">
                      Assigned to: <span className="font-medium">{user.assignedBarName}</span>
                    </p>
                  )}
                </div>
                {/* Selection indicator */}
                <div className={`w-4 h-4 rounded-full border-2 shrink-0 flex items-center justify-center ${selected ? 'border-[#1E5A8D] bg-[#1E5A8D]' : 'border-[#CBD5E0]'}`}>
                  {selected && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                </div>
              </label>
            )
          })}
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-[#1E5A8D] hover:bg-[#174a78] disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors text-sm shadow-sm"
      >
        {loading ? 'Signing in…' : `Sign in as ${selectedUser.name}`}
      </button>

      <p className="text-xs text-center text-[#4A5568]">
        Development mode — select any user to continue
      </p>
    </form>
  )
}

function initials(name: string): string {
  return name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

function roleColor(role: MockUser['role']): string {
  const map: Record<MockUser['role'], string> = {
    owner:     '#1ABC9C',
    manager:   '#3498DB',
    warehouse: '#D69E2E',
    bartender: '#E74C3C',
  }
  return map[role]
}
