/**
 * LoginPage — thin route component.
 * Composes the LoginForm feature component inside a centered layout.
 */
import { LoginForm } from '@/features/auth/LoginForm'

export default function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7FAFC]">
      <LoginForm />
    </div>
  )
}
