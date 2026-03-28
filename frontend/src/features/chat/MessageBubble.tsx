/**
 * MessageBubble — renders a single chat message with role-based styling.
 * User messages align right; assistant messages align left with accent colour.
 */
interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
}

export function MessageBubble({ role, content }: MessageBubbleProps) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-2`}>
      <div
        className={`max-w-xs px-3 py-2 rounded-lg text-sm ${
          isUser
            ? 'bg-[#1E5A8D] text-white'
            : 'bg-[#F7FAFC] border border-[#E2E8F0] text-[#1A202C]'
        }`}
      >
        {content}
      </div>
    </div>
  )
}
