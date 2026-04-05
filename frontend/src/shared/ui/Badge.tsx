/**
 * Badge — small status indicator pill. Used for alert severity and event status.
 */
interface BadgeProps {
  label: string
  color?: 'primary' | 'success' | 'warning' | 'danger' | 'neutral'
}

const colorClasses = {
  primary: 'bg-blue-100 text-[#1E5A8D]',
  success: 'bg-green-100 text-[#38A169]',
  warning: 'bg-yellow-100 text-[#D69E2E]',
  danger: 'bg-red-100 text-[#E53E3E]',
  neutral: 'bg-[#F7FAFC] text-[#4A5568] border border-[#E2E8F0]',
}

export function Badge({ label, color = 'neutral' }: BadgeProps) {
  return (
    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${colorClasses[color]}`}>
      {label}
    </span>
  )
}
