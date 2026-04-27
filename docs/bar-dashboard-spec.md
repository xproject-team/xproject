# Bar Dashboard — Manager + Bartender View · Spec v1.0

**Status:** Draft · **Owner:** Hesam · **Last updated:** 2026-04-27 · **Target:** Sundance June 2026

The dashboard surface for Manager and Bartender roles at /dashboard.
Owner has their own multi-bar overview at the same route already; this spec
defines what non-Owner roles see at the SAME path, with strict bar-scoping
and real-time sync across the page.

When this spec and any older document disagree, **this spec wins.**

---

## 1. Why this spec exists

Browser test on 2026-04-25 showed Manager logging in lands on /dashboard
with a **blank white page**. Root cause: DashboardPage line 309
hard-checks canViewAllBars and dead-ends non-Owner roles with
navigate('/'); return null — but / redirects back to /dashboard,
creating an unrenderable state.

The route guard correctly grants access (Owner OR Manager OR Bartender,
per auth-and-roles-spec S5.2). The page itself only handles Owner. This
spec closes the gap with three commitments:

1. **Role-aware single page.** /dashboard renders Owner's multi-bar
   overview for Owner, "My Bar" view for Manager, "My Bar" view for
   Bartender. One route, three role-conditional bodies.
2. **Real-time sync.** Every transaction, alert, message, and stock
   change reflects on the dashboard within ~200ms via WebSocket pub/sub.
   No manual refresh ever.
3. **Strict bar-scoping at the SERVER.** Bartender's browser never
   receives data for other bars. Manager's browser never receives other
   bars. Server enforces, not client filtering.

---

## 2. What we are NOT building in v1.0

| Item | Status | Why |
|---|---|---|
| Bartender per-shift view | Deferred v1.1 | Needs shift-time tracking we don't have |
| Manager-to-Manager direct chat | Deferred v1.1 | Owner-channel only for v1.0 |
| Custom date-range filtering | Deferred v1.1 | Always shows current Live event |
| Sparkline charts on KPI tiles | Deferred v1.1 | Static numbers for v1.0 |
| Push notifications for alerts | Deferred v1.2 | Web push is its own infrastructure question |
| Bar-vs-bar performance comparison | Deferred v2.0 | Owner-level concern |
| Offline mode / queued mutations | Deferred v2.0 | Sundance has WiFi |

---

## 3. Layout

The page header shows: My Bar - {bar_name} - Sundance 2026 - LIVE, plus a
live-sync indicator dot in the top-right.

Below the header, four KPI tiles in a row:
  - Stock Health
  - Revenue Tonight
  - Active Alerts
  - Last 5 Transactions

Below the KPIs, two panels side-by-side:
  - Active Alerts panel (left, 2/3 width)
  - Bar Chat panel (right, 1/3 width)

At the bottom, a full-width Last 5 Transactions table.

The live-sync dot in the top-right shows green when WebSocket is
connected, orange when reconnecting, red when disconnected. Auto-retry
on disconnect.

Design tokens (already in use):
  Brand blue #1E5A8D - Success #10B981 - Warning #DD6B20 - Danger #E74C3C

---

## 4. The four KPIs

### KPI 1 - Stock Health

Fields:
  total_products: number          // distinct SKUs at this bar
  products_at_risk: number        // count where current_qty < threshold
  total_units_remaining: number   // sum of current_qty
  pct_remaining: number           // sum(current) / sum(allocated) * 100

UI: tile shows headline pct_remaining with colored bar.
  >= 50% green, 20-50% orange, < 20% red.
Subtitle: "{units_remaining} units across {total_products} products. {at_risk} at risk."

### KPI 2 - Revenue Tonight

Fields:
  revenue_cents_so_far: number
  predicted_total_cents: number | null
  vs_predicted_pct: number | null

UI: tile shows EUR value formatted Italian (T1.5 helper).
Subtitle: "+/- {pct}% vs forecast" only when prediction exists.

### KPI 3 - Active Alerts

Fields:
  unresolved_count: number
  critical_count: number
  most_recent_alert: { product_name, severity, created_at } | null

UI: tile shows unresolved_count in red if critical_count > 0, else grey.
Subtitle: most recent alert summary or "All clear."

### KPI 4 - Last 5 Transactions

Fields:
  count_today: number
  most_recent: ScanResponse[]   // 5 most recent

UI: tile shows count_today. Click scrolls to the transactions table at bottom.

---

## 5. Active Alerts panel (mid-page, left 2/3)

