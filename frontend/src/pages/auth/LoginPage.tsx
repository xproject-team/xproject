import { LoginForm } from '@/features/auth/LoginForm'

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col">
      {/* Navy header */}
      <header className="bg-primary py-4 px-8 shadow-md">
        <span className="text-white text-2xl font-bold tracking-tight">XProject</span>
      </header>

      {/* Centred card */}
      <main className="flex-1 flex items-center justify-center px-4">
        <div className="w-full max-w-md">
          <div className="bg-surface rounded-xl shadow-lg overflow-hidden">
            <div className="bg-primary px-8 py-6">
              <h1 className="text-white text-xl font-semibold">Sign in to XProject</h1>
              <p className="text-blue-200 text-sm mt-1">Sundance 2026 Operations Platform</p>
            </div>
            <div className="px-8 py-8">
              <LoginForm />
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
