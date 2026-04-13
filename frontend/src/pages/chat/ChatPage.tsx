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
  useMarkChannelRead,
  usePostMessage,
  type ChannelResponse,
  type MessageResponse,
} from '@/features/chat/useChat'
import { useAuth } from '@/features/auth/useAuth'


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
}: {
  channelId:     string
  channelName:   string
  currentUserId: string
}) {
  const messages = useChannelMessages(channelId)
  const postMsg  = usePostMessage(channelId)
  const markRead = useMarkChannelRead(channelId)
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

function MessageBubble({ message, isOwn }: { message: MessageResponse; isOwn: boolean }) {
  return (
    <div className={`flex ${isOwn ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[70%] ${isOwn ? 'items-end' : 'items-start'} flex flex-col`}>
        {!isOwn && message.sender_name && (
          <span className="text-[11px] font-semibold text-[#4A5568] px-1 mb-1">
            {message.sender_name}
          </span>
        )}
        <div
          className={[
            'px-4 py-2 rounded-2xl text-sm whitespace-pre-wrap break-words',
            isOwn
              ? 'bg-[#1E5A8D] text-white rounded-br-md'
              : 'bg-[#F0F4F8] text-[#1A202C] rounded-bl-md',
          ].join(' ')}
        >
          {message.body}
        </div>
        <span className="text-[10px] text-[#A0AEC0] mt-1 px-1">
          {new Date(message.created_at).toLocaleTimeString([], {
            hour:   '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </div>
  )
}
