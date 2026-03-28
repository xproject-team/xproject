/**
 * AlertToast — single alert row with severity badge, message, and acknowledge button.
 */
interface AlertToastProps {
  severity: 'info' | 'warning' | 'critical'
  message: string
  onAcknowledge?: () => void
}

const severityStyles = {
  info: 'border-l-4 border-[#1E5A8D] bg-blue-50',
  warning: 'border-l-4 border-[#D69E2E] bg-yellow-50',
  critical: 'border-l-4 border-[#E53E3E] bg-red-50',
}

export function AlertToast({ severity, message, onAcknowledge }: AlertToastProps) {
  return (
    <div className={`p-3 rounded ${severityStyles[severity]} mb-2`}>
      <div className="flex items-center justify-between">
        <p className="text-sm text-[#1A202C]">{message}</p>
        {onAcknowledge && (
          <button
            onClick={onAcknowledge}
            className="text-xs text-[#4A5568] hover:text-[#1A202C] ml-2"
          >
            Ack
          </button>
        )}
      </div>
    </div>
  )
}
