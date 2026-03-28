/**
 * LoginForm — email/password form that calls the /api/v1/auth/login endpoint.
 * Uses React Hook Form + Zod for validation. On success, calls useAuth().login().
 */
export function LoginForm() {
  // TODO: implement with useForm, zodResolver, and useAuth
  return (
    <form className="bg-white p-8 rounded-lg shadow-md w-full max-w-sm">
      <h2 className="text-xl font-bold text-[#1A202C] mb-6">Sign in to XProject</h2>
      <div className="mb-4">
        <label className="block text-sm font-medium text-[#4A5568]">Email</label>
        <input type="email" className="mt-1 w-full border border-[#E2E8F0] rounded px-3 py-2" />
      </div>
      <div className="mb-6">
        <label className="block text-sm font-medium text-[#4A5568]">Password</label>
        <input type="password" className="mt-1 w-full border border-[#E2E8F0] rounded px-3 py-2" />
      </div>
      <button
        type="submit"
        className="w-full bg-[#1E5A8D] text-white py-2 rounded font-medium hover:bg-[#164d7a]"
      >
        Sign in
      </button>
    </form>
  )
}
