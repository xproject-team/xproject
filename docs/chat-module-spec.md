# Chat Module — Design Specification

**Status:** Draft, awaiting build
**Author:** Hesam + Claude, captured April 17 2026
**Target ship:** v1.0 (before Sundance June 2026) — pending prioritization against remaining MVP work

---

## 1. Product framing

### What Chat is

A bidirectional, real-time messaging module that lets the Owner (Omar) and the on-the-ground Manager/Bartender at each bar communicate without leaving the XProject app. Every bar at an active event has its own persistent channel. Messages in that channel are visible in two UI locations which stay in sync:

1. The **Chat tab in the BarDetailOverlay** — context-rich, shows the last N messages when Omar drills into a specific bar from the Dashboard.
2. The **Sidebar Chat page** — the dedicated chat inbox, showing all channels the user has access to, with unread indicators.

Both UIs read from the same backend state. A message sent from the overlay appears instantly in the sidebar and vice versa.

### The problem Chat solves

During a live event, Omar sees on the Dashboard that Bar 3 is running low on premium vodka. Today, his only options are: walk over physically, call the manager's phone, or use WhatsApp — none of which leave a trail tied to the event, none of which are auditable post-event. Chat gives him a one-click path to tell Bar 3's manager "send someone to restock from warehouse, now" and have the conversation persist in the event record.

Secondary use case: bartenders flag issues upward ("two tables walking out without paying on south side") without the overhead of a call.

### What Chat explicitly is NOT (v1.0)

- Not a general team messenger. No DMs between two managers. No group chats across bars.
- Not an alert system. Alerts are their own module. Chat is human-to-human.
- Not threaded. Flat conversation per bar.
- Not searchable beyond "filter by bar." No full-text search until v1.1.
- Not reactions, not read-by-indicator-avatars, not typing indicators, not voice, not file upload. Text only.
- Not multi-tenant-cross-org. Every channel belongs to one tenant, period.

### Success criteria

A brand-new bartender at an event, given 60 seconds of training, can:
- See a message from Omar appear on their phone in under 2 seconds after Omar hits Send
- Reply, and have their reply appear on Omar's Dashboard overlay within 2 seconds
- Scroll up to see the last 20 messages of context if they step away and come back

Omar, on the Dashboard:
- Can open any bar's overlay and see the same conversation that the bartender sees on their phone
- Can navigate to the sidebar Chat page and see all bars' channels in one list, with unread counts
- Never has to ask "which message are you replying to" because there's only one conversation per bar

---

## 2. User & role model

### Who has accounts

| Role | Purpose | How they log in | What they see |
|---|---|---|---|
| Owner | Omar, the tenant admin | Email + password (existing auth) | All channels for all bars at all events owned by the tenant |
| Manager | One per bar — the person running that bar | Email + password | The channel for THEIR bar only, for the currently-live event |
| Bartender | Optional secondary staff at a bar | Email + password | Read-only access to their bar's channel (can receive urgent messages but doesn't reply to Omar directly — keeps signal-to-noise high) |

For v1.0 we do NOT need to build the Bartender role — Omar and Manager cover the primary use case. Bartender is stubbed in the schema but no UI affordance.

### Account creation flow

- Owner: already exists, created via tenant signup
- Manager: Owner invites them via `POST /users/invite` with `{email, role: "manager", default_bar_id}`. Manager gets an email with a signup link. Clicks it, sets password, is now a user in the tenant. This invite flow is its own small scope — probably ~2 hours of work, but it's prerequisite to Chat being real.
- Bartender: Same invite flow, different role. Deferred for v1.0.

### Permission matrix

