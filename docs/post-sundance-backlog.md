# Post-Sundance Backlog

Produced by state-of-project audit completed 2026-05-18.
Source: docs/audits/state-of-project-2026-05-17.md Section 5

After Sundance go-live (2026-06-19), this becomes the post-event
sprint inventory.

---

## Class A — Strategic deferrals

  A0.  Phase 1D-full: remove in-memory user.role shim from
       get_current_user dependency in auth/router.py:39
       Update get_active_role helper to read JWT active_role claim
       directly via FastAPI Request injection (signature changes
       to add request: Request parameter).
       Update 20 call sites to pass request.
       Run Alembic migration p2_drop_users_role_column to remove
       users.role from DB schema (user_roles join table remains
       the only source).
       Estimated time: 0.5-1 day post-Sundance.
       Why deferred: Phase 1D-min (helper + 20 sites migrated) is
       the Sundance-critical work.  Phase 1D-full is architectural
       cleanup that adds Sundance risk without Sundance value.

  A1.  Visual theme redesign (one pass after Sundance)
  A2.  Token rotation policy with Slesh (operational; week-after reminder)
  A3.  Multi-tenant scaling (only when adding 2nd tenant)
  A4.  Event P&L preview (needs wholesale cost data)
  A5.  Briefing Sheet preview (needs XHR staff-shift data)
  A7.  Async test infrastructure rebuild
  A9.  Multi-language UI (only if requested by 2nd client)

## Class B — UX polish

  B1.  URL state for tabs (3 surfaces)
  B2.  Loading skeletons on F5 (all 11 pages)
  B4.  "Ships in v1.1" footnotes cleanup
  B6.  Self-DM channel naming (seed data hygiene)
  B11. Allocations UI for warehouse staff (if not pre-Sundance)

## Class C — Feature gaps

  C1.  Detector #6 Warehouse Discrepancy (baseline #1+#2 sufficient)
  C2.  Manager auto-join bar channel hook
  C3.  PATCH /bars/{id}/manager UI endpoint
  C5.  Anomaly detectors #3, #4, #5

## Class D — Phase 8 closure

  D2.  Whitespace dedup in product names
  D3.  Brand-specific ingredient products

## Class E — Production hardening

  E2.  Rate limiting (slowapi retry; previous attempt broke chat send)

## Working as designed (NO-FIX)

  B8.  Active Alerts KPI (recon false positive)
  B12. Login role picker offering all 4 roles for warehouse.keeper
       (anti-enumeration design from Phase 1C.2)

---

## Suggested post-Sundance sequencing

Week 1 (2026-06-20 to 06-26):
  Post-event retrospective with Omar
  A1 visual theme redesign sprint
  A2 token rotation calendar reminder

Week 2-3 (2026-06-27 to 07-10):
  A3 multi-tenant scaling design
  C5 + C1 anomaly detector backlog
  A7 async test infrastructure rebuild

Month 2+ (2026-07-11+):
  A4 Event P&L (once cost data arrives)
  A5 Briefing Sheet (once staff data arrives)
  E2 Rate limiting retry
  A9 Multi-language UI (if requested)

---

Last updated: 2026-05-18

---

## [2026-05-26] Self-serve event-staff QR onboarding

**Status:** Design phase — DO NOT build pre-Sundance.

**Trigger context:** Walkthrough on 2026-05-26 surfaced 5 orphan
users with `bar_id=NULL` (manager.focacceria, manager.malandrino,
bartender.giulia/paolo/sofia). Root cause is that the current account-
creation flow has no clean way to assign staff to a bar at event time.

**Proposed feature:**

Owner creates a new event. Platform generates a QR code (or set of
QR codes) for that event. Each staff member scans the QR with their
phone camera, fills in name + email + role + which bar they are
working at. The platform creates the account, logs them in, drops
them into the bar's chat channel, and links them to the manager
plus other bartenders of that bar — all in under 30 seconds per
staff member.

**Constraints from Hesam (2026-05-26 conversation):**

- Max 5-6 bars per event — keeps the bar-picker simple.
- Must sync across all surfaces: account, chat membership, dashboard
  scoping, manager-staff linkage, alert audience.
- Must work on a phone browser (no native app dependency).

**Open design questions (answer FIRST, then build):**

1. **QR scope** — one per event, one per bar, or one per role-per-bar?
2. **Authentication after scan** — staff-set password, magic link,
   one-time pin, or QR-is-the-credential?
3. **Existing-email handling** — recognize and add to event, or block?
4. **Revocation** — who can remove a registered staff member?
5. **Schema change** — add `event_staff(event_id, user_id, bar_id, role)`
   junction table, or keep overwriting `users.bar_id`?
6. **QR validity window** — forever, event-bounded, owner-windowed,
   or single-use?
7. **Scan UX** — exact form fields, landing page, welcome message.

**Estimated effort once Q1-Q7 are answered:**

- Backend: 1-2 days (endpoint, QR generation, dedup logic, chat join)
- Frontend: 1-2 days (Owner config page, scan landing page, success flow)
- Schema migration + tests: 0.5 day
- Total: ~3-4 days for a clean MVP

**Sundance-related cleanup that will be unblocked by this feature:**

- The 5 orphan users can be re-onboarded properly at the next event
- The "default password xproject2026" testing pattern can retire
- Other venues using XProject get the same self-serve flow

**Do NOT implement before Sundance 2026-06-19.** This is post-event work.
