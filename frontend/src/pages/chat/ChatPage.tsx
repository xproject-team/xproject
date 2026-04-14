/**
 * ChatPage — Slack-style 2-column chat UI.
 *
 *   ┌───────────────┬──────────────────────────────────────┐
 *   │   Channels    │   Messages (selected channel)        │
 *   │  - Cocktail   │   Omar: good morning team            │
 *   │  - Focacceria │   Manager: cocktails stocked 🍹      │
 *   │  - Malandrino │                                       │
 *   │               │   [ input box ────────────── Send ]  │
 *   └───────────────┴──────────────────────────────────────┘
 *
 * Real data from /api/v1/chat/*.  WebSocket live updates come in Phase B3.
 */
import { useEffect, useRef, useState } from 'react'
import {
  useChannels,
  useChannelMessages,
  useDeleteMessage,
  useEditMessage,
  useMarkChannelRead,
  usePostMessage,
  type ChannelResponse,
  type MessageResponse,
} from '@/features/chat/useChat'
import { useAuth } from '@/features/auth/useAuth'
import { useChatSocket } from '@/features/chat/useChatSocket'


/**
 * Render message body with @mentions highlighted as inline pills.
 * Self-mentions are brighter (yellow) — "this one is for you".
 */
function renderBody(body: string, currentUserName: string | null) {
  const MENTION_RE = /(?:^|(?<=\s))@([A-Za-z][A-Za-z0-9._-]{1,63})/g
  const parts: (string | { mention: string; isSelf: boolean })[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  const myFirstName = currentUserName?.trim().split(/\s+/)[0]?.toLowerCase() ?? ''
  const myFullNorm  = currentUserName?.trim().toLowerCase().replace(/\s+/g, '') ?? ''

  while ((match = MENTION_RE.exec(body)) !== null) {
    const start = match.index
    if (start > lastIndex) parts.push(body.slice(lastIndex, start))

    const token = match[1]
    const tokenNorm = token.toLowerCase().replace(/[._-]/g, '')
    const isSelf = !!myFirstName && (tokenNorm === myFirstName || tokenNorm === myFullNorm)

    parts.push({ mention: token, isSelf })
    lastIndex = start + match[0].length
  }
  if (lastIndex < body.length) parts.push(body.slice(lastIndex))

  if (parts.length === 0) return body
  return parts.map((part, i) => {
    if (typeof part === 'string') return <span key={i}>{part}</span>
    return (
      <span
        key={i}
        className={[
          'inline-block px-1.5 rounded font-semibold',
          part.isSelf ? 'bg-[#FEF3C7] text-[#92400E]' : 'bg-[#E2E8F0] text-[#1A202C]',
        ].join(' ')}
      >
        @{part.mention}
      </span>
    )
  })
}


export default function ChatPage() {
  const { user } = useAuth()
  const channels = useChannels()
  const [activeChannelId, setActiveChannelId] = useState<string | null>(null)

  // Auto-select first channel once loaded
  useEffect(() => {
    if (!activeChannelId && channels.data && channels.data.length > 0) {
      setActiveChannelId(channels.data[0].id)
    }
  }, [activeChannelId, channels.data])

  return (
    <div className="h-[calc(100vh-64px)] flex bg-white">
      {/* ─── Channel list ─────────────────────────────────────── */}
      <aside className="w-64 border-r border-[#E2E8F0] flex flex-col bg-[#F7FAFC]">
        <div className="px-4 py-3 border-b border-[#E2E8F0]">
          <h2 className="text-xs font-bold text-[#1A202C] uppercase tracking-wider">
            Channels
          </h2>
        </div>

        {channels.isLoading && (
          <div className="p-4 text-sm text-[#718096]">Loading channels…</div>
        )}
        {channels.isError && (
          <div className="p-4 text-sm text-[#E53E3E]">Couldn't load channels.</div>
        )}

        <div className="flex-1 overflow-y-auto">
          {channels.data?.map((ch) => (
            <ChannelRow
              key={ch.id}
              channel={ch}
              active={ch.id === activeChannelId}
              onClick={() => setActiveChannelId(ch.id)}
            />
          ))}
        </div>

        {user && (
          <div className="px-4 py-3 border-t border-[#E2E8F0] text-xs text-[#4A5568]">
            Signed in as <span className="font-semibold text-[#1A202C]">{user.full_name}</span>
          </div>
        )}
      </aside>

      {/* ─── Messages ────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0">
        {activeChannelId ? (
          <ChannelView
            channelId={activeChannelId}
            channelName={
              channels.data?.find((c) => c.id === activeChannelId)?.name ?? 'Chat'
            }
            currentUserId={user?.id ?? ''}
            currentUserName={user?.full_name ?? null}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-[#718096]">
            Select a channel to start messaging.
          </div>
        )}
      </main>
    </div>
  )
}


// ─── Channel row ──────────────────────────────────────────────────────

function ChannelRow({
  channel,
  active,
  onClick,
}: {
  channel: ChannelResponse
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'w-full text-left px-4 py-3 border-l-4 flex items-center justify-between gap-2 transition-colors',
        active
          ? 'border-[#1E5A8D] bg-white'
          : 'border-transparent hover:bg-white',
      ].join(' ')}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-[#1A202C] truncate">
          {channel.name}
        </p>
        <p className="text-[10px] text-[#718096] uppercase tracking-wide mt-0.5">
          {channel.channel_type}
        </p>
      </div>
      {channel.unread_count > 0 && (
        <span className="text-[11px] font-bold bg-[#1E5A8D] text-white rounded-full px-2 py-0.5 min-w-[1.25rem] text-center">
          {channel.unread_count}
        </span>
      )}
    </button>
  )
}


// ─── Channel view ─────────────────────────────────────────────────────

function ChannelView({
  channelId,
  channelName,
  currentUserId,
  currentUserName,
}: {
  channelId:       string
  channelName:     string
  currentUserId:   string
  currentUserName: string | null
}) {
  const messages = useChannelMessages(channelId)
  const postMsg  = usePostMessage(channelId)
  const editMsg  = useEditMessage(channelId)
  const deleteMsg = useDeleteMessage(channelId)
  const markRead = useMarkChannelRead(channelId)
  useChatSocket({ activeChannelId: channelId, currentUserId })
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  // On channel switch: mark as read
  useEffect(() => {
    markRead.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId])

  // Scroll to bottom when messages load/change
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages.data])

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    const body = draft.trim()
    if (!body) return
    setDraft('')
    try {
      await postMsg.mutateAsync(body)
    } catch {
      // If it fails, restore the draft so the user can retry
      setDraft(body)
    }
  }

  return (
    <>
      {/* Header */}
      <header className="px-6 py-3 border-b border-[#E2E8F0] bg-white">
        <h3 className="text-sm font-bold text-[#1A202C]">{channelName}</h3>
      </header>

      {/* Message list (newest at bottom — API returns newest first, we reverse) */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {messages.isLoading && (
          <p className="text-sm text-[#718096]">Loading messages…</p>
        )}
        {messages.isError && (
          <p className="text-sm text-[#E53E3E]">Couldn't load messages.</p>
        )}
        {messages.data && messages.data.length === 0 && (
          <p className="text-sm text-[#718096]">No messages yet. Say hi 👋</p>
        )}
        {messages.data
          ?.slice()
          .reverse()                                 // newest at bottom for natural chat flow
          .map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              isOwn={m.sender_id === currentUserId}
              currentUserName={currentUserName}
              onEdit={(newBody) => editMsg.mutate({ messageId: m.id, body: newBody })}
              onDelete={() => deleteMsg.mutate(m.id)}
              editing={editMsg.isPending}
              deleting={deleteMsg.isPending}
            />
          ))}
      </div>

      {/* Composer */}
      <form
        onSubmit={handleSend}
        className="border-t border-[#E2E8F0] px-6 py-3 flex items-center gap-3 bg-white"
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Message #${channelName}`}
          className="flex-1 border border-[#E2E8F0] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-[#1E5A8D] bg-[#F7FAFC]"
          disabled={postMsg.isPending}
        />
        <button
          type="submit"
          disabled={!draft.trim() || postMsg.isPending}
          className="bg-[#1E5A8D] hover:bg-[#174a78] disabled:opacity-50 text-white font-semibold px-5 py-2.5 rounded-xl text-sm shadow-sm transition-colors"
        >
          {postMsg.isPending ? 'Sending…' : 'Send'}
        </button>
      </form>
    </>
  )
}