Renders the same AlertWithVersion rows from /alerts, but:
  - Server-side filtered to bar_id == user.assignedBarId for non-Owner
  - Limited to 5 most recent unresolved + 3 most recent acknowledged
  - Acknowledge and Mark resolved buttons MANAGER ONLY
    (Bartender sees alerts but cannot action them)

If 0 alerts: calm empty state - "All quiet at your bar. We will show
stockouts, depletion warnings, and anomaly flags here."

---

## 6. Chat panel (right 1/3)

### Manager view
  - 5 most recent messages from the bar's channel
  - Header: Bar chat - {channel_name}
  - Message input + Send button
  - Restock Request button - pre-canned templated message:
    "@Owner - Bar {bar_name} needs restock. Low items: {at_risk_products}."
    Auto-fills at_risk_products from KPI 1's data. One click sends.
  - "Open full chat" link to /chat?channel={channel_id}

### Bartender view
  - Same recent messages preview, READ-ONLY (no input field)
  - "Open full chat" link works the same
  - No Restock Request button (per auth-and-roles-spec S5.3)

If chat module not wired or channel does not exist: empty state
"Chat coming soon for this bar."

---

## 7. Last 5 Transactions table (bottom, full width)

Columns: Time - Product - Qty - User - Total

Same scoping as everything else (bar-filtered server-side).
Read-only for both Manager and Bartender (transactions are append-only
via POS scan flow).

If 0 transactions: empty state "No sales yet tonight. Transactions
will appear here as they happen."

---

## 8. Real-time sync

### 8.1 Architecture (uses existing infra)

Backend already has app/realtime/publisher.py running per-tenant Redis
pub/sub. From uvicorn boot logs:
  subscriber: subscribed to 4 patterns: event:*, chat:*, user:*, alerts:*

We add stock:* as a 5th pattern (publishes when bar_stock or
stock_transactions change).

### 8.2 Frontend WebSocket hook

Single hook useDashboardSocket(eventId, barId) opens one WS connection
per page mount, listens for events scoped to (event, bar) pair, and
calls TanStack Query invalidateQueries on relevant cache keys.

Backend publisher.py already publishes alerts. We add publish calls in:
  - BarStockService.upsert_* -> stock:{tenant}:{event}:{bar}
  - StockTransactionsService.record_* -> transaction:{tenant}:{event}:{bar}
  - ChatService.post_message -> already publishes chat:*

### 8.3 Connection states

  Connected:   green dot + "live" - real-time updates flowing
  Reconnecting: orange dot - auto-retry every 2s up to 10 attempts
  Disconnected: red dot + "Refresh page" button after 10 failed retries

When reconnected after a gap, all queries are invalidated so the page
catches up to current state.

### 8.4 Fallback: polling

If WebSocket fails to connect at all, page falls back to polling each
query at 10s intervals. Silent safety net - user never sees an error.

---

## 9. Server-side bar-scoping

### 9.1 Why server-side, not client filtering

A motivated Bartender opens DevTools, watches network requests, sees
other bars' data even if the UI hides it. Real isolation requires the
server to never send what the role is not entitled to see.

### 9.2 Endpoints that need bar_id scoping

  GET /bar-stock/by-event/{event_id}     -> add ?bar_id= param + role check
  GET /alerts?event_id=                  -> add ?bar_id= param + role check
  GET /stock-transactions?event_id=      -> add ?bar_id= param + role check
  GET /chat/channels/{id}/messages       -> already channel-scoped, no change
  GET /burn-rate/by-event/{event_id}     -> OK, returns per-bar slices

### 9.3 Backend enforcement pattern

Single guard function in service layers:
  assert_bar_access(user, requested_bar_id):
    if user.role == OWNER: return
    if user.assigned_bar_id is None: raise PermissionDenied("No bar assigned")
    if user.assigned_bar_id != requested_bar_id:
      raise PermissionDenied("Cannot access other bars")

Called by every list endpoint at the top. Owner bypasses, Manager and
Bartender enforce against assignedBarId.

### 9.4 Client-side adaptation

Existing hooks accept an optional barId parameter. When user is Manager
or Bartender, the hook auto-passes their assignedBarId. Owner-side code
that needs all bars passes barId=null explicitly.

---

