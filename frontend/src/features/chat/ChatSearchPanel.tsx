/**
 * Search panel overlay for chat. Appears when user types in the search bar.
 * Shows ranked results; click one jumps to that channel.
 */
import { highlightMatches, useChatSearch, type SearchResultItem } from './useChatSearch'


interface ChatSearchPanelProps {
  query:         string
  onResultClick: (channelId: string, messageId: string) => void
}


export function ChatSearchPanel({ query, onResultClick }: ChatSearchPanelProps) {
  const { data, isLoading, isError } = useChatSearch(query)
  const trimmed = query.trim()

  if (trimmed.length === 0) return null

  return (
    <div className="absolute top-full left-0 right-0 mt-1 max-h-[480px] overflow-y-auto bg-white border border-[#E2E8F0] rounded-xl shadow-lg z-50">
      {isLoading && (
        <div className="px-4 py-6 text-xs text-[#718096] text-center">
          Searching…
        </div>
      )}

      {isError && (
        <div className="px-4 py-6 text-xs text-[#E74C3C] text-center">
          ⚠ Search failed — try again
        </div>
      )}

      {!isLoading && !isError && data && data.length === 0 && (
        <div className="px-4 py-6 text-xs text-[#718096] text-center">
          No messages match &ldquo;<span className="font-semibold">{trimmed}</span>&rdquo;
        </div>
      )}

      {!isLoading && data && data.length > 0 && (
        <>
          <div className="px-4 py-2 text-[10px] uppercase tracking-wide text-[#A0AEC0] border-b border-[#EDF2F7]">
            {data.length} result{data.length === 1 ? '' : 's'}
          </div>
          <ul className="divide-y divide-[#EDF2F7]">
            {data.map((item) => (
              <SearchResultRow key={item.message_id} item={item} query={trimmed} onClick={() => onResultClick(item.channel_id, item.message_id)} />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}


function SearchResultRow({
  item,
  query,
  onClick,
}: {
  item: SearchResultItem
  query: string
  onClick: () => void
}) {
  const when = new Date(item.created_at).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left px-4 py-3 hover:bg-[#F7FAFC] transition-colors"
      >
        <div className="flex items-center gap-2 text-[11px] text-[#718096] mb-1">
          <span className="font-semibold text-[#1E5A8D]">#{item.channel_name}</span>
          <span>·</span>
          <span>{item.sender_name ?? '(deleted user)'}</span>
          <span>·</span>
          <span>{when}</span>
        </div>
        <p
          className="text-sm text-[#1A202C] line-clamp-2 [&>mark]:bg-yellow-200 [&>mark]:text-[#1A202C] [&>mark]:px-0.5 [&>mark]:rounded"
          dangerouslySetInnerHTML={{ __html: highlightMatches(item.body, query) }}
        />
      </button>
    </li>
  )
}
