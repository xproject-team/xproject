/**
 * Search panel overlay for chat. Appears when user types in the search bar.
 * Shows ranked results; click one jumps to that channel.
 *
 * Message bodies render as React TEXT via highlightSegments — never through
 * dangerouslySetInnerHTML (the old path was a stored XSS: a message body
 * containing markup executed in the searcher's browser).
 */
import { highlightSegments, useChatSearch, type SearchResultItem } from './useChatSearch'


interface ChatSearchPanelProps {
  query:         string
  onResultClick: (channelId: string, messageId: string) => void
}


export function ChatSearchPanel({ query, onResultClick }: ChatSearchPanelProps) {
  const { data, isLoading, isError } = useChatSearch(query)
  const trimmed = query.trim()

  if (trimmed.length === 0) return null

  return (
    <div
      className="absolute top-full left-0 right-0 mt-1 max-h-[480px] overflow-y-auto rounded-[var(--v-radius)] z-50 shadow-xl"
      style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
    >
      {isLoading && (
        <div className="px-4 py-6 text-xs text-center" style={{ color: 'var(--v-text-muted)' }}>
          Searching…
        </div>
      )}

      {isError && (
        <div className="px-4 py-6 text-xs text-center" style={{ color: 'var(--v-pink)' }}>
          Search failed — try again
        </div>
      )}

      {!isLoading && !isError && data && data.length === 0 && (
        <div className="px-4 py-6 text-xs text-center" style={{ color: 'var(--v-text-muted)' }}>
          No messages match “<span className="font-semibold" style={{ color: 'var(--v-text)' }}>{trimmed}</span>”
        </div>
      )}

      {!isLoading && data && data.length > 0 && (
        <>
          <div
            className="px-4 py-2 text-[10px] uppercase tracking-wide"
            style={{ color: 'var(--v-text-dim)', borderBottom: '0.5px solid var(--v-border)' }}
          >
            {data.length} result{data.length === 1 ? '' : 's'}
          </div>
          <ul>
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
    <li style={{ borderBottom: '0.5px solid var(--v-border)' }}>
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left px-4 py-3 transition-colors hover:bg-white/[0.04]"
      >
        <div className="flex items-center gap-2 text-[11px] mb-1" style={{ color: 'var(--v-text-muted)' }}>
          <span className="font-semibold" style={{ color: 'var(--v-cyan)' }}>#{item.channel_name}</span>
          <span>·</span>
          <span>{item.sender_name ?? '(deleted user)'}</span>
          <span>·</span>
          <span>{when}</span>
        </div>
        <p className="text-sm line-clamp-2" style={{ color: 'var(--v-text)' }}>
          {highlightSegments(item.body, query).map((seg, i) =>
            seg.match ? (
              <mark
                key={i}
                className="px-0.5 rounded"
                style={{ background: 'rgba(255, 216, 77, 0.35)', color: 'var(--v-text)' }}
              >
                {seg.text}
              </mark>
            ) : (
              <span key={i}>{seg.text}</span>
            ),
          )}
        </p>
      </button>
    </li>
  )
}
