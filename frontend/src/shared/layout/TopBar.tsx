/**
 * TopBar — sticky top navigation bar with event selector and user menu.
 */
export function TopBar() {
  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center px-6 justify-between">
      <div className="text-sm text-[#4A5568]">
        {/* TODO: EventSelector dropdown */}
        Select event…
      </div>
      <div className="flex items-center gap-3">
        {/* TODO: NotificationBell, UserMenu */}
        <span className="text-sm text-[#4A5568]">User</span>
      </div>
    </header>
  )
}
