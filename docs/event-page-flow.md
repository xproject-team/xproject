# Event Page Flow — Navigation & State Contract

Single source of truth for Event lifecycle, button behavior, page transitions,
and cross-page sync rules. Every code change to Event-related pages must be
cross-checked against this document.

Last updated: 2026-04-15
Owner: Hesam
Status: v1.0

---

## 1. State Machine

Events have exactly 4 lifecycle states. Transitions are one-way (no rollback).

  DRAFT  --Activate-->  ACTIVE  --Go Live-->  LIVE  --End Event-->  COMPLETED

State definitions:

- DRAFT: Owner is still configuring. Schema mutable. No live data.
- ACTIVE: Configuration locked. Pre-event tasks (staff confirm, smoke test). No live data yet.
- LIVE: Event running. POS open. Dashboards updating. Real-time data flowing.
- COMPLETED: Event ended. All data frozen. Report generated. Owner read-only.

Auto-transition: Live becomes Completed when now() > event.ended_at AND no manual end was triggered.

---

## 2. Button Matrix

### Events List page (/events)
- View: visible on all statuses → navigates to /events/{id} → backend GET /events/{id}

### Event Detail page (/events/{id})
- Edit Event: Draft/Active/Live → toggles inline edit mode (no backend call until Save)
- Save Changes: only when editing → PATCH /events/{id}
- Cancel: only when editing → revert draft, exit edit mode (no backend call)
- Activate Event: Draft only → status becomes Active. NO dialog, NO nav change. POST /events/{id}/activate
- Go Live: Active only → CONFIRM dialog → status becomes Live → SECOND dialog "Stay or Open Dashboard?". POST /events/{id}/start
- End Event: Live only → CONFIRM dialog → status becomes Completed → STAY on Detail page. POST /events/{id}/end
- View Dashboard: Active/Live → navigates to /dashboard
- View Report: Completed only → navigates to /reports/{event_id}

### Inline Edit field rules per status

| Field            | Draft | Active | Live   | Completed |
|------------------|-------|--------|--------|-----------|
| Name             | edit  | edit   | edit   | read-only |
| Date             | edit  | edit   | LOCKED | read-only |
| Venue            | edit  | edit   | LOCKED | read-only |
| Number of Bars   | edit  | edit   | LOCKED | read-only |
| Expected Guests  | edit  | edit   | edit   | read-only |
| Created          | LOCKED| LOCKED | LOCKED | LOCKED    |
| Status           | LOCKED| LOCKED | LOCKED | LOCKED    |

Locked fields show a small lock icon + tooltip: "Locked while event is live"

---

## 3. Navigation Map

EVENTS LIST → click View → EVENT DETAIL
EVENT DETAIL → Edit Event → enters inline edit mode (same page)
  → Cancel: exits edit mode (same page)
  → Save Changes: PATCH backend, exits edit mode (same page)
EVENT DETAIL → Activate Event (Draft only) → status becomes Active (same page, buttons re-render)
EVENT DETAIL → Go Live (Active only):
  → confirmation dialog "Go Live with this event?"
    → Cancel: close dialog
    → Yes, Go Live: status becomes Live → second dialog "Event is live. Where to?"
      → Stay on Detail: close dialog
      → Open Dashboard: navigate to /dashboard
EVENT DETAIL → End Event (Live only):
  → confirmation dialog "End {name}?"
    → Cancel: close dialog
    → Yes, End Event: status becomes Completed, stay on same page (now Completed view)
EVENT DETAIL → View Dashboard (Active/Live) → /dashboard
EVENT DETAIL → View Report (Completed) → /reports/{id}

Key rules:
1. No silent redirects. Owner always knows when they are being moved.
2. Confirmation dialogs only for destructive/irreversible actions: Go Live, End Event.
3. Activate Event has no dialog (soft transition, no live data yet).
4. Save Changes has no dialog (Owner expects immediate confirmation via UI update).
5. Completed events use the same /events/{id} route — read-only mode is computed from status.

---

## 4. Cross-Page Sync Rules

When something happens on Event Detail, what must update elsewhere:

- Edit Name → Events List row, Header breadcrumb, Dashboard event picker, Report title
- Edit Expected Guests → Events List Guests column, Dashboard KPI, Capacity calculations
- Edit Date → Events List Date column, Dashboard "Event Day" widget
- Edit Venue → Events List Venue column, Dashboard footer
- Edit Number of Bars → Bars table count, Dashboard bar grid layout, Inventory page bar list
- Activate (Draft → Active) → Events List badge, Dashboard "ready" indicator
- Go Live (Active → Live) → Events List badge, Dashboard becomes accessible, Alerts page activates
- End Event (Live → Completed) → Events List badge, Dashboard becomes read-only snapshot, Report generated, Alerts deactivate

Sync mechanism:
- Today (mock data): local React state — changes only visible within the same session.
- Tomorrow (backend wired): TanStack Query cache invalidation. After mutation, invalidate ['events'], ['events', id], ['dashboard']. All consumers re-fetch automatically.

---

## 5. Backend Endpoints Needed

| Method | Path                              | Purpose                            |
|--------|-----------------------------------|------------------------------------|
| GET    | /api/v1/events                    | List all events for tenant         |
| GET    | /api/v1/events/{id}               | Single event detail                |
| POST   | /api/v1/events                    | Create new event                   |
| PATCH  | /api/v1/events/{id}               | Update editable fields             |
| POST   | /api/v1/events/{id}/activate      | Draft to Active transition         |
| POST   | /api/v1/events/{id}/start         | Active to Live transition          |
| POST   | /api/v1/events/{id}/end           | Live to Completed transition       |
| GET    | /api/v1/events/{id}/bars          | Bars belonging to event            |

Status enum (Postgres + Pydantic + TypeScript must match):
'draft' | 'active' | 'live' | 'completed'

PATCH payload (editable fields only):
{ "name"?, "date"?, "location"?, "expected_guest_count"?, "bars_count"? }

Server validates per-field whether editing is allowed in current status.
Returns 409 if Owner tries to edit a locked field on a Live event.

---

## 6. Open Questions (for Omar discussion)

1. Reports page (/reports/{id}) does not exist yet. Build alongside backend wiring or defer to v1.1?
2. Dashboard event scoping: if multiple events go Live simultaneously, how does Dashboard pick? Event picker?
3. Auto-transition timing: Live to Completed exactly at ended_at, or with a 30-min buffer for late sales reconciliation?
4. Soft delete on Draft events: should Draft events be deletable? Active/Live/Completed should never be deletable.
5. End Event = report generation: takes how long? Show progress bar? Email notification when ready?
6. Activate Event side effects: should activation lock prices automatically? Send notification to staff?

---

## 7. Implementation Status (today)

Built and verified:
- State machine: 4 statuses in types.ts
- Auto-transition Live to Completed by ended_at
- Events List with View-only buttons + 5 status tabs
- Edit/Save/Cancel inline edit on Detail page
- Lock matrix (Live = name+guests editable, Date/Venue/Bars locked)
- Activate Event button (Draft only)
- Go Live button (Active only)
- End Event confirmation dialog
- Status-aware action buttons
- Local override pattern for mock data persistence

Known gaps to close before moving to Page C:
1. Add Go Live confirmation dialog (matches End Event pattern)
2. Add post-Go-Live "Stay or Open Dashboard?" choice dialog

Not yet built:
- All backend endpoints (only GET /events and POST /events exist from earlier)
- Cross-page sync via TanStack Query (mock data only today)
- Reports page

---

## 8. Change Log

2026-04-15: v1.0 initial document covering Pages A + B
