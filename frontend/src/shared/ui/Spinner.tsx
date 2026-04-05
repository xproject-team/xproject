/**
 * Spinner — animated loading indicator for async data states.
 */
export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizeClasses = { sm: 'w-4 h-4', md: 'w-8 h-8', lg: 'w-12 h-12' }
  return (
    <div className={`${sizeClasses[size]} border-2 border-[#E2E8F0] border-t-[#1E5A8D] rounded-full animate-spin`} />
  )
}
