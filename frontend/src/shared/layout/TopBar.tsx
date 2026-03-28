import { useNavigate } from 'react-router-dom'

export function TopBar() {
  const navigate = useNavigate()

  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center px-6 justify-between flex-shrink-0 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-[#38A169] animate-pulse" title="Live" />
        <span className="text-sm font-semibold text-[#1A202C]">XProject</span>
        <span className="text-[#E2E8F0]">·</span>
        <span className="text-sm text-[#4A5568]">Sundance 2026</span>
        <span className="ml-2 bg-[#38A169]/10 text-[#38A169] text-xs font-medium px-2 py-0.5 rounded-full border border-[#38A169]/20">
          LIVE
        </span>
      </div>

      <div className="flex items-center gap-4">
        {/* Alert bell */}
        <button className="relative text-[#4A5568] hover:text-[#1A202C] transition-colors">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-[#E53E3E] text-white text-[10px] font-bold rounded-full flex items-center justify-center">
            3
          </span>
        </button>

        {/* Sign out */}
        <button
          onClick={() => navigate('/login')}
          className="text-xs text-[#4A5568] hover:text-[#1A202C] border border-[#E2E8F0] px-3 py-1.5 rounded-lg transition-colors"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
