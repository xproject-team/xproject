/**
 * EmptyState — placeholder shown when a list or data set has no items.
 */
interface EmptyStateProps {
  message: string
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ message, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <p className="text-[#4A5568] mb-4">{message}</p>
      {action && (
        <button
          onClick={action.onClick}
          className="text-sm text-[#1E5A8D] font-medium hover:underline"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