| Action | Owner | Manager (at their bar) | Manager (at different bar) | Bartender |
|---|---|---|---|---|
| Read channel messages | ✅ | ✅ | ❌ | ✅ (own bar only) |
| Post message | ✅ | ✅ | ❌ | ❌ (v1.0) |
| Delete message | ✅ (own messages + any) | ✅ (own only) | ❌ | ❌ |
| See channel list | ✅ (all bars at tenant's events) | ✅ (own bar only) | ❌ | ✅ (own bar only) |

Enforcement happens at the service layer, NOT just at the router layer. A `ChatPermissionError` is raised if the rules are violated, translated to 403 in the router.

### Channel identity

One channel per (tenant, event, bar) triple. When a bar is created for an event, a channel is created lazily on first message. When the event ends, the channel becomes read-only (history preserved, no new messages accepted). When the event is deleted, the channel cascades.

This means: Channel IDs are stable per-bar-per-event. A manager who works Bar 3 at Sundance 2026 has a different channel than the same manager at a different event. This is intentional — each event's chat log is a standalone artifact for post-event review.

---

## 3. Data model

### Three tables

```sql
-- One row per bar-per-event channel. Created lazily on first message.
CREATE TABLE chat_channels (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_id         UUID NOT NULL REFERENCES events(id)  ON DELETE CASCADE,
    bar_id           UUID NOT NULL REFERENCES bars(id)    ON DELETE CASCADE,
    is_closed        BOOLEAN NOT NULL DEFAULT FALSE,  -- true once event ends
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at        TIMESTAMPTZ,

    CONSTRAINT chat_channels_tenant_event_bar_unique
        UNIQUE (tenant_id, event_id, bar_id)
);

CREATE INDEX chat_channels_tenant_event_idx
    ON chat_channels (tenant_id, event_id);

-- One row per message. Append-only (deletion uses a soft-delete flag).
CREATE TABLE chat_messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id)        ON DELETE CASCADE,
    channel_id       UUID NOT NULL REFERENCES chat_channels(id)  ON DELETE CASCADE,
    sender_user_id   UUID NOT NULL REFERENCES users(id)          ON DELETE RESTRICT,
    body             TEXT NOT NULL,                -- already-sanitized, see §7 hostile input
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at       TIMESTAMPTZ,
    deleted_by_id    UUID REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chat_messages_body_not_empty CHECK (length(trim(body)) > 0),
    CONSTRAINT chat_messages_body_max_len    CHECK (length(body) <= 2000)
);

-- For "messages newest-first for a channel" - the single hot query
CREATE INDEX chat_messages_channel_created_idx
    ON chat_messages (channel_id, created_at DESC);

-- For per-user recent-activity summaries
CREATE INDEX chat_messages_tenant_sender_created_idx
    ON chat_messages (tenant_id, sender_user_id, created_at DESC);

-- Membership + read receipts. One row per (user, channel).
CREATE TABLE chat_participants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id)        ON DELETE CASCADE,
    channel_id          UUID NOT NULL REFERENCES chat_channels(id)  ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id)          ON DELETE CASCADE,
    role                VARCHAR(32) NOT NULL,          -- 'owner' | 'manager' | 'bartender'
    can_post            BOOLEAN NOT NULL DEFAULT TRUE,
    last_read_at        TIMESTAMPTZ,                   -- for unread-count computation
    added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chat_participants_user_channel_unique
        UNIQUE (channel_id, user_id)
);

CREATE INDEX chat_participants_user_idx
    ON chat_participants (user_id);
```

### Key decisions and rationale

- **No `is_read` column, one `last_read_at` timestamp.** Unread count = messages in channel with `created_at > participant.last_read_at`. Constant-memory, no matter how many messages pile up. Updating read-receipts is a single UPDATE, not N.

- **Soft-delete via `is_deleted`, not DELETE.** Deleted messages still occupy their position in the conversation, rendered as "message deleted" in the UI. Preserves conversational coherence, required for post-event audit.

- **Body length ceiling 2000 chars.** Long enough for a thoughtful message, short enough to prevent a 500KB blob being dropped into the stream. Client-side soft limit at 1800 with warning.

- **`chat_participants.can_post`** lets us enforce read-only bartender without inventing a separate role in code. Manager = `can_post=true`, Bartender = `can_post=false`. Owner is also `can_post=true`.

- **Channel creation is LAZY.** We don't create a channel row when a bar is created. We create it on the first message sent to that (event, bar). This keeps event setup cheap and lets us extend channel-creation rules later without data migrations.

- **`chat_participants` auto-population.** When a channel is lazily created: the Owner and the bar's default Manager are auto-inserted as participants. Manually adding participants later is a v1.1 feature.

- **Multi-tenant isolation enforced at every query.** Same pattern as every other module — `tenant_id` filter on every read.

### Schema invariants enforced at DB level

- Message body is non-empty after trimming → DB CHECK
- Message body ≤ 2000 chars → DB CHECK
- One channel per (tenant, event, bar) → DB UNIQUE
- One participant row per (user, channel) → DB UNIQUE
- Cascade deletes: if event is deleted, channels go; if channel goes, messages and participants go; if user is deleted, their participant rows go but their authored messages are RESTRICTED (we never orphan messages just because a user was removed)

---

## 4. API surface

All endpoints live under `/api/v1/chat/`. Typed error envelopes follow our existing convention (see Backend Bible §7.3).

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/chat/channels`                          | List channels the current user can access (+ unread counts) |
| `GET`  | `/chat/channels/{channel_id}/messages`    | Paginated message history, newest-first |
| `POST` | `/chat/channels/{channel_id}/messages`    | Send a message (cross-module validation + broadcast) |
| `POST` | `/chat/channels/{channel_id}/mark-read`   | Update caller's `last_read_at` |
| `DELETE` | `/chat/messages/{message_id}`           | Soft-delete a message (permission-checked) |
| `GET`  | `/chat/channels/by-bar/{event_id}/{bar_id}` | Resolve bar → channel_id (lazy-creates if missing) |

### Request / response shapes

```python
# POST /chat/channels/{channel_id}/messages
class SendMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    client_id: str | None = None  # optional, for echo-suppression (see §5)

class ChatMessageResponse(BaseModel):
    id: UUID
    channel_id: UUID
    sender_user_id: UUID
    sender_display_name: str  # denormalized for frontend convenience
    sender_role: str          # "owner" | "manager" | "bartender"
    body: str
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    client_id: str | None     # echoed back so sender can reconcile optimistic update

# GET /chat/channels returns List[ChannelSummary]
class ChannelSummary(BaseModel):
    channel_id: UUID
    event_id: UUID
    event_name: str
    bar_id: UUID
    bar_name: str
    is_closed: bool
    unread_count: int
    last_message: ChatMessageResponse | None
    participants_count: int
```

### Pagination strategy

`GET /messages` accepts `before` (ISO timestamp) and `limit` (default 50, max 200). Newest-first ordering. Clients page backward by setting `before = earliest_message.created_at` from the previous page.

NO offset-based pagination. New messages arriving during scroll would shift offsets and create holes.

### Idempotency

`SendMessageRequest.client_id` is an optional UUID the client generates per local send. If a client retries due to network flake, the server deduplicates on `(channel_id, sender_user_id, client_id)` within a 1-hour window. Prevents double-posts.

Implementation: add a partial unique index if idempotency turns into a real problem in testing. For v1.0 we keep it soft (best-effort) and add the hard index if we see duplicates in the wild.

### Authorization

Every endpoint checks: current user has a row in `chat_participants` for the relevant channel. If not, 403. Permissions layer runs before any data access.

`POST /messages` additionally checks `can_post=true` for the caller.

`DELETE /messages/{id}` additionally checks: caller is the sender OR caller has `role=owner` in this channel. Others get 403.

---

## 5. Realtime protocol

### Transport

We already have a Redis pub/sub publisher on the backend (`app.realtime.publisher`) and channel-subscription patterns (`event:*`, `chat:*`, `user:*`). Chat reuses this infrastructure — we do NOT introduce a second transport.

Frontend side: a single WebSocket connection per authenticated session. Already established for the existing realtime work. Chat adds a new message type, not a new socket.

### Channel subscription

Convention: `chat:{channel_id}`. When a client opens the overlay or the sidebar Chat page, it tells the server "subscribe me to these channels." Server checks permissions (participant exists), subscribes the socket to the pub/sub key.

### Event types published to `chat:{channel_id}`

```json
{
  "type": "message.sent",
  "channel_id": "...",
  "message": { /* ChatMessageResponse shape */ }
}

{
  "type": "message.deleted",
  "channel_id": "...",
  "message_id": "...",
  "deleted_by_id": "..."
}

{
  "type": "channel.closed",
  "channel_id": "..."
}
```

### Publish-after-commit, not publish-instead-of-commit

Same pattern as `stock_transactions`: the service commits the message INSERT to Postgres FIRST, then publishes to the Redis channel. If the publish fails, we log and move on — the message is safe in Postgres and will appear on the next refresh or reconnect. We never roll back the DB because of a publish failure. Ledger-integrity over real-time-niceness.

### Client reconciliation

On WebSocket reconnect, clients replay the last N messages via `GET /messages?before=<now>&limit=50` and merge with any messages received via socket. Messages are keyed by `id`, so duplicates dedupe naturally. This handles the "laptop sleep, wake up 2 hours later" case without special logic.

### Echo suppression

When the sender's own message comes back via the subscription, they need to NOT render it twice (they already rendered their optimistic local copy). The `client_id` field in the `ChatMessageResponse` is how the sender matches the server-echoed message back to the local optimistic one and reconciles in place.

---

## 6. Sync contract — overlay + sidebar

This is the specific requirement Hesam called out: the chat tab inside the BarDetailOverlay and the sidebar Chat page must stay in sync. Here's the contract.

### Single source of truth

Both UIs consume the SAME TanStack Query keys:

```ts
chatKeys = {
  channelList:  ['chat', 'channels'],
  messages:     (channelId) => ['chat', 'messages', channelId],
  channel:      (channelId) => ['chat', 'channel', channelId],
}
```

The overlay's chat section and the sidebar page both call `useQuery(chatKeys.messages(channelId))`. TanStack Query deduplicates: there's ONE network request, ONE cache entry, TWO subscribers. If one updates, the other re-renders.

### Invalidation triggers

- Socket event `message.sent` for a channel → `queryClient.setQueryData(chatKeys.messages(id), (old) => [message, ...old])` — surgical append, not full refetch
- Socket event `message.deleted` → patch the specific message in-place
- Socket event `channel.closed` → `queryClient.invalidateQueries(chatKeys.channel(id))`
- User sends a new message → optimistic local insertion + API call → reconcile on success via client_id match

### Unread-count consistency

The sidebar's unread badge for a channel is computed from `ChannelSummary.unread_count`, which comes from the backend's view (messages since `last_read_at`). When the user opens that channel in EITHER the overlay OR the sidebar:
1. Client fires `POST /channels/{id}/mark-read` with the current timestamp
2. Server updates the participant's `last_read_at`
3. Server publishes a user-scoped event `user:{user_id}` with `{type: "unread.changed", channel_id, unread_count: 0}`
4. All of this user's connected clients update their sidebar's unread badge

### Scroll position

Not synced. Overlay and sidebar maintain independent scroll. Only the data is shared.

### Draft input

Not synced. If Omar types in the overlay, then opens the sidebar, the draft does NOT appear in the sidebar. Draft is a UI-local concept. Keeping it local sidesteps ugly edge cases (what if both views are open and typing at once).

---

## 7. Edge cases

### Offline send
Client queues the send locally with a pending indicator. When network returns, replay the queue. Use `client_id` so the server deduplicates if the server actually received the first attempt before the network dropped.

Failure after 3 retries: show a red retry button on the local message, don't auto-retry further.

### Deleted messages
`is_deleted=true` messages still render in the list, as `"This message was deleted"` in muted gray text. Keeps conversation order stable. The body text is NOT returned by the API for deleted messages (privacy — a deleted message stays deleted).

### Bar handover mid-event
If a bar's manager is replaced mid-event (Manager A quits, Manager B takes over): Owner removes A and adds B to `chat_participants`. A loses access immediately (their next request gets 403). B sees the full channel history from when they join (they don't get retroactive "before you joined this was said"). B's `last_read_at` is set to NOW() on join so they only see unread for their tenure.

### Hostile input (XSS, SQL injection)
- **Storage:** Store `body` verbatim. Never modify user input on write. Postgres handles the SQL side via parameterized queries.
- **Rendering:** Frontend NEVER uses `dangerouslySetInnerHTML` for message bodies. Only text rendering. Tailwind + React auto-escapes. URL detection for "make links clickable" uses an allowlist regex for http/https, rendered as `<a>` with `rel="noopener noreferrer"`.
- **Length limit:** 2000 chars enforced server-side CHECK + client-side soft limit at 1800.

### Message length limits
Soft warn at 1800 chars in the client ("approaching limit"). Hard reject at 2000 server-side with typed error `message_too_long`.

### Rapid-fire flooding
Rate limit: 30 messages per user per channel per 60 seconds. Exceed → typed error `rate_limit_exceeded`, HTTP 429. Server-side sliding window in Redis.

### Message from a user who's no longer a participant
Can happen if a user is mid-sending when the Owner removes them. Server re-checks permission at message-insert time. If they've lost access: 403 with typed error `no_longer_participant`. Client shows the red retry/cancel on the message.

### Reconnection storms
100 bartenders + Omar all reconnecting at once after a flaky WiFi blip. Server handles WebSocket reconnection budget: max N new subscriptions per second per instance. Rate-limit excess with exponential backoff directive sent to the client.

### Channel closed during active conversation
Event ends while Omar is typing: the send hits 422 `channel_closed`. Client shows a banner: "This event has ended — channel is read-only." Existing messages remain readable.

### Cross-bar spillover
Prevented by `(tenant, event, bar)` uniqueness on channels and participant permissions. A manager at Bar 3 cannot see Bar 5's conversation even if they guess the channel_id.

---

## 8. Out-of-scope for v1.0

Deferred explicitly so scope stays tight. Each gets a GitHub issue at module-build-time.

- Typing indicators ("Omar is typing...")
- Reactions/emojis on messages
- Per-message read-by indicators
- File uploads, images, voice notes, video
- Message threading (reply-to-specific-message)
- @-mentions and notifications-on-mention
- Desktop push notifications (rely on in-app badge for v1.0)
- DMs between managers
- Cross-event channel history (each event has a separate channel even for the same bar+manager)
- Full-text message search
- Export to PDF / post-event chat archive
- Message editing (only delete + re-send in v1.0)
- Admin audit log of all chat activity
- Bots / programmatic posting (useful later for auto-alerts from anomaly engine)
- Archiving closed channels to cold storage

---

## 9. Build plan

### Prerequisites (blockers that must exist before Chat can be built)

1. **Manager role in the user model.** Right now only Owner exists. Adding Manager is ~2 hours: new enum value, role check middleware, seed data.
2. **User invite flow.** Owner → invites Manager by email. ~2 hours.
3. **Real user test accounts.** Create a Manager account for one test bar so we can open two browsers and actually test bidirectional.

Total prerequisites: **~4-5 hours**.

### Backend module — 6 phases matching our existing pattern

Follows the 4-layer convention we've used for every module (models → schemas → repository → service → router) plus the realtime piece.

| Phase | What | Hours |
|---|---|---|
| 1 | Alembic migration — 3 tables, indexes, constraints | 1 |
| 2 | `models.py`, `schemas.py`, permission helpers | 1 |
| 3 | `repository.py` — queries for channels, messages, participants, unread counts | 2 |
| 4 | `service.py` — business logic, permission checks, lazy channel creation, auto-participant | 2 |
| 5 | `router.py` — 6 endpoints with typed errors | 1.5 |
| 6 | Realtime: extend `app.realtime.publisher` patterns for `chat:*`, implement publish-after-commit in service | 1.5 |
| **Subtotal** | | **~9** |

### Frontend — 2 phases

| Phase | What | Hours |
|---|---|---|
| A | TanStack Query hooks (`useChannels`, `useChannelMessages`, `useSendMessage`, `useMarkRead`) + WebSocket integration in `useChannelMessages` | 2 |
| B | Wire the BarDetailOverlay chat section + the sidebar Chat page. Both consume the same hooks. Scroll, send, delete, unread. | 3 |
| **Subtotal** | | **~5** |

### Testing — 1 phase

| Phase | What | Hours |
|---|---|---|
| T | 12-scenario smoke battery: send/receive, permission denial, idempotency replay, rate limit, message-too-long, soft-delete, unread math, two-tab bidirectional, offline queue, reconnect reconcile, channel close, lazy channel create. Two-user manual test. | 2 |
| **Subtotal** | | **~2** |

### Grand total

| | Hours |
|---|---|
| Prerequisites (users/invites) | ~4-5 |
| Backend module | ~9 |
| Frontend | ~5 |
| Testing | ~2 |
| **Total** | **~20-21 hours** |

That's 2.5 focused workdays. Not a sprint task, not an evening hack. A proper mini-module.

### Proposed sequence when build time comes

Day 1 morning — prerequisites (users + invites).
Day 1 afternoon — backend phases 1-4.
Day 2 morning — backend phases 5-6, backend smoke tests.
Day 2 afternoon — frontend phase A, frontend phase B.
Day 3 morning — full integration test, two-user manual test, bug fix, commit.

Pacing caveat for Hesam: This module is materially more complex than any one module we built this week because of the realtime + multi-user angle. It should NOT be squeezed into a day with other unrelated work. Block the time.

---

## Appendix A — Decisions intentionally deferred to implementation time

Things the spec declines to decide now because they're best decided when building with the actual code in front of us:

- Exact pub/sub vs. direct-WS routing topology (depends on whether we end up running multi-instance backend)
- Client-side message cache eviction policy (probably TanStack Query default, but revisit when we see memory usage)
- Server-side full-text index strategy (deferred because search is out of scope for v1.0)
- Presence indicators ("Manager is online") — ambiguously in-scope; re-examine when building

## Appendix B — Open questions to ask Omar before build

1. Do we need a disclaimer / consent screen for bartenders ("messages are logged") for GDPR-flavored reasons given European deployment?
2. Retention policy: how long do we keep chat history after an event ends? 30 days? Forever?
3. Should Owner be able to read a channel silently (without triggering read-receipt visibility to the Manager)? Probably yes but confirm.
4. Italian UI: is chat translated, or do managers use English? Affects UI labels but not data model.

---

*End of spec. Save to `docs/chat-module-spec.md` in the repo when ready to build.*
