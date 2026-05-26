# Phase 8 — Dress rehearsal findings

Date kicked off: 2026-05-23
Goal: simulate Sundance 2026 end-to-end across all four roles, then
inject synthetic events to stress the alert pipeline.  Catch what WS2
missed before go-live.

## Severity scale

    S1   operator unusable; blocks Sundance              fix immediately
    S2   broken but workable; must fix before live       fix this week
    S3   visual / UX; fix if time permits                triage
    S4   cosmetic only                                   defer to backlog

## Round structure

    Round 1 — Owner walkthrough (broadest permissions)
    Round 2 — Manager walkthrough (single-bar scope)
    Round 3 — Bartender walkthrough (scan + alerts only)
    Round 4 — Warehouse walkthrough (scan + reconciliation)
    Round 5 — Synthetic stress (depletion / spike / deviation injection)
    Round 6 — Event lifecycle (end event → report generation)

## Findings — format

For each finding, fill in:

    ### Pn-N — short title

    Role:        Owner / Manager / Bartender / Warehouse
    Page:        /route
    Severity:    S1 / S2 / S3 / S4
    Observed:    what happened
    Expected:    what should happen
    Notes:       any debugging context

---

## Round 1 — Owner walkthrough

Date executed:  2026-05-26
Driver:         Hesam + Claude (terminal) + Claude in Chrome (browser agent)
Login:          omar@nomagroup.it / xproject2026
Landing route:  /dashboard (after fix; see P1-23 below)

### P1-23 — Stale localStorage 'lastPath' surprises Owner at login
Role:        Owner
Severity:    S2
Observed:    Owner login redirected to /alerts instead of /dashboard.
Expected:    Login should redirect to ROLE_LANDING[role] = /dashboard.
Notes:       SessionExpiredModal writes lastPath; LoginForm consumes it.
             No TTL on the stored value -> entries from days ago override
             today's role default. At Sundance: Owner logs in next morning
             confused by landing on whatever page he last saw.
Fix:         JSON {path, ts} payload + 30-min TTL guard.
             Shipped commit 7d4c8d7.

### P1-24 — Dashboard counted resolved alerts as unacknowledged (117 vs 3)
Role:        Owner
Severity:    S1
Observed:    KPI strip showed UNACKNOWLEDGED 117; sidebar showed 117 in
             header AND rendered 126 cards with Acknowledge buttons.
             DB truth: 3 active anomaly alerts.
Expected:    KPI=3, header=3, list=3.
Notes:       Counter filter checked only the client-side acknowledged Set,
             ignoring acknowledged_at, auto_resolved_at, expired_at from
             the server response. Sundance impact: Omar would panic at
             the inflated number and try to ack already-resolved alerts.
             Root cause was a chain of dropped fields - the legacy-shape
             adapter on line 405 of DashboardPage.tsx dropped lifecycle_state
             entirely. Fixed by carrying lifecycle_state through the adapter
             AND filtering on 'lifecycle_state === active' in both the
             counter AND the rendered sidebar list.
Fix:         Shipped commit 7d4c8d7.

### P1-25 — Anomaly-acknowledge → chat auto-post verified working
Role:        Owner
Severity:    (not a bug - verification record)
Observed:    Clicking Acknowledge on an anomaly alert (audience=owner_only)
             updates the alert row (acknowledged_at set, acknowledged_by_user_id
             set) AND posts a neutral 'routine count' message to the bar's
             chat channel within 14 ms. The chat message is authored as
             the Owner (sender_id = ack user), NOT system-authored.
Expected:    Matches design intent in alerts/service.py comment line ~440.
Notes:       Memory previously framed this as 'silent investigation' which
             overstated the deception. The manager sees an honest message
             from Omar; only the trigger reason (an anomaly fired) is
             hidden from them.
Fix:         No code change. Memory + cheat sheet wording corrected to
             match real behaviour. Shipped commit e9b6456.

## Round 2 — Manager walkthrough

Date executed:  2026-05-26
Driver:         Hesam (manual browser drive)
Login:          manager.cocktail@nomagroup.it / xproject2026
Landing route:  /dashboard with Cocktail Bar context

### P2-1 — Manager dashboard renders correctly with bar-scoped data
Role:        Manager
Severity:    (verification only)
Observed:    Manager landed on /dashboard with 'Cocktail Bar' header,
             stock health 84%, revenue 3,928€, last 5 transactions visible.
             BAR CHAT panel shows pre-existing messages + has working
             Type-a-message input.
