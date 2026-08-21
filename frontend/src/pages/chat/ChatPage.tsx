/**
 * ChatPage — design-system conversion + two-role redesign (Stage 3).
 *
 * Layout: PageHeader over a two-panel body (channel sidebar + messages),
 * centred like the other pages but wider — chat earns the extra width.
 *
 * Sidebar grouping (Part A design):
 *   - CURRENT EVENT: bar channels of the LIVE event, else the next ACTIVE
 *     event by scheduled date
 *   - UPCOMING: other non-archived events' channels, grouped per event
 *   - CONVERSATIONS: event-less channels (DMs, strategic, general)
 *   - PAST EVENTS: archived (completed/cancelled) events' channels,
 *     collapsed by default — read-only history, enforced by the backend
 *     (POST/PATCH/DELETE → 409) and reflected here (no composer).
 *
 * Two-role reality:
 *   - authorless messages (deleted sender) label as "(deleted user)"
 *   - the channel header shows the real derived members (Owner + Managers);
 *     a bar channel with no manager yet says so plainly
 *   - the @mention picker offers only those real members
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useChannels,
  useChannelMessages,
  useChannelMembers,
  useDeleteMessage,
  useEditMessage,
  useMarkChannelRead,
  usePostMessage,
  type ChannelMemberInfo,
  type ChannelResponse,
  type MessageResponse,
} from '@/features/chat/useChat'
import { useAuth } from '@/features/auth/useAuth'
import { useChatSocket } from '@/features/chat/useChatSocket'
import { AttachmentPicker } from '@/features/chat/AttachmentPicker'
import { ChatSearchPanel } from '@/features/chat/ChatSearchPanel'
import { useAttachmentUpload } from '@/features/chat/useAttachments'
import { Badge, Button, EmptyState, PageHeader } from '@/design-system/components'
import { inputCls } from '@/design-system/wizardForm'
import '@/design-system/components/components.css'


/**
 * Render message body with @mentions highlighted as inline pills.
 * Self-mentions are brighter — "this one is for you". Plain React nodes,
 * never raw HTML.
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
        className="inline-block px-1.5 rounded font-semibold"
        style={
          part.isSelf
            ? { background: 'rgba(255, 216, 77, 0.25)', color: 'var(--v-amber)' }
            : { background: 'rgba(255, 255, 255, 0.10)', color: 'var(--v-text)' }
        }
      >
        @{part.mention}
      </span>
    )
  })
}

// ─── Event grouping for the sidebar ───────────────────────────────────

interface EventGroup {
  eventId:     string
  eventName:   string
  eventStatus: string | null
  scheduledAt: string | null
  channels:    ChannelResponse[]
}

interface GroupedChannels {
  current:       EventGroup | null
  upcoming:      EventGroup[]
  conversations: ChannelResponse[]
  past:          EventGroup[]
}

function groupChannels(channels: ChannelResponse[]): GroupedChannels {
  const conversations = channels.filter((c) => c.event_id === null)
  const byEvent = new Map<string, EventGroup>()
  for (const c of channels) {
    if (!c.event_id) continue
    const g = byEvent.get(c.event_id) ?? {
      eventId:     c.event_id,
      eventName:   c.event_name ?? 'Unknown event',
      eventStatus: c.event_status,
      scheduledAt: c.event_scheduled_at,
      channels:    [],
    }
    g.channels.push(c)
    byEvent.set(c.event_id, g)
  }

  const groups = [...byEvent.values()]
  const past = groups
    .filter((g) => g.eventStatus === 'completed' || g.eventStatus === 'cancelled')
    .sort((a, b) => (b.scheduledAt ?? '').localeCompare(a.scheduledAt ?? ''))
  const active = groups.filter((g) => !past.includes(g))

  // Current = the LIVE event, else the next ACTIVE by scheduled date,
  // else the earliest remaining (draft) event
  const bySchedule = (a: EventGroup, b: EventGroup) =>
    (a.scheduledAt ?? '9999').localeCompare(b.scheduledAt ?? '9999')
  const current =
    active.find((g) => g.eventStatus === 'live') ??
    active.filter((g) => g.eventStatus === 'active').sort(bySchedule)[0] ??
    active.sort(bySchedule)[0] ??
    null
  const upcoming = active.filter((g) => g !== current).sort(bySchedule)

  return { current, upcoming, conversations, past }
}

// ─── Page ─────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { user } = useAuth()
  const channels = useChannels()
  const [searchQuery, setSearchQuery] = useState('')
  const [highlightedMessageId, setHighlightedMessageId] = useState<string | null>(null)
  const [activeChannelId, setActiveChannelId] = useState<string | null>(null)
  const [showPast, setShowPast] = useState(false)

  const grouped = useMemo(() => groupChannels(channels.data ?? []), [channels.data])

  // Auto-select the first CURRENT-event channel once loaded (not an archive)
  useEffect(() => {
    if (!activeChannelId && channels.data && channels.data.length > 0) {
      const first =
        grouped.current?.channels[0] ?? grouped.conversations[0] ?? channels.data[0]
      setActiveChannelId(first.id)
    }
  }, [activeChannelId, channels.data, grouped])

  const activeChannel = channels.data?.find((c) => c.id === activeChannelId) ?? null

  return (
    <div className="h-[calc(100vh-64px)] flex flex-col px-6 py-5 max-w-[1400px] mx-auto w-full">
      <div className="mb-4 shrink-0">
        <PageHeader
          title="Chat"
          subtitle={
            grouped.current
              ? `${grouped.current.eventName}${grouped.current.eventStatus === 'live' ? ' · Live' : ''}`
              : 'No current event'
          }
        />
      </div>

      <div className="flex-1 min-h-0 flex gap-4">
        {/* ─── Channel sidebar ─────────────────────────────────── */}
        <aside
          className="w-72 shrink-0 flex flex-col rounded-[var(--v-radius-lg)] overflow-hidden"
          style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)' }}
        >
          <div className="px-4 py-3 relative shrink-0" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search messages…"
              className={inputCls}
            />
            <ChatSearchPanel
              query={searchQuery}
              onResultClick={(channelId, messageId) => {
                setActiveChannelId(channelId)
                setHighlightedMessageId(messageId)
                setSearchQuery('')
              }}
            />
          </div>

          <div className="flex-1 overflow-y-auto py-2">
            {channels.isLoading && (
              <p className="px-4 py-3 text-sm" style={{ color: 'var(--v-text-muted)' }}>Loading channels…</p>
            )}
            {channels.isError && (
              <p className="px-4 py-3 text-sm" style={{ color: 'var(--v-pink)' }}>Couldn't load channels.</p>
            )}

            {channels.data && channels.data.length === 0 && (
              <div className="px-3 py-4">
                <EmptyState
                  headline="No channels yet"
                  body="Each event's bars create their team channels automatically — set up an event to start chatting."
                />
              </div>
            )}

            {/* Current event */}
            {grouped.current && (
              <SidebarSection
                label={grouped.current.eventName}
                badge={grouped.current.eventStatus === 'live' ? 'LIVE' : undefined}
              >
                {grouped.current.channels.map((ch) => (
                  <ChannelRow key={ch.id} channel={ch} active={ch.id === activeChannelId} onClick={() => setActiveChannelId(ch.id)} />
                ))}
              </SidebarSection>
            )}

            {/* Other upcoming events */}
            {grouped.upcoming.map((g) => (
              <SidebarSection key={g.eventId} label={g.eventName}>
                {g.channels.map((ch) => (
                  <ChannelRow key={ch.id} channel={ch} active={ch.id === activeChannelId} onClick={() => setActiveChannelId(ch.id)} />
                ))}
              </SidebarSection>
            ))}

            {/* Event-less conversations: DMs, strategic, general */}
            {grouped.conversations.length > 0 && (
              <SidebarSection label="Conversations">
                {grouped.conversations.map((ch) => (
                  <ChannelRow key={ch.id} channel={ch} active={ch.id === activeChannelId} onClick={() => setActiveChannelId(ch.id)} />
                ))}
              </SidebarSection>
            )}

            {/* Past events — collapsed archive */}
            {grouped.past.length > 0 && (
              <div className="mt-2 px-2">
                <button
                  type="button"
                  onClick={() => setShowPast((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-2 text-[11px] font-medium uppercase tracking-wide rounded-[var(--v-radius-sm)] hover:bg-white/[0.04]"
                  style={{ color: 'var(--v-text-dim)' }}
                  aria-expanded={showPast}
                >
                  <span>{showPast ? '▾' : '▸'}</span>
                  Past events
                  <span className="ml-auto">{grouped.past.reduce((n, g) => n + g.channels.length, 0)}</span>
                </button>
                {showPast &&
                  grouped.past.map((g) => (
                    <SidebarSection key={g.eventId} label={g.eventName} dim>
                      {g.channels.map((ch) => (
                        <ChannelRow key={ch.id} channel={ch} active={ch.id === activeChannelId} onClick={() => setActiveChannelId(ch.id)} />
                      ))}
                    </SidebarSection>
                  ))}
              </div>
            )}
          </div>

          {user && (
            <div className="px-4 py-3 text-xs shrink-0" style={{ borderTop: '0.5px solid var(--v-border)', color: 'var(--v-text-muted)' }}>
              Signed in as <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{user.full_name}</span>
            </div>
          )}
        </aside>

        {/* ─── Messages panel ──────────────────────────────────── */}
        <main
          className="flex-1 min-w-0 flex flex-col rounded-[var(--v-radius-lg)] overflow-hidden"
          style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)' }}
        >
          {activeChannel ? (
            <ChannelView
              channel={activeChannel}
              currentUserId={user?.id ?? ''}
              currentUserName={user?.full_name ?? null}
              allChannelIds={channels.data?.map((c) => c.id) ?? []}
              highlightedMessageId={highlightedMessageId}
              onHighlightConsumed={() => setHighlightedMessageId(null)}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center p-8">
              <EmptyState
                headline="Select a channel"
                body="Pick a channel from the list to read and send messages."
              />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

// ─── Sidebar building blocks ──────────────────────────────────────────

function SidebarSection({
  label,
  badge,
  dim,
  children,
}: {
  label: string
  badge?: string
  dim?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="mb-1">
      <div className="px-4 pt-3 pb-1 flex items-center gap-2">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider truncate"
          style={{ color: dim ? 'var(--v-text-dim)' : 'var(--v-text-muted)' }}
        >
          {label}
        </span>
        {badge && (
          <span
            className="text-[9px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
            style={{ background: 'rgba(56, 161, 105, 0.15)', color: '#38A169', border: '0.5px solid rgba(56,161,105,0.3)' }}
          >
            {badge}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

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
        'w-full text-left px-4 py-2 border-l-2 flex items-center justify-between gap-2 transition-colors',
        active ? 'border-l-[var(--v-cyan)]' : 'border-l-transparent hover:bg-white/[0.04]',
      ].join(' ')}
      style={active ? { background: 'rgba(0, 229, 212, 0.10)' } : undefined}
    >
      <div className="min-w-0 flex-1 flex items-center gap-1.5">
        <p
          className="text-sm truncate"
          style={{ color: active ? 'var(--v-cyan)' : channel.is_archived ? 'var(--v-text-muted)' : 'var(--v-text)' }}
        >
          {channel.name}
        </p>
        {channel.is_archived && <Badge variant="dim">Archived</Badge>}
      </div>
      {channel.unread_count > 0 && (
        <span
          className="text-[11px] font-bold rounded-full px-2 py-0.5 min-w-[1.25rem] text-center shrink-0"
          style={{ background: 'var(--v-cyan)', color: '#06251f' }}
        >
          {channel.unread_count}
        </span>
      )}
    </button>
  )
}

// ─── Channel view ─────────────────────────────────────────────────────

function ChannelView({
  channel,
  currentUserId,
  currentUserName,
  allChannelIds,
  highlightedMessageId,
  onHighlightConsumed,
}: {
  channel:              ChannelResponse
  currentUserId:        string
  currentUserName:      string | null
  allChannelIds:        string[]
  highlightedMessageId: string | null
  onHighlightConsumed:  () => void
}) {
  const channelId = channel.id
  const messages = useChannelMessages(channelId)
  const members  = useChannelMembers(channelId)
  const postMsg  = usePostMessage(channelId)
  const editMsg  = useEditMessage(channelId)
  const deleteMsg = useDeleteMessage(channelId)
  const markRead = useMarkChannelRead(channelId)
  useChatSocket({ activeChannelId: channelId, currentUserId, allChannelIds })
  const attachments = useAttachmentUpload(channelId)
  const [draft, setDraft] = useState('')
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLInputElement>(null)

  const isArchived = channel.is_archived
  const memberList = members.data ?? []
  const managerCount = memberList.filter((m) => m.role === 'manager').length
  const isBarChannel = channel.channel_type === 'bar' || channel.channel_type === 'general'

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

  // ── @mention picker: track a trailing "@token" in the draft ─────────
  const mentionMatch = /(?:^|\s)@([A-Za-z0-9._-]*)$/.exec(draft)
  const mentionQuery = mentionMatch?.[1]?.toLowerCase() ?? null
  const mentionCandidates =
    mentionQuery !== null
      ? memberList.filter(
          (m) =>
            m.id !== currentUserId &&
            m.full_name.toLowerCase().replace(/\s+/g, '').startsWith(mentionQuery.replace(/[._-]/g, '')),
        )
      : []

  function insertMention(m: ChannelMemberInfo) {
    const token = '@' + m.full_name.trim().replace(/\s+/g, '_') + ' '
    setDraft((d) => d.replace(/(^|\s)@[A-Za-z0-9._-]*$/, (_, pre) => pre + token))
    composerRef.current?.focus()
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    const body = draft.trim()
    const att_ids = attachments.pending.map((a) => a.id)
    if (!body && att_ids.length === 0) return
    setDraft('')
    try {
      await postMsg.mutateAsync({ body: body || '(file)', attachment_ids: att_ids })
      attachments.clear()
    } catch {
      // If it fails, restore the draft so the user can retry
      setDraft(body)
    }
  }

  return (
    <>
      {/* Header */}
      <header className="px-5 py-3 shrink-0" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
        <div className="flex items-center gap-2.5 flex-wrap">
          <h3 className="text-sm font-semibold" style={{ color: 'var(--v-text)' }}>{channel.name}</h3>
          {channel.event_name && (
            <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>{channel.event_name}</span>
          )}
          {channel.event_status === 'live' && <Badge variant="success">Live</Badge>}
          {isArchived && <Badge variant="dim">Archived · read-only</Badge>}
          <div className="ml-auto flex items-center gap-1.5 flex-wrap">
            {memberList.map((m) => (
              <span key={m.id} className="flex items-center gap-1 text-xs" style={{ color: 'var(--v-text-muted)' }}>
                {m.full_name}
                <Badge variant={m.role === 'owner' ? 'info' : 'violet'}>{m.role}</Badge>
              </span>
            ))}
          </div>
        </div>
        {isBarChannel && !members.isLoading && managerCount === 0 && (
          <p className="text-xs mt-1.5" style={{ color: 'var(--v-text-dim)' }}>
            No manager yet — manager accounts join this channel automatically when they're created.
          </p>
        )}
      </header>

      {/* Message list (newest at bottom — API returns newest first, we reverse) */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {messages.isLoading && (
          <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>Loading messages…</p>
        )}
        {messages.isError && (
          <p className="text-sm" style={{ color: 'var(--v-pink)' }}>Couldn't load messages.</p>
        )}
        {messages.data && messages.data.length === 0 && (
          <div className="pt-8">
            <EmptyState
              headline={isArchived ? 'Nothing was posted here' : 'No messages yet'}
              body={
                isArchived
                  ? 'This channel ended its event without any messages.'
                  : 'Start the conversation — messages reach every member instantly.'
              }
            />
          </div>
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
              readOnly={isArchived}
              onEdit={(newBody) => editMsg.mutate({ messageId: m.id, body: newBody })}
              onDelete={() => setPendingDelete(m.id)}
              editing={editMsg.isPending}
              deleting={deleteMsg.isPending}
              highlighted={m.id === highlightedMessageId}
              onHighlightConsumed={onHighlightConsumed}
            />
          ))}
      </div>

      {/* Composer — or the archive notice */}
      {isArchived ? (
        <div
          className="px-5 py-3.5 text-sm shrink-0 text-center"
          style={{ borderTop: '0.5px solid var(--v-border)', color: 'var(--v-text-muted)' }}
        >
          This event has ended — its chat is archived and read-only.
        </div>
      ) : (
        <div className="relative shrink-0" style={{ borderTop: '0.5px solid var(--v-border)' }}>
          {/* Mention picker */}
          {mentionCandidates.length > 0 && (
            <div
              className="absolute bottom-full left-5 mb-1 w-72 rounded-[var(--v-radius)] overflow-hidden shadow-xl z-10"
              style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
            >
              {mentionCandidates.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => insertMention(m)}
                  className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-white/[0.06]"
                >
                  <span className="text-sm" style={{ color: 'var(--v-text)' }}>{m.full_name}</span>
                  <Badge variant={m.role === 'owner' ? 'info' : 'violet'}>{m.role}</Badge>
                </button>
              ))}
            </div>
          )}
          <form onSubmit={handleSend} className="px-5 py-3 flex items-center gap-3">
            <AttachmentPicker
              channelId={channelId}
              pending={attachments.pending}
              uploading={attachments.uploading}
              error={attachments.error}
              onPick={attachments.upload}
              onRemove={attachments.remove}
            />
            <input
              ref={composerRef}
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={`Message ${channel.name} — @ to mention`}
              className={inputCls + ' flex-1'}
              disabled={postMsg.isPending}
            />
            <Button
              variant="primary"
              disabled={(!draft.trim() && attachments.pending.length === 0) || postMsg.isPending}
            >
              {postMsg.isPending ? 'Sending…' : 'Send'}
            </Button>
          </form>
        </div>
      )}

      {/* Delete confirmation — established modal treatment */}
      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div
            className="rounded-2xl max-w-sm w-[90%] mx-4 p-6"
            style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
          >
            <h3 className="text-lg font-medium mb-1" style={{ color: 'var(--v-text)' }}>Delete message</h3>
            <p className="text-sm mb-5" style={{ color: 'var(--v-text-muted)' }}>
              This removes the message for everyone. There is no undo.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setPendingDelete(null)}>Cancel</Button>
              <button
                type="button"
                onClick={() => {
                  deleteMsg.mutate(pendingDelete)
                  setPendingDelete(null)
                }}
                className="text-sm font-medium px-4 py-2 rounded-[var(--v-radius-sm)] transition-colors"
                style={{ background: 'rgba(255, 61, 113, 0.15)', color: 'var(--v-pink)', border: '0.5px solid var(--v-pink)' }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Message bubble ───────────────────────────────────────────────────

interface MessageBubbleProps {
  message:              MessageResponse
  isOwn:                boolean
  currentUserName:      string | null
  readOnly:             boolean
  onEdit:               (newBody: string) => void
  onDelete:             () => void
  editing:              boolean
  deleting:             boolean
  highlighted:          boolean
  onHighlightConsumed:  () => void
}

function MessageBubble({ message, isOwn, currentUserName, readOnly, onEdit, onDelete, editing, deleting, highlighted, onHighlightConsumed }: MessageBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.body)
  const [hovered, setHovered] = useState(false)

  // Highlight flash when this bubble is the search target
  const bubbleRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!highlighted) return
    // Scroll into view centered
    bubbleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Clear highlight after 3s so a future search can re-target
    const t = setTimeout(onHighlightConsumed, 3000)
    return () => clearTimeout(t)
  }, [highlighted, onHighlightConsumed])

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

  return (
    <div
      className={`flex ${isOwn ? 'justify-end' : 'justify-start'} group`}
      ref={bubbleRef}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={`max-w-[70%] ${isOwn ? 'items-end' : 'items-start'} flex flex-col`}>
        {!isOwn && (
          <span
            className="text-[11px] font-semibold px-1 mb-1"
            style={{ color: message.sender_name ? 'var(--v-text-muted)' : 'var(--v-text-dim)' }}
          >
            {message.sender_name ?? '(deleted user)'}
          </span>
        )}

        {/* Bubble (or edit textarea if editing) */}
        {isEditing ? (
          <div className="flex flex-col gap-1.5 w-full min-w-[240px]">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className={inputCls + ' min-h-[60px]'}
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
              <Button variant="secondary" onClick={cancelEdit}>Cancel</Button>
              <Button variant="primary" onClick={saveEdit} disabled={editing}>
                {editing ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            {/* Edit/delete icons (own messages only, on hover, never in archives) */}
            {isOwn && !readOnly && hovered && !deleting && (
              <div className="flex gap-1">
                <button
                  onClick={startEdit}
                  title="Edit"
                  className="p-1 transition-colors"
                  style={{ color: 'var(--v-text-dim)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-cyan)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-dim)')}
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
                <button
                  onClick={onDelete}
                  title="Delete"
                  className="p-1 transition-colors"
                  style={{ color: 'var(--v-text-dim)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-pink)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-dim)')}
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M10 7V4a1 1 0 011-1h2a1 1 0 011 1v3" />
                  </svg>
                </button>
              </div>
            )}
            <div
              className={[
                highlighted ? 'ring-2 ring-[var(--v-amber)] shadow-lg transition-shadow' : '',
                'px-4 py-2 rounded-2xl text-sm whitespace-pre-wrap break-words',
                isOwn ? 'rounded-br-md' : 'rounded-bl-md',
                deleting ? 'opacity-40' : '',
              ].join(' ')}
              style={
                isOwn
                  ? { background: 'rgba(0, 229, 212, 0.14)', border: '0.5px solid rgba(0, 229, 212, 0.3)', color: 'var(--v-text)' }
                  : { background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }
              }
            >
              {renderBody(message.body, currentUserName)}
              {message.attachments && message.attachments.length > 0 && (
                <div className="mt-2 flex flex-col gap-1.5">
                  {message.attachments.map((att) => (
                    <a
                      key={att.id}
                      href={att.download_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      download={att.original_filename}
                      className="flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs transition-colors no-underline hover:bg-white/[0.06]"
                      style={{ background: 'rgba(255,255,255,0.04)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}
                    >
                      {att.content_type.startsWith('image/') ? (
                        <img
                          src={att.download_url}
                          alt={att.original_filename}
                          className="max-w-[200px] max-h-[200px] rounded"
                        />
                      ) : (
                        <>
                          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <span className="font-medium truncate max-w-[200px]">{att.original_filename}</span>
                          <span style={{ color: 'var(--v-text-dim)' }}>
                            {att.size_bytes < 1024
                              ? `${att.size_bytes} B`
                              : att.size_bytes < 1024 * 1024
                              ? `${(att.size_bytes / 1024).toFixed(1)} KB`
                              : `${(att.size_bytes / (1024 * 1024)).toFixed(1)} MB`}
                          </span>
                        </>
                      )}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <span className="text-[10px] mt-1 px-1" style={{ color: 'var(--v-text-dim)' }}>
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
