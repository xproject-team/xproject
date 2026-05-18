# Post-Sundance Backlog

Produced by state-of-project audit completed 2026-05-18.
Source: docs/audits/state-of-project-2026-05-17.md Section 5

After Sundance go-live (2026-06-19), this becomes the post-event
sprint inventory.

---

## Class A — Strategic deferrals

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