Expected:    Manager sees only their assigned bar.
Notes:       Confirmed via side-by-side comparison with Owner view -
             same bar, same revenue, but Manager UI omits anomaly alerts
             (audience=owner_only correctly hidden).

### P2-2 — Manager → Bar chat real-time push (forward direction)
Role:        Manager
Severity:    (verification only)
Observed:    Manager typed and sent 'Surface 3 test - manager ping at 17:35'
             from the dashboard inline chat panel. Message appeared in the
             bartender's window (different browser, different session) in
             real time without manual refresh. DB confirms persistence
             with correct sender_id.
Expected:    WebSocket push delivers to all subscribers of the bar channel.

### P2-3 — Bartender → Manager chat real-time push (reverse direction)
Role:        Bartender
Severity:    (verification only)
Observed:    Bartender clicked 'Open full chat →' to reach the full chat
             view, typed and sent a reply. Message appeared in the manager's
             dashboard chat panel without refresh.
Expected:    Same as P2-2 in reverse.
Notes:       Bartender's dashboard chat panel is READ-ONLY (no inline send
             input). Must click 'Open full chat →' to reach the send view.
             Logged as P3-1 for triage.

### P2-4 — Cross-role chat visibility verified
Role:        Owner/Manager/Bartender
Severity:    (verification only)
Observed:    Owner-authored chat message (from the anomaly-ack auto-post)
             is visible to Manager AND Bartender on the same bar.
             Manager-authored messages are visible to Bartender.
             Bartender-authored messages are visible to Manager.
Expected:    All three roles share the same bar channel.

## Round 3 — Bartender walkthrough

Date executed:  2026-05-26
Driver:         Hesam (manual Safari drive, side-by-side with Manager Chrome)
Login:          bartender.luca@nomagroup.it / xproject2026
Landing route:  /dashboard with bartender-scoped UI

### P3-1 — Bartender dashboard chat panel is read-only (intentional?)
Role:        Bartender
Severity:    S3
Observed:    The BAR CHAT panel on the bartender's dashboard shows the
             message list and an 'Open full chat →' link, but NO inline
             send input. The manager's panel had the send input inline.
Expected:    Unclear - might be intentional (keeps bartender focused on
             pouring) or might be missing.
Notes:       Bartender CAN send from the full chat view at /chat. So the
             functionality is present, just not inline. If Omar wants
             bartenders to send quick messages without leaving /dashboard,
             this needs to be enabled. Triage with Omar before fix.

### P3-2 — Chat scrollback timestamps show time only, not date
Role:        Bartender
Severity:    S4
Observed:    Messages from 28 April 2026 display as '05:20 PM' with no
             date prefix.
Expected:    Yesterday/older messages should show 'Apr 28' or similar.
Notes:       Sundance impact minimal but real - after midnight, all of
             today's earlier messages will look 'recent' to a tired
             bartender doing reconciliation.

### P3-3 — Bartender sidebar shows correct role-specific items
Role:        Bartender
Severity:    (verification only)
Observed:    Sidebar shows: My Bar, Scan Empties, Inventory, Chat, Settings.
             No 'Alerts' or 'Reports' or admin pages. KPI header chip
             'Bottles opened today: 12' is bartender-specific.
Expected:    Role-scoped UI hides irrelevant management pages.

### P3-4 — Two channels visible to bartender (bar + DM)
Role:        Bartender
Severity:    (verification only)
Observed:    Sidebar in full chat view lists:
               - Bar Team: Cocktail (bar channel)
               - DM: Luca Bianchi ↔ Manager ... (direct message channel)
Expected:    Bar channel always present; DM channels created on demand.
Notes:       Bonus finding - DM functionality is wired in addition to
             the bar channel. Not tested for Sundance use.

## Cross-cutting findings (data hygiene)

### X1 — Five orphan users with bar_id=NULL
Roles:       Manager (focacceria, malandrino), Bartender (giulia, paolo, sofia)
Severity:    S2 (blocks usability for these specific users at Sundance)
Observed:    psql query against users table on 2026-05-26 showed 5 active
             accounts with bar_id=NULL:
               - manager.focacceria@nomagroup.it
               - manager.malandrino@nomagroup.it
               - bartender.giulia@nomagroup.it
               - bartender.paolo@nomagroup.it
               - bartender.sofia@nomagroup.it
             Bars 'Focacceria' and 'Malandrino' DO exist in the bars table,
             so the 2 manager accounts have an obvious likely mapping.
