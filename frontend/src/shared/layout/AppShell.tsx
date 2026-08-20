/**
 * AppShell — top-level layout wrapper: Sidebar + TopBar + main content area.
 * All authenticated pages are wrapped in this component.
 */
import { type ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { AmbientBackground } from '@/design-system/components/AmbientBackground'
import '@/design-system/tokens.css'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="vera-dark flex h-screen relative">
      <AmbientBackground />
      <Sidebar />
      {/* relative z-10 lifts this column above the fixed, z-0 AmbientBackground —
          without it, browsers paint positioned z-0 siblings over static content. */}
      <div className="flex-1 flex flex-col overflow-hidden relative z-10">
        <TopBar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
