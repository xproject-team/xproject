/**
 * LoginPage — real email/password login.
 * Renders the XProject-branded card shell; delegates auth to LoginForm.
 *
 * Role-based landing (manager → /dashboard, owner → /dashboard, etc.)
 * happens INSIDE LoginForm after the JWT lands, because the role isn't
 * known until the backend responds.
 */
import { LoginForm } from '@/features/auth/LoginForm'

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-[#F7FAFC] flex flex-col">
      {/* Header */}
      <header className="bg-[#1E5A8D] py-4 px-8 shadow-md">
        <span className="text-white text-2xl font-bold tracking-tight">XProject</span>
      </header>

      {/* Centered card */}
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
              <LoginForm />
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