Expected:    Active staff accounts should be assigned to a bar.
Notes:       At Sundance, if any of these 5 try to log in:
               - They can authenticate (account is active)
               - But /dashboard cannot load bar-scoped data
               - They cannot see or send chat messages
               - They get a broken-feeling experience
             ACTION NEEDED FROM OMAR before Sundance:
               1. Are these 5 accounts real upcoming staff, or leftover
                  test seeds? (If test seeds: deactivate them.)
               2. If real: which bar does each one work at?
             Once Omar answers, run a one-line SQL UPDATE per user.
             Long-term fix: covered by post-Sundance QR-onboarding feature
             (see docs/post-sundance-backlog.md entry dated 2026-05-26).

## Round 4 — Warehouse walkthrough

Date executed:  2026-05-26
Driver:         Hesam (Safari) + Claude in Chrome (terminal agent)
Login:          warehouse.keeper@nomagroup.it / xproject2026
Landing route:  /warehouse

Verdict:        SUNDANCE-SAFE. Zero red console errors. Zero 404s.
                All routes load. Role-based UI is clean and consistent.
                B13 fix verified live: role badges (OWNER, MANAGER,
                BARTENDER) render capitalized in the activity feed,
                confirming commit 6792b69 landed correctly.

### W1 — Pending Deliveries section has no empty state
Role:        Warehouse
Severity:    S4
Observed:    On /warehouse/scan, after the invoice form, the "Pending
             Deliveries" heading shows with blank space below it. No
             placeholder text, no icon, no hint.
Expected:    Empty-state text such as "No pending deliveries yet" with
             optional guidance on how to add one.
Notes:       Cosmetic only; user might briefly wonder if the page is
             broken before realizing it's intentionally empty.

### W2 — Inventory CATEGORY column is blank
Role:        Warehouse
Severity:    S3
Observed:    The Inventory table has a CATEGORY column header, but the
             one rendered row (Bacardi Rum 1L) shows no category value.
Expected:    Either remove the column if no data is being populated, or
             populate it from the product's category enum.
Notes:       Could be a seed-data gap or a frontend rendering bug.
             Needs investigation to determine which.

### W3 — Inventory has only 1 distinct product
Role:        Warehouse
Severity:    S3 (needs triage)
Observed:    Inventory shows 1 distinct product (Bacardi Rum 1L, 95 units)
             despite the venue having 22 bars serving cocktails, beer, food,
             gelato, wine, etc.
Expected:    Unclear — could be by design (warehouse only tracks physically
             dispatched items in its custody) or a seed-data gap.
Notes:       Triage with Omar before Sundance. If by design, the dashboard
             needs a label clarifying "tracked in warehouse" vs "in event bars".
             If a bug, the warehouse view will look thin during the event.

### W4 — Language toggle effect unclear
Role:        Warehouse (also visible to all roles via Settings)
Severity:    S3
Observed:    "Italiano" is the selected language toggle, but the UI text
             remained in English throughout. A note says "Persistence
             across devices ships in v1.1" suggesting intentional partial
             implementation.
Expected:    Either the toggle should immediately change the UI language,
             or the toggle should be disabled with a clearer "coming soon"
             label until the feature is wired.
Notes:       Today's commit 6792b69 changed the disclaimer to a positive
             helper text, but if the toggle itself doesn't switch the UI
             yet, the helper text "Your selection applies to both the UI
             and the reports" is overconfident.

### W5 — "+ New Delivery" navigates instead of opening a modal
Role:        Warehouse
Severity:    S4
Observed:    The "+ New Delivery" CTA on the dashboard navigates to
             /warehouse/scan rather than opening a modal/dialog. The
             button label reads like a modal trigger.
Expected:    Either change the button label to suggest navigation
             ("Open New Delivery"), or convert the form to a modal.
Notes:       Cosmetic mismatch between affordance and behavior; reasonable
             design choice but worth aligning the label.

## Round 5 — Synthetic stress

_(pending)_

## Round 6 — Event lifecycle

_(pending)_