// ─── Message bubble ───────────────────────────────────────────────────

interface MessageBubbleProps {
  message:         MessageResponse
  isOwn:           boolean
  currentUserName: string | null
  onEdit:          (newBody: string) => void
  onDelete:        () => void
  editing:         boolean
  deleting:        boolean
}

function MessageBubble({ message, isOwn, currentUserName, onEdit, onDelete, editing, deleting }: MessageBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.body)
  const [hovered, setHovered] = useState(false)

  function startEdit() {
    setDraft(message.body)
    setIsEditing(true)
  }

  function saveEdit() {
    const trimmed = draft.trim()
    if (!trimmed || trimmed === message.body) {
      setIsEditing(false)
      return
    }
    onEdit(trimmed)
    setIsEditing(false)
  }

  function cancelEdit() {
    setDraft(message.body)
    setIsEditing(false)
  }

  function handleDelete() {
    if (confirm('Delete this message?')) {
      onDelete()
    }
  }

  return (
    <div
      className={`flex ${isOwn ? 'justify-end' : 'justify-start'} group`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={`max-w-[70%] ${isOwn ? 'items-end' : 'items-start'} flex flex-col`}>
        {!isOwn && message.sender_name && (
          <span className="text-[11px] font-semibold text-[#4A5568] px-1 mb-1">
            {message.sender_name}
          </span>
        )}

        {/* Bubble (or edit textarea if editing) */}
        {isEditing ? (
          <div className="flex flex-col gap-1.5 w-full min-w-[240px]">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="border border-[#1E5A8D] rounded-xl px-3 py-2 text-sm focus:outline-none bg-white text-[#1A202C] min-h-[60px]"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Escape') cancelEdit()
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  saveEdit()
                }
              }}
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={cancelEdit}
                className="text-xs px-3 py-1 rounded-lg text-[#4A5568] hover:bg-[#F0F4F8]"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={editing}
                className="text-xs px-3 py-1 rounded-lg bg-[#1E5A8D] text-white hover:bg-[#174a78] disabled:opacity-60"
              >
                {editing ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            {/* Edit/delete icons (own messages only, on hover) */}
            {isOwn && hovered && !deleting && (
              <div className="flex gap-1">
                <button
                  onClick={startEdit}
                  title="Edit"
                  className="text-[#A0AEC0] hover:text-[#1E5A8D] p-1"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
                <button
                  onClick={handleDelete}
                  title="Delete"
                  className="text-[#A0AEC0] hover:text-[#E74C3C] p-1"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M10 7V4a1 1 0 011-1h2a1 1 0 011 1v3" />
                  </svg>
                </button>
              </div>
            )}
            <div
              className={[
                'px-4 py-2 rounded-2xl text-sm whitespace-pre-wrap break-words',
                isOwn
                  ? 'bg-[#1E5A8D] text-white rounded-br-md'
                  : 'bg-[#F0F4F8] text-[#1A202C] rounded-bl-md',
                deleting ? 'opacity-40' : '',
              ].join(' ')}
            >
              {renderBody(message.body, currentUserName)}
            </div>
          </div>
        )}

        <span className="text-[10px] text-[#A0AEC0] mt-1 px-1">
          {new Date(message.created_at).toLocaleTimeString([], {
            hour:   '2-digit',
            minute: '2-digit',
          })}
          {message.edited_at && <span className="ml-1 italic">(edited)</span>}
        </span>
      </div>
    </div>
  )
}