## 10. Component structure

  pages/dashboard/DashboardPage.tsx
    - Owner branch: existing multi-bar overview (no changes)
    - Manager branch: <BarDashboardView role="manager" />
    - Bartender branch: <BarDashboardView role="bartender" />

  features/dashboard/
    BarDashboardView.tsx          - role-gated single component (NEW)
    KpiTile.tsx                    - reusable, used 4x (NEW)
    ActiveAlertsPanel.tsx          - dashboard + reuse on /alerts
    BarChatPanel.tsx               - embeds bar's chat channel
    RecentTransactionsTable.tsx    - dashboard
    useDashboardSocket.ts          - WebSocket hook (NEW)
    useBarKpis.ts                  - composes the 4 KPI queries (NEW)

The role prop on BarDashboardView drives:
  - Whether Acknowledge / Mark resolved buttons show on alerts
  - Whether chat input is editable or read-only
  - Whether Request Restock button shows
  - All visible content is identical otherwise

---

## 11. Implementation plan - sub-patches

  3b.1  Backend bar_id scoping + assert_bar_access guard       ~45 min  COMMIT
        Files: 3 service files + 3 routers
  3b.2  Backend stock:* pub/sub + wire BarStock + Transactions ~30 min  COMMIT
        Files: 2 service files + publisher.py
  3b.3  Frontend BarDashboardView scaffold + role gate         ~30 min  COMMIT
        Files: DashboardPage.tsx + new BarDashboardView.tsx
        (closes blank-page bug)
  3b.4  Frontend 4 KPI tiles + alerts panel + transactions     ~60 min  COMMIT
        Files: 5 new components
  3b.5  Frontend bar chat panel + Restock Request button       ~45 min  COMMIT
        Files: BarChatPanel.tsx
  3b.6  Frontend useDashboardSocket hook + connection indicator ~30 min  COMMIT
        Files: useDashboardSocket.ts + indicator
  3b.7  Browser test all roles + final commit                   ~20 min  COMMIT

Total: ~4 hours of implementation across 7 sub-patches.
Between each sub-patch we commit. If energy fails mid-session, nothing
is lost - the last commit is always shippable.

---

## 12. Edge cases & empty states

  User has assignedBarId == null (Manager misconfigured):
    Banner "Your account is not assigned to a bar. Contact Owner."

  No Live event in progress:
    Same as Owner - "No Live event. Start one from /events."

  Live event exists but bar has no bar_stock rows:
    KPI 1 shows zeros + "No stock allocated yet" hint

  0 alerts:
    KPI 3 shows 0 in grey + "All clear" subtitle. Alerts panel: empty state.

  0 transactions:
    KPI 4 shows 0 + "No sales yet" subtitle. Table: empty state.

  Chat channel does not exist for the bar:
    Chat panel "Chat not yet configured for this bar."

  WebSocket fails to connect:
    Orange "reconnecting" indicator. Polling fallback at 10s.

  User loses internet entirely:
    Red "offline" indicator after 10 retries. "Refresh page" button.

  Wrong-bar API call (Manager tries to query other bar):
    Backend 403; frontend shows toast "You can only view your assigned bar."

---

## 13. Testing checklist

When 3b.7 commits, manually verify:

  [ ] Owner login - multi-bar dashboard unchanged
  [ ] Manager (M. Cocktail) login - bar dashboard renders cocktail bar
  [ ] Manager sees their own alerts only (verify via DevTools Network)
  [ ] Manager can acknowledge an alert - it disappears from panel
  [ ] Manager can send chat message - appears in panel + propagates
  [ ] Manager clicks Restock Request - templated message sent to Owner
  [ ] Bartender login - same dashboard but no acknowledge buttons + no chat input
  [ ] WebSocket disconnect - indicator turns orange - reconnects to green
  [ ] WebSocket dead - polling fallback after 10s - updates still visible
  [ ] Manager opens dashboard in 2 tabs - tab 1 sends - tab 2 sees within 1s
  [ ] Manager queries /api/v1/bar-stock/by-event/X?bar_id=OTHER directly - 403

---

## 14. Future scope (not v1.0)

Tracked here so nothing important gets forgotten:

  Sparkline charts on KPI tiles (v1.1)
  Bartender per-shift "you sold N drinks tonight" view (v1.1)
  Custom date filtering (v1.1)
  Push notifications for critical alerts (v1.2)
  Bar-vs-bar performance comparison for Owner (v2.0)
  Offline mode with queued mutations (v2.0)

---

## 15. Document history

  v1.0  2026-04-27  Hesam  Initial spec. Locks 4-KPI design, real-time
                            WebSocket sync, server-side bar-scoping.
                            Bartender = read-only Manager view.
