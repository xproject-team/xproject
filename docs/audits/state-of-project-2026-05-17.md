# XProject — State of Project Audit
# 2026-05-17

**Audit owner:** Hesam (technical lead)
**Audit purpose:** Reconcile what is shipped vs what docs claim before
adding any new features.  Standard pre-event discipline 33 days before
Sundance 2026 go-live.
**Output:** This document is the single source of truth for project
state until it is superseded by the next audit.

────────────────────────────────────────────────────────────

## 1. Audit methodology + scope

Three layers of verification, in order:

  Layer 1  Documented state
           Read every roadmap doc and closure doc.  Record what they
           CLAIM.

  Layer 2  Git state
           Cross-reference claims against git log.  Record what was
           actually shipped (commits with hashes).

  Layer 3  Code state
           Grep for TODO / FIXME / HACK / deferred markers in code.
           Inspect test coverage.  Identify feature flags + dead
           code.  Record actual runtime state.

Truth is where all three layers agree.  Drift is recorded as a finding.

Scope: every phase 0-9 of the Sundance Readiness Roadmap, plus the
Slesh integration work that was performed in parallel.

────────────────────────────────────────────────────────────

## 2. Phase-by-phase reality check

[ TO BE FILLED IN as we audit phase by phase ]

────────────────────────────────────────────────────────────

## 3. Today's Slesh work (mis-numbered as Phase 8)

The 11 commits from 2026-05-11 to 2026-05-17 were attached to a
"Phase 8" label in our internal closure docs.  However, the master
roadmap reserves "Phase 8" for a different deliverable: Sundance
dress rehearsal (full simulated event, all 4 roles, 2-3 days work).

This is a naming collision, not a missed milestone.  The Slesh work
itself is real and valuable — it was the integration of Slesh POS
data into the reconciliation report with honest signaling.  Proper
re-attachment will happen in Session 2 (doc reconciliation).

Proposed renaming:
  Our docs "Phase 8" -> "Slesh-Reconciliation Workstream"
  (or similar non-numbered label, since the master roadmap owns
  the phase numbers)

────────────────────────────────────────────────────────────

## 4. Red flags from first read of roadmap (lines 1-80)

RED FLAG 1: Status pointer in master roadmap is 11 days stale
  Claim:  "Phase 1 — Not started, recon complete (2026-05-06)"
  Reality: Phases 1-7 done per memory + Slesh work shipped
  Impact: anyone reading the master doc cold gets the wrong state
  Severity: HIGH for new collaborators (Reza, future hires).
  Severity: LOW for Hesam (knows reality).
  Fix scope: update the Status Pointer to current state.

RED FLAG 2: Phase 8 naming collision (described above in section 3).

RED FLAG 3: 8 UX criteria + 5 phase criteria never explicitly referenced
  Master roadmap defines 8 UX criteria + 5 phase criteria that
  every phase must meet before merge.
  Our recent commits + closure docs do not explicitly reference
  passage of these criteria.
  Impact: phases claimed "DONE" may not have passed every criterion.
  Severity: HIGH if any criterion was silently skipped (e.g., test
  coverage, keyboard navigation, role-correctness).
  Fix scope: re-audit each phase against the 13 criteria in
  Session 1 deep-read.

RED FLAG 4: Test suite status unknown
  Phase rule requires "all existing tests still pass".
  Closure docs claim "no tests broken" without showing test runs.
  Impact: if a test suite exists and we're not running it,
  the bar is being silently lowered.
  If no test suite exists, the phase rule is being structurally
  violated.
  Severity: HIGH.
  Fix scope: run `pytest` and `npm test` and record results.

RED FLAG 5: Branch hygiene rule violated
  Master roadmap says "one feature branch per phase, squash-merge".
  Practice has been direct commits to develop.
  Impact: low for solo work, but indicates discipline drift.
  Severity: LOW operationally.
  Severity: MEDIUM if it signals other rule drift.

────────────────────────────────────────────────────────────

## 5. Deferred items inventory (consolidated)

Five disconnected sources held deferred-item records before this audit:
master-roadmap Appendix A, per-phase body "Deferred" sections, "(deferred
item)" tags inside phase definitions, the phase8-closure.md sections 4-6,
and userMemories.  RF30 identified this and recommended consolidation.

The list below is the single authoritative deferred-items inventory.
Each item carries a class label (A-E) showing source, a disposition
recommendation (pre-Sundance / post-Sundance / won't-ship), and a cross-
reference to relevant red flags.

### Class A — Explicit post-Sundance deferrals (master roadmap Appendix A)

  A1.  Visual theme redesign
       Source: master roadmap Appendix A line 1
       Disposition: POST-SUNDANCE  (intentional; works for MVP)
       
  A2.  Token rotation policy with Slesh
       Source: master roadmap Appendix A line 2
       Disposition: POST-SUNDANCE  (operational, not code; calendar
                                    reminder for week-after Sundance)
       
  A3.  Multi-tenant scaling (cache + cursor logic for tenant isolation)
       Source: master roadmap Appendix A line 3
       Disposition: POST-SUNDANCE  (only matters when adding 2nd tenant)
       
  A4.  Event P&L preview
       Source: master roadmap Appendix A line 4
       Disposition: POST-SUNDANCE  (blocked by wholesale cost data
                                    Hesam does not have yet)
       
  A5.  Briefing Sheet preview
       Source: master roadmap Appendix A line 5
       Disposition: POST-SUNDANCE  (blocked by XHR staff-shift data)
       
  A6.  B6.7-B6.14 polling worker formal pytest tests
       Source: master roadmap Appendix A line 6
       Cross-ref: RF27 HIGH (test gap on Sundance-critical infra)
       Disposition: PRE-SUNDANCE smoke test (substitute for formal tests)
                    POST-SUNDANCE full pytest rebuild
       
  A7.  Async test infrastructure rebuild (asyncpg "another operation
       in progress" issue)
       Source: master roadmap Appendix A line 7
       Cross-ref: RF4 + RF8 (test infra debt)
       Disposition: POST-SUNDANCE  (production runs fine; tests only
                                    affected on async fixtures)
       
  A8.  ORM mapper init bug (User relationship in alerts/models.py
       breaks standalone scripts; production fine)
       Source: master roadmap Appendix A line 8
       Cross-ref: RF26 MEDIUM (Phase 9 recipe-seeding risk)
       Disposition: PRE-SUNDANCE  (likely needed when seeding recipes
                                   in Phase 9.1)
       
  A9.  Multi-language UI
       Source: master roadmap Appendix A line 9
       Disposition: POST-SUNDANCE  (UI stays English; reports already
                                    bilingual)

### Class B — Per-phase body deferred sections

  B1.  URL state for tabs (Catalog Products/Recipes, Alerts filter,
       Chat channel)
       Source: master roadmap line 686 (Phase 2 body Deferred section)
       Disposition: POST-SUNDANCE  (UX polish)
       
  B2.  Loading skeletons on F5 (all 11 pages)
       Source: master roadmap line 687
       Disposition: POST-SUNDANCE  (UX polish)
       
  B3.  Alerts "Warning" filter scope inconsistency
       Source: master roadmap line 688
       Disposition: PRE-SUNDANCE  (alerts are Sundance-critical;
                                   investigate may be small fix)
       
  B4.  Multiple "ships in v1.1" footnotes
       Source: master roadmap line 689
       Disposition: POST-SUNDANCE  (cleanup)
       
  B5.  "ACTIVE ALERTS 0 all clear" KPI mislabel
       Source: master roadmap line 716 (Phase 3 body polish-week)
       Disposition: PRE-SUNDANCE  (Manager-visible contradicts alerts;
                                   one-line copy fix)
       
  B6.  Self-DM channel "Manager Cocktail Bar <-> ..." (seed data hygiene)
       Source: master roadmap line 717
       Disposition: POST-SUNDANCE  (cosmetic seed data)
       
  B7.  Bottom-left sidebar swap-icon dev affordance still visible
       Source: master roadmap line 718
       Disposition: PRE-SUNDANCE  (dev affordance visible in prod;
                                   remove before Omar/event)
       
  B8.  "Active Alerts" KPI logic — Bartender recon confusion
       Source: master roadmap line 745 (Phase 4 body polish-week)
       Disposition: NO-FIX  (audit determined to be recon false positive)
       
  B9.  Alert text race (Mojito alert flickering between two adapter shapes)
       Source: master roadmap line 747 (Phase 4 body, flagged to Phase 7)
       Cross-ref: RF28 + RF31 (handoff lost; adapter inconsistency)
       Disposition: PRE-SUNDANCE  (Phase 7 was supposed to catch this;
                                   needs real fix as part of real
                                   Phase 7 cross-role bug hunt)
       
  B10. Settings copy "Reports are already bilingual" references a
       feature Warehouse Staff doesn't have
       Source: master roadmap line 775 (Phase 5 body; same bug in
                                        Phase 4 for Bartender)
       Disposition: PRE-SUNDANCE  (one-line fix; visible to non-Owner)
       
  B11. Allocations UI missing (backend POST /api/v1/warehouse/allocations
       exists; no UI; Owner-workflow workaround)
       Source: master roadmap line 776
       Cross-ref: RF29 MEDIUM (feature gap with workaround)
       Disposition: PRE-SUNDANCE IF dress rehearsal shows operational
                    friction with Owner-as-proxy.  Otherwise POST-SUNDANCE.
       
  B12. Login role picker offers all 4 roles for warehouse.keeper
       Source: master roadmap line 779
       Disposition: NO-FIX  (anti-enumeration design from Phase 1C.2,
                              working as designed)
       
  B13. Inconsistent role labels ("Warehouse" vs "Warehouse Staff")
       across topbar pill / sidebar pill / Settings
       Source: master roadmap line 780
       Disposition: PRE-SUNDANCE  (visible to client; cosmetic but visible)

### Class C — Phase-body "(deferred item)" tags in main definitions

  C1.  Detector #6 — Warehouse Discrepancy anomaly detector
       Source: master roadmap Phase 6.7 spec
       Cross-ref: RF14 + RF16 + RF35 HIGH (NEVER SHIPPED)
       Disposition: PRE-SUNDANCE IF time budget allows (compounds
                    Sundance value of scanner+alerts combo).
                    Otherwise POST-SUNDANCE.  Session 3 decides.
       
  C2.  Manager auto-join bar channel hook
       Source: master roadmap Phase 3.4 + userMemories
       Disposition: POST-SUNDANCE  (manual workaround; not blocking)
       
  C3.  PATCH /api/v1/bars/{id}/manager UI endpoint
       Source: master roadmap Phase 3.6 + userMemories
       Disposition: POST-SUNDANCE  (backend supports; no UI)
       
  C4.  Post-event report generator (Phase 2.10)
       Source: master roadmap Phase 2.10 spec
       Disposition: PRE-SUNDANCE  (post-Sundance retrospective needs
                                   this to deliver value to Omar)
       
  C5.  Anomaly detectors #3, #4, #5 (Phase 2.13)
       Source: master roadmap Phase 2.13 spec
       Disposition: NEED INVESTIGATION  (status unverified by audit;
                                          Session 3 must verify and
                                          decide)
       
  C6.  Settings — change password etc (Phase 2.12 — ship status
       unverified)
       Source: master roadmap Phase 2.12 spec
       Disposition: NEED INVESTIGATION
       
  C7.  Phase 6.14 physical-device dress rehearsal (vs the docs-only
       checklist that shipped at commit 63a4b2f)
       Source: master roadmap Phase 6.14 spec
       Cross-ref: RF19 HIGH (Sundance reliability gap)
       Disposition: PRE-SUNDANCE  (physical device test on real
                                   hardware before Sundance day)

### Class D — Phase-closure doc deferrals (phase8-closure.md sections 4-6)

  D1.  Recipe seeding from Slesh historical catalog
       Source: phase8-closure.md
       Disposition: PRE-SUNDANCE  (Phase 9.1 prerequisite; needs Omar
                                   to confirm 2026 menu structure)
       
  D2.  Whitespace dedup in product names
       Source: phase8-closure.md
       Disposition: POST-SUNDANCE  (cosmetic data hygiene)
       
  D3.  Brand-specific ingredient products (e.g. Belvedere Vodka vs
       generic Vodka)
       Source: phase8-closure.md
       Disposition: POST-SUNDANCE  (recipes Phase 9 may need this;
                                    deferred from initial recipe set)
       
  D4.  S8 admin slesh-poll-state endpoint
       Source: phase8-closure.md (Phase 8 closure deferral, our Slesh
                                   workstream)
       Disposition: PRE-SUNDANCE  (admin observability for live event)
       
  D5.  GENERIC_MENU_NAMES proper categorization (currently set as
       Phase 9 dependency hook)
       Source: phase8-closure.md
       Disposition: PRE-SUNDANCE  (Phase 9 prerequisite)

### Class E — userMemories deferrals

  E1.  Open weather integration (Open-Meteo API)
       Source: userMemories: "identified as mandatory ML feature per Omar"
       Disposition: PRE-SUNDANCE  (Phase 9 ML feature engineering input;
                                   may also reveal Sundance-day forecast
                                   for ops planning)
       
  E2.  Rate limiting (slowapi previously attempted, rolled back)
       Source: userMemories: "Rate limiting (slowapi) was attempted and
                              rolled back"
       Disposition: POST-SUNDANCE  (production hardening; not Sundance-
                                    blocking; previous attempt broke
                                    chat send)

### Inventory summary

Total items: 32 across five classes.  Counts by disposition:

  PRE-SUNDANCE          (16 items)
  POST-SUNDANCE         (12 items)
  NO-FIX (working as designed)   ( 2 items)
  NEED INVESTIGATION    ( 2 items)

PRE-SUNDANCE items by sub-category:
  Visible to client / Sundance-day operations:  B5, B7, B10, B11, B13,
                                                D4, C7
  Phase 9 prerequisites (Omar-gated):           A8, D1, D5, E1
  Sundance-critical feature gaps:               B3, B9, C4, C1 (if budget)
  Test infrastructure:                          A6

These 16 items, plus the 4 phase-level workstreams (RF33 auth, RF37
real Phase 7, RF21 Phase 8 dress rehearsal, Phase 9 ML), constitute
the audit's must-ship recommendation for pre-Sundance work.  Session 3
sequences them by priority and time-budget against the 32-day window.

### Next action

Session 3 gap triage will:
  - Verify NEED INVESTIGATION items (C5 anomaly detectors #3/4/5,
    C6 Settings ship status)
  - Confirm or revise each disposition
  - Sequence PRE-SUNDANCE items by dependency + impact
  - Produce docs/pre-sundance-must-ship.md as the executable plan
  - Produce docs/post-sundance-backlog.md for everything else

────────────────────────────────────────────────────────────

## 6. Known issues inventory

  Codebase TODO/FIXME comments (Layer 3 grep, 2026-05-18):
    Backend:  7 occurrences
    Frontend: 3 occurrences
    Total:    10 across whole codebase
  
  Healthy debt level for a 6-week-old project with 193 commits.
  Triage pass deferred to Session 3 — each TODO inspected for
  Sundance-criticality.
  
  Phase 7 known-issues.md (required by master roadmap Phase 7
  done-criterion): DOES NOT EXIST.  Confirms RF20, corroborates
  RF37 + RF38.
  
  Real Phase 7 cross-role bug hunt (RF37) will produce this file
  as one of its deliverables.

## 7. Days-remaining math
## 8. Open questions requiring decisions

[ All sections below to be filled in as audit progresses ]

────────────────────────────────────────────────────────────

## Appendix A — Audit progress log

  2026-05-17  Audit started.
  2026-05-17  First read: master roadmap lines 1-80.  5 red flags
              recorded.  Audit doc created.
  2026-05-17  Second read: master roadmap lines 80-180 (Phase 0 +
              Phase 1A/B/C).  4 new red flags recorded (RF6-RF9).
              Phase 1D status pending chunk 3.
  2026-05-17  Third read: master roadmap lines 180-280 (Phase 1D +
              Phase 2 audit checklist + sub-steps 2.1-2.8).  3 new
              red flags recorded (RF10-RF12).  RF10 is highest-
              priority: doc internally contradicts itself on
              Phase 2 status.  RF11 confirms Phase 1D has no
              completion marker (critical schema migration
              status unclear).
  2026-05-17  Fourth read: master roadmap lines 280-380 (Phase 2
              remaining sub-steps 2.9-2.14 + Phase 3 full + Phase
              4.1).  3 new red flags recorded (RF13-RF15).
              Initial deferred-items inventory captured (14 items;
              expect more from chunks 5-9).  Pattern emerging:
              "done" phases hide significant unfinished work
              tagged as "deferred item" in body.
  2026-05-17  Fifth read: master roadmap lines 380-480 (Phase 4
              remaining + Phase 5 full + Phase 6 sub-steps 6.1-6.8).
              4 new red flags recorded (RF16-RF19).  RF16 resolves
              the Phase 2.13 -> Phase 6.7 detector cross-reference.
              RF17 confirms Phase 6 status drift (header says ⏸,
              memory says shipped).  RF18 + RF19 are HIGH severity
              Sundance reliability items: offline-queue verification
              + device-testing schedule.
  2026-05-17  Sixth read: master roadmap lines 480-580 (Phase 7
              full + Phase 8 full = real dress rehearsal + Phase
              9.1 start).  4 new red flags recorded (RF20-RF23).
              RF21 is CRITICAL severity — first item at that level.
              Real Phase 8 is the Sundance go/no-go dress rehearsal
              and it's unstarted with 33 days to event.  Severity
              tier "CRITICAL" added to inventory.  Phase 7 has
              specific done-criterion (zero S1/S2 + known-issues.md)
              that needs verification.
  2026-05-17  Seventh read: master roadmap lines 580-680 (Phase 9
              sub-steps + Appendix A + Appendix B + start of body-
              section overrides).  4 new red flags recorded
              (RF24-RF27).  Major discovery: Appendix A contains
              the EXPLICITLY-pushed deferred items list (9 items).
              But Class 2 items (tagged "(deferred item)" in phase
              bodies) are NOT in Appendix A.  Two disconnected
              lists exist.  Also: Phase 2 has dual sub-step systems
              (14 sub-steps in main def vs 4 batches in body audit)
              that are not cross-referenced.  RF26 flags the ORM
              mapper bug as a risk for Phase 9 recipe seeding.
  2026-05-17  Eighth read: master roadmap lines 680-792 (full body
              audits for Phase 3, 4, 5).  4 new red flags recorded
              (RF28-RF31).  POSITIVE FINDING: per-role audits were
              rigorous (batches E/F/G/H with explicit bug fixes
              shipped same day).  RF30 supersedes RF15+RF24 with
              the full count: 22+ deferred items across 4 lists.
              RF28 flags need to verify phase-to-phase handoffs
              actually landed (Phase 4 -> Phase 7 alert text race).
              Master roadmap fully read.  Layer 1 (documented
              state) audit complete.
  2026-05-18  Layer 1 commit landed (023b9e5).  715 lines preserved
              before any Layer 2 risk.
  2026-05-18  Layer 2 begun.  git log analysis revealed May 8
              zero-commit anomaly.  Per-day commit-density check
              identified Phase 3/4/5 fixes as actually-May-9.
  2026-05-18  May 7-9 window verification: RF32 RESOLVED — fixes
              are in repo with one-day audit/commit timing offset.
              LANDMARK finding RF33 discovered: Phase 1D NEVER
              HAPPENED.  Tactical Layer 3 dip confirmed:
                - users.role column still exists
                - 20/20 legacy call sites unmigrated
                - 0 uses of get_active_role helper anywhere
              Severity escalated to CRITICAL.  Phase 1 incomplete
              by its own definition; auth system in dual state.
              RF11 superseded by RF33's evidence-backed version.
              Phase-to-commit mapping table added as Appendix E.

────────────────────────────────────────────────────────────

## Appendix B — Red flags continued (from chunk 2)

RED FLAG 6: Checkbox-DONE mismatch across Phase 1 sub-phases
  Pattern: sub-phase header says "✅ DONE 2026-05-07" but every
  task checkbox below is "[ ]" (unchecked).
  Observed in: Phase 1A (6 checkboxes), Phase 1B (7 checkboxes),
  Phase 1C (in progress; first 7 visible all unchecked).
  Impact: cannot determine from the doc which specific tasks
  within a sub-phase were completed vs skipped.  Onboarding +
  audit slowed.
  Severity: MEDIUM.
  Fix scope: in Session 2 doc reconciliation, sweep sub-phases
  marked DONE and either check the boxes (if task ran) or strike
  them out (if task was deferred).

RED FLAG 7: Empty completion records
  Every sub-phase has placeholder "Completion record:
  [done] YYYY-MM-DD — commit ________" that was never filled in.
  Impact: cannot verify the commit hash that closed each
  sub-phase without searching git log.
  Severity: MEDIUM.
  Fix scope: Session 2 fills in actual commit hash + date per
  sub-phase.  This becomes a 30-min task once we have the
  reconciled mapping.

RED FLAG 8: Test-infrastructure debt formally documented + unresolved
  Phase 1A note states: "DB-write tests inside the test process
  hit a known asyncpg/pytest-asyncio interaction.  1A coverage
  is achieved through functional smoke tests."
  Plus: "the async-test-infra rebuild stays in Appendix A as
  its own future phase."
  Impact: the "all existing tests still pass" rule from the
  Phase Standard is structurally not enforceable.  Each phase
  compounds the gap silently.
  Severity: HIGH.  This is the substantive form of Red Flag 4.
  Confirmed in writing that test debt is known and accepted.
  Fix scope: needs decision in Session 3:
    Option A: rebuild async-test-infra before Sundance (estimate?)
    Option B: accept the debt formally, document mitigations
              (smoke tests as substitute), set post-Sundance
              priority.
  My read: Option B is what's already happening; document it
  honestly + ensure smoke tests cover critical paths.

RED FLAG 9: Phase 1D status not visible yet
  1A/B/C confirmed DONE.  1D (call-site migration of 20 reads
  of current_user.role) not seen in chunk 2.
  Pending: chunk 3 read to confirm 1D status.
  RESOLUTION (chunk 3): 1D header has NO ✅ marker.  Body shows
  12 unchecked sub-tasks (1D.1-1D.12).  Completion record blank.
  Pending further: doc may say "1D ✅ COMPLETE" later in body.
  Code-audit grep needed to verify actual call-site state.

RED FLAG 10: Phase 2 doc-internal contradiction
  Header (line ~224):  "# Phase 2 — Owner Experience ⏸"
  Body (line ~644):    "## Phase 2 — Owner experience audit
                        ✅ COMPLETE 2026-05-07"
  Both statements are in the same document.
  Hypothesis: the May 7 audit COMPLETED in audit form (findings
  documented in body section), but the actual FIX WORK (Page C
  wiring, Inventory wiring, Warehouse wiring) may or may not
  have shipped after the audit.
  Severity: HIGH.  Reading the doc top-down vs bottom-up gives
  different answers about Phase 2 status.  Equally bad for
  collaborators + future audits.
  Fix scope: chunk 7-8 will reveal the body section.  Then
  code-audit needed to determine which sub-steps shipped.

RED FLAG 11: Phase 1D critical sub-tasks unchecked
  Includes:
    1D.10  drop users.role column (schema change)
    1D.11  final manual browser test all 4 roles
    1D.12  commit + PR + squash-merge to develop
  All unchecked.  Header has no ✅.  No completion record.
  Severity: HIGH if any of the 20 call sites remains unmigrated
  (causes inconsistent role-reading: legacy users.role vs new
  active_role JWT claim).
  Fix scope: code-audit grep:
    grep -rn "current_user.role" app/ --include="*.py"
    grep -rn "get_active_role" app/ --include="*.py"
  Compare counts; verify all sites use the helper.

RED FLAG 12: Phase 2 sub-step inventory incomplete (read in progress)
  Owner sidebar has 11 items.  Sub-steps visible through chunk 3:
  2.1 Dashboard, 2.2 Events list+detail, 2.3 Events Page C,
  2.4 Bars, 2.5 Catalog, 2.6 Inventory, 2.7 Alerts, 2.8 Warehouse.
  Remaining pages not yet seen: Predictions, Reports, Chat,
  Settings.
  RESOLUTION (chunk 4): remaining sub-steps located.
  2.9 Predictions, 2.10 Reports, 2.11 Chat, 2.12 Settings,
  2.13 Anomaly detectors #3-#5, 2.14 Tests + commit.
  Full Phase 2 inventory: 14 sub-steps (2.1 through 2.14).

RED FLAG 13: "Done" phases contain unchecked deferred items
  Pattern: a phase marked ✅ COMPLETE in the body contains
  sub-steps explicitly tagged "(deferred item)" in the same phase.
  
  Confirmed instances:
    Phase 2.10  Reports — "Implement post-event report
                generator (deferred item)" — bilingual PDF
                with alert ledger + burn-rate history + revenue
                summary.  Substantive feature, not housekeeping.
    Phase 3.4   Chat — "Auto-join hook (deferred item): when
                a Manager is assigned to a bar, they auto-join
                that bar's channel."
    Phase 3.6   "PATCH /bars/{id}/manager UI (deferred item) —
                Owner-side UI to assign/reassign managers to
                bars."
  
  Likely more below in chunks 5-9.
  Severity: HIGH.  This is the substantive form of RF10.  A
  phase saying "DONE" while containing tasks marked "deferred
  item" is the worst possible audit state — looks complete,
  isn't.
  Fix scope: Session 2 doc reconciliation must distinguish
  "phase audit done" from "phase fix work done" in every
  ⏸/✅ marker.  Probably needs a third status: ⚠️ PARTIAL.

RED FLAG 14: Anomaly detector #6 may be unblockable
  Doc text: "Detector #6 — Warehouse Discrepancy — defer;
             needs barcode hardware".
  But Phase 6 (Scanner subsystem) shipped per memory.  Barcode
  hardware now exists.  Detector #6's reason for deferral is
  no longer valid.
  Severity: MEDIUM.  Recoverable opportunity if Sundance budget
  allows.
  Fix scope: Session 3 gap triage decides ship-before / ship-
  after / won't-ship for Detector #6.

RED FLAG 15: No consolidated deferred-items list
  Multiple "deferred items" referenced in passing across the
  roadmap.  userMemories has a partial list.  Closure docs have
  partial lists.  NO consolidated source-of-truth exists.
  
  Initial inventory (will populate section 5 of this audit doc):
    - post-event report generator (Phase 2.10)
    - Detector #6 Warehouse Discrepancy (Phase 2.13 — now
      potentially unblockable per RF14)
    - Manager auto-join-bar-channel hook (Phase 3.4)
    - PATCH /bars/{id}/manager UI (Phase 3.6)
    - WebSocket deferred for some features (per userMemories)
    - Alerts frontend WebSocket kept with 10s polling backup
      (per userMemories)
    - Option B overlay DM design (per userMemories)
    - Phase 6.14 physical-device dress rehearsal (per memory)
    - Recipe seeding for 8 generic menu items (per phase8-closure.md)
    - Whitespace dedup for 13 product names (per phase8-closure.md)
    - ML Model A demand forecasting (Phase 9)
    - Brand-specific ingredient products (per phase8-closure.md)
    - S8 admin slesh-poll-state endpoint (per phase8-closure.md)
    - Detector #6 Warehouse Discrepancy (above)
  
  More will surface in chunks 5-9.  Final list goes into section 5.
  Severity: HIGH.  Without one list, items get rediscovered
  randomly during real Sundance pressure.
  Fix scope: section 5 of THIS audit doc becomes the
  consolidated list.

RED FLAG 16: Detector #6 cross-reference (resolves part of RF14)
  Chunk 4 noted: "Detector #6 — Warehouse Discrepancy — defer;
                  needs barcode hardware" (Phase 2.13)
  Chunk 5 reveals: Phase 6.7 IS Detector #6 — "Now possible
                   because scans are happening"
  This is consistent: Phase 2's "defer" pointed forward to
  Phase 6.7 where the work is properly scoped.
  Severity: LOW (resolved internal pointer).
  Fix scope: Session 2 doc reconciliation should add an
  explicit cross-reference "Phase 2.13 -> Phase 6.7" so
  readers don't think the detector was dropped.
  Still need: code-grep to confirm 6.7 actually shipped as
  part of the 21 scanner commits.

RED FLAG 17: Phase 6 header status doesn't match shipped reality
  Doc header (line ~434):  "# Phase 6 — Camera Scanner System ⏸"
  Memory:                  "Phase 6 (Scanner subsystem) — 21
                            commits, COMPLETE"
  Closure doc exists:      docs/scanner-architecture.md (19 KB)
  
  Same drift pattern as Phase 2 (RF10) but here it's the master
  roadmap not catching up to shipped code.  Body sections of the
  roadmap may or may not have ✅ markers for Phase 6.
  Severity: HIGH for new collaborators.  Reza or future hire
  reading the master roadmap top-down would conclude scanner
  isn't built.
  Fix scope: Session 2 doc reconciliation flips Phase 6 header
  to ✅ with commit hash + date.

RED FLAG 18: Phase 6.6 "offline queue" reliability — verify ship
  Sub-step text: "If backend unreachable, queue scans in
                  localStorage.  On reconnect, drain queue
                  with idempotent re-submission."
  Critical Sundance reliability feature: network may be flaky
  at the venue.  Without offline queue, scans during network
  drop are silently lost = inventory ground-truth corruption.
  Severity: HIGH.  If 6.6 didn't ship, Sundance has a real
  reliability gap.
  Fix scope: code-grep verification:
    grep -rn "offline\|localStorage" frontend/src/features/scan/
    or similar.
  If shipped: confirm in audit + cross-reference commit.
  If NOT shipped: this becomes a P0 pre-Sundance item.

RED FLAG 19: Phase 6.8 device-testing discipline deferred
  Sub-step text: "Browser test on real iOS / Android devices".
  Per memory + userMemories: "Phase 6.14 physical-device dress
  rehearsal" is DEFERRED.
  So Phase 6 may be "code complete" but not "device-tested
  complete".
  Severity: HIGH for Sundance reliability.  A scanner working
  in desktop Chrome ≠ working in iPhone Safari at the venue
  under operational stress.
  Fix scope: schedule docs/scanner-dress-rehearsal-checklist.md
  as a P0 pre-Sundance blocker.  Time estimate per the doc:
  ~30 minutes once you have phone + bottles.  Low-cost,
  high-value test.

RED FLAG 20: Phase 7 "zero S1/S2 bugs" claim needs verification
  Memory says: "Phase 7 — 4 commits, COMPLETE".
  Doc requires: "Phase 7 done when: zero S1 bugs, zero S2 bugs,
                 S3/S4 documented in docs/known-issues.md".
  
  Initial docs/ ls in chunk 1 did not show docs/known-issues.md.
  Two implications:
    A) If known-issues.md is missing, Phase 7 done-criterion is
       structurally unmet.  Either all bugs were genuinely fixed
       (best case) or phase was declared done without documenting
       remaining bugs (bad case — bugs lost).
    B) Without the doc, cannot tell which case applies.
  
  Severity: HIGH.
  Fix scope:
    1) ls docs/known-issues.md — confirm existence
    2) If missing: reconstruct from the 4 Phase 7 commit messages
    3) Session 2 then writes the doc properly

RED FLAG 21: Real Phase 8 = Sundance Dress Rehearsal (CRITICAL)
  Doc header (line ~524): "# Phase 8 — Sundance Dress Rehearsal ⏸"
  Doc verbatim quote: "This is the Sundance go/no-go."
  Sub-steps include:
    8.1  Setup realistic test event
    8.2  Multi-role concurrent test (4 windows, 30-min simulation)
    8.3  Failure modes (4 categories)
    8.4  Performance (3 specific criteria)
    8.5  Fix issues, retest
  
  Doc-stated time: ~2-3 days.
  Days remaining to Sundance: 33.
  Actual Phase 8 = UNSTARTED.
  Our Slesh integration work was MIS-LABELED Phase 8 in our
  internal closure docs (already captured as RF2).
  
  Severity: CRITICAL.  Highest yet.  This is THE most important
  remaining pre-Sundance work.  Skipping it = gambling on
  Sundance day.
  Fix scope: Session 3 must reserve at least 3-5 working days
  for actual Phase 8 dress rehearsal.  Best scheduled ~2 weeks
  before Sundance (early June 2026) so discovered S1/S2 bugs
  have time to fix.

RED FLAG 22: Phase 8.4 performance criteria specific + unverified
  Doc requires:
    A) Dashboard loads in <3 seconds
    B) WebSocket reconnects in <5 seconds
    C) No memory leaks after 30 minutes
  
  None of these measured anywhere in this audit so far.
  Severity: HIGH.  Objective, testable criteria.  Current state
  may fail any/all of them silently.
  Fix scope: Phase 8 dress rehearsal will measure these.  A
  pre-rehearsal smoke check is also possible NOW: time dashboard
  load with browser DevTools; watch DevTools memory profiler
  for 30 minutes.

RED FLAG 23: Phase 8.3 failure modes likely untested
  Doc lists 4 failure modes to verify:
    A) Backend goes down mid-event — graceful degradation
    B) Network slow — UI still responsive
    C) One role's session expires — modal works, others unaffected
    D) Two managers post chat simultaneously — no message loss
  
  (A), (B), (D) — never tested in any audit history seen so far.
  (C) — partially tested (Phase 1C ships session expiry modal,
       but "modal works AND others unaffected" not validated).
  
  Severity: HIGH.  Most common Sundance-day failure modes:
  bartender's phone loses signal for 30 seconds — does system
  recover gracefully or duplicate scans?  Backend hiccups —
  does the UI freeze or show a meaningful state?
  Fix scope: Phase 8 dress rehearsal will catch these.
  Failure-mode-specific tests should also be scripted into the
  pre-event smoke test.

RED FLAG 24: Appendix A is the partial deferred-items list (RF15 update)
  Appendix A in the master roadmap captures 9 EXPLICITLY-PUSHED
  items.  It does NOT capture items tagged "(deferred item)" in
  phase bodies.
  
  CLASS 1 items (Appendix A, intentional):
    Visual theme redesign
    Token rotation policy
    Multi-tenant scaling
    Event P&L preview
    Briefing Sheet preview
    B6.7-B6.14 polling worker pytest tests
    Async test infrastructure rebuild
    ORM mapper init bug (alerts/models.py User relationship)
    Multi-language UI
  
  CLASS 2 items (phase-body tags + scattered, incidental):
    Post-event report generator (Phase 2.10)
    Manager auto-join hook (Phase 3.4)
    PATCH /bars/{id}/manager UI (Phase 3.6)
    Phase 6.14 physical-device dress rehearsal (per memory)
    Recipe seeding (per phase8-closure.md)
    Whitespace dedup (per phase8-closure.md)
    Brand-specific ingredient products (per phase8-closure.md)
    S8 admin slesh-poll-state endpoint (per phase8-closure.md)
    Detector #6 Warehouse Discrepancy (cross-ref RF16)
    Open weather integration (per userMemories: "identified as
                              mandatory ML feature")
    Anomaly detectors #3, #4, #5 (Phase 2.13 - status unknown)
  
  Severity: HIGH.  Two disconnected lists mean any consolidated
  view requires manual merge.
  Fix scope: Session 2 reconciliation produces ONE authoritative
  deferred-items list.  Each item gets:
    - Status (deferred-intentional / deferred-incidental /
              actually-shipped-but-unmarked)
    - Pre-Sundance / Post-Sundance disposition
    - Owner of the decision

RED FLAG 25: Phase 2 has dual sub-step systems
  Main definition (lines 224-280): 14 sub-steps (2.1-2.14).
  Body audit (lines 644-680): 4 batches (A, B, C, D).
  No cross-reference between them.
  
  Hypothesis: the May 7 audit DISCOVERED items and TRIAGED them
  into batches.  Original sub-step list was the "planned scope";
  batch list was the "discovered-and-shipped scope".
  
  Verification questions:
    - Did 2.10 (Reports / post-event report generator) ship?
      Batches A/B/C/D don't appear to mention it.  Likely DEFERRED.
    - Did 2.13 (Anomaly detectors #3, #4, #5) ship?
      Not in batches.  Likely DEFERRED.
    - Did 2.6 (Inventory wiring) ship?
      Batch B "Inventory rewrite" confirms YES.
    - Did 2.12 (Settings — change password etc) ship?
      Not in batches.  Likely DEFERRED.
  
  Severity: HIGH.  Without explicit mapping, can't tell which
  Phase 2 sub-steps shipped vs deferred.  Same pattern may
  exist in Phase 3, 4, 5.
  Fix scope: Session 2 reconciliation produces explicit mapping
  per phase: each sub-step → ship status → commit hash or
  deferred-disposition.

RED FLAG 26: ORM mapper init bug — affects standalone scripts
  Appendix A item: "ORM mapper init bug — User relationship in
  alerts/models.py breaks standalone scripts; production fine"
  
  "Production fine" but "standalone scripts" break.  Operational
  scripts we depend on (categorize_slesh_products.py, future
  seed scripts, debugging) may break.
  
  In Phase 8 we ran several standalone scripts.  Did we hit
  this bug or work around it?  If we worked around it (e.g.
  via importlib.reload tricks), the workaround pattern is
  itself technical debt.
  
  userMemories says: "importlib.reload() on SQLAlchemy models
  causes 'Table already defined' — use fresh subprocess instead."
  This may BE the workaround.
  
  Severity: MEDIUM.  Hidden landmine for any future ops/seed
  scripts.  Affects Phase 9 recipe seeding script directly.
  Fix scope: Session 2 catalogs which scripts hit it + the
  workaround pattern.  May warrant fix-before-Phase-9 since
  recipe seeding is a standalone-script task.

RED FLAG 27: B6.7-B6.14 polling worker tests deferred = test gap
  Appendix A item: "B6.7-B6.14 polling worker formal pytest tests
  — functionality verified manually with real data"
  
  Polling worker (Slesh order ingestion) is critical Sundance
  infrastructure.  No automated tests means:
    - Any change carries high regression risk
    - No CI ability to catch regressions
    - "Manual verification with real data" only works while a
      real-data scenario exists
  
  This feeds the variance signal we just shipped in Phase 8.
  
  Severity: HIGH for Sundance reliability.
  Fix scope: Session 3 gap triage decides:
    Option A: Defer formally (current state).  Mitigation: pre-
              Sundance smoke test exercises worker against real
              data.
    Option B: Build smoke test as substitute for pytest tests
              (~half day work).  High Sundance ROI.

RED FLAG 28: Phase-to-phase handoffs need cross-verification
  Phase 4 body audit flagged: "Alert text race (Mojito alert
  flickering between two copies) — flagged for Phase 7 cross-role
  bug-hunt."
  Phase 7 is marked DONE per memory (4 commits).
  Question: did Phase 7 actually fix this race, or did the
  Phase 4 -> Phase 7 handoff get lost?
  
  Same pattern may exist elsewhere: any phase audit that says
  "flagged for Phase X" creates a handoff that needs verification.
  
  Severity: HIGH.  Lost handoffs = bugs that everyone thinks
  someone else fixed.
  Fix scope: Session 2 grep for "flagged for" / "deferred to
  Phase X" patterns + verify each handoff actually landed in
  the target phase.

RED FLAG 29: Warehouse Allocations UI missing (new feature gap)
  Phase 5 body audit: "Allocations UI: 'Active Allocations' KPI
  exists but no dedicated UI exists for warehouse staff to
  allocate stock to bars.  Backend is available (POST
  /api/v1/warehouse/allocations) — genuine missing feature,
  not a bug.  Not Sundance-blocking; allocation can happen via
  Owner workflow until built."
  
  Severity: MEDIUM.  Workaround exists (Owner does it).  But
  this is a Warehouse Staff workflow gap.
  Fix scope: Phase 8 dress rehearsal should test the Owner-as-
  proxy workaround.  If it adds operational friction, ship the
  Warehouse Allocations UI before Sundance.

RED FLAG 30: FOUR disconnected deferred-items lists (RF24 update)
  Now confirmed three locations + closure docs + userMemories
  contain deferred-items entries:
    1. Appendix A (9 items, explicit intentional)
    2. Per-phase "Deferred (post-Sundance)" sections in body
       (Phase 2: 4 items; Phase 3: 3 items; Phase 4: 2 items;
        Phase 5: 4 items)
    3. userMemories partial list
    4. closure docs partial lists (phase8-closure.md sections 4-6)
  
  PER-PHASE BODY DEFERRED ITEMS DISCOVERED:
    Phase 2 deferred:
      P2.1  URL state for tabs (Catalog Products/Recipes, Alerts
            filter, Chat channel)
      P2.2  Loading skeletons on F5 (all 11 pages)
      P2.3  Alerts "Warning" filter scope inconsistency
      P2.4  Multiple "ships in v1.1" footnotes
    Phase 3 deferred (polish-week):
      P3.1  "ACTIVE ALERTS 0 all clear" KPI mislabel
      P3.2  Self-DM channel "Manager Cocktail Bar <-> ..."
            (seed data hygiene)
      P3.3  Bottom-left sidebar swap-icon dev affordance still
            visible
    Phase 4 deferred:
      P4.1  Active Alerts KPI confusion (false positive, no fix)
      P4.2  Alert text race (FLAGGED FOR PHASE 7 — see RF28)
    Phase 5 deferred (polish-week):
      P5.1  Settings copy "Reports are already bilingual"
            references a feature Warehouse Staff doesn't have
      P5.2  Allocations UI missing (see RF29)
      P5.3  Login role picker offers all 4 roles for
            warehouse.keeper (anti-enumeration, working as
            designed)
      P5.4  Inconsistent role labels ("Warehouse" vs "Warehouse
            Staff") across topbar / sidebar / Settings
  
  TOTAL pre-Sundance items requiring decision: 13 phase-body
  items + 9 Appendix A items = 22+ items in scattered locations.
  
  Severity: HIGH.  Without consolidation, items will surface
  randomly during Sundance pressure.
  Fix scope: Session 2 produces ONE authoritative consolidated
  deferred-items list as section 5 of this audit doc.

RED FLAG 31: Alert text race may indicate broader adapter issue
  Phase 4 audit text: "Alert text race between two adapter
  shapes (Mojito alert flickering between two copies)".
  
  "Two adapter shapes" suggests TWO different alert data shapes
  being merged or compared.  This could be a deeper architecture
  issue, not just a UX bug.
  
  Severity: MEDIUM-HIGH if it indicates broader inconsistency.
  Fix scope: code-grep for alert adapters; verify race was
  actually fixed in Phase 7.  See also RF28.

────────────────────────────────────────────────────────────

## Appendix D — Layer 2 (Git) findings

### RF32 RESOLUTION: Phase 3/4/5 fixes are in the repo

Concern: master roadmap body sections claim Phase 3, 4, 5
✅ COMPLETE 2026-05-08 but git shows zero commits on 2026-05-08.

Resolution: git log shows the work shipped 2026-05-09:

  7ba09eb  Phase 3 complete — Manager
  2739450  Phase 3 Batch F — Inventory scoping
  508621e  Phase 3 Batch E — /reports route guard
  4cfa01d  Phase 4 complete — Bartender
  8b1f67b  Phase 4 Batch G — Bartender polish
  1f27ffb  Phase 5 complete — Warehouse Staff
  b9befea  Phase 5 Batch H — Warehouse Staff polish

Body section dates record AUDIT timestamp (Claude in Chrome
walk), not COMMIT timestamp.  Audit was performed May 8;
fixes committed May 9.  This is reasonable practice, not
drift worth alarming about.
Severity: LOW.  Body sections should ideally include both
audit-date AND commit-hash; Session 2 will add commit hashes.

────────────────────────────────────────────────────────────

RED FLAG 33: Phase 1D NEVER HAPPENED (LANDMARK finding)

This is the most consequential finding of the audit.
Severity: HIGH operationally; CRITICAL if conditions trigger.

Layer 1 evidence:
  Master roadmap defines Phase 1 as 4 sub-phases (1A/1B/1C/1D).
  Each has separate "Completion record" placeholder.
  1D scope is 12 sub-tasks: migrate 20 call sites, drop
  users.role column, browser test 4 roles, squash-merge.
  1A/1B/1C show "✅ DONE 2026-05-07" headers.
  1D shows NO completion marker (RF11).

Layer 2 evidence:
  Git log shows single commit 1a15439 (2026-05-07 17:53):
    "feat(auth): Phase 1 — multi-role login, two-step auth
                  UI, session-expiry modal"
  This single commit ships 1A + 1B + 1C in one shot.
  No subsequent Phase 1D commit appears anywhere.
  The expand/contract migration pattern (described in master
  roadmap as the entire rationale for splitting Phase 1)
  was abandoned in execution.

Layer 3 evidence (tactical Layer 3 dip):
  Query A: psql \d users
           Result: users.role column STILL EXISTS
                   (Phase 1D.10 drop-column not done)
  Query B: grep -c "current_user.role" app/**/*.py
           Result: 20 occurrences
                   (matches recon's 20 sites EXACTLY; zero
                   migrated)
  Query C: grep "current_user.role" with file:line
           Result: spans auth, bars, alerts, warehouse modules
                   - app/modules/auth/router.py:170
                   - app/modules/bars/router.py:152
                   - app/modules/alerts/router.py:88, 130, 166, 204
                   - app/modules/warehouse/router.py:82, 108,
                     130, 131
  Query D: grep -c "get_active_role" app/**/*.py
           Result: 0 uses
                   (helper from Phase 1B.4 EXISTS in spec but
                   is unused anywhere in the codebase)

System designer interpretation:

The auth system is in the EXPAND state of expand/contract
migration but never reached CONTRACT.  Two coexisting state
representations:
  OLD:  users.role column (single role per user, native enum)
  NEW:  user_roles join table (multi-role per user, backfilled
                                from users.role at 1A.2)

Read paths:
  - 20 call sites read users.role (OLD path) — production code
  - JWT carries active_role claim from Phase 1B.3 — middleware
  - Roles-for-email endpoint queries user_roles (NEW path)

Current state (today):
  user_roles + users.role are IN SYNC because the 1A.2 backfill
  populated user_roles from users.role and nothing has written
  EITHER since.  Login flow likely writes both.

Drift triggers (any one breaks the system):
  1. New feature writes to users.role without updating user_roles
  2. New feature writes to user_roles without updating users.role
  3. Manual SQL update by Hesam to either table
  4. New feature reads from user_roles assuming it's authoritative
  5. New feature reads from users.role assuming it's authoritative
  6. Developer (Reza) adds code calling get_active_role()
     and tests pass because no other code uses it, but then
     inconsistency emerges later
  7. Any future role-add or role-revoke endpoint (1B.6 exists
     in spec; not verified in code)

Sundance risk:
  LOW immediately — current state is stable
  MEDIUM during Phase 9 development if new features touch roles
  HIGH if any of trigger 1-7 fires before Sundance

Fix scope (post-audit):
  Option A: Complete Phase 1D properly before any new feature work
            Estimated time: 1-2 days
            Risk profile: surgical, well-spec'd, all 20 sites known
            Sundance impact: removes drift risk entirely
  Option B: Defer formally and document the dual state
            Add CI guard: prevent any new code from reading
            current_user.role; force all new code through helper
            Estimated time: half-day
            Risk profile: lower effort but technical-debt grows
  Option C: Hybrid - ship the helper, migrate the 4 highest-traffic
            call sites (alerts), defer the rest
            Estimated time: half-day
            Risk profile: medium

System-designer recommendation: Option A.
Reasoning:
  - 1-2 days is fast for "complete a migration"
  - The migration is well-defined; recon already done
  - Doing it now eliminates 7 distinct drift triggers
  - Doing it before Phase 9 means Phase 9 builds on stable auth
  - Sundance pre-event smoke test then exercises the unified
    code path

────────────────────────────────────────────────────────────

RED FLAG 34 RESOLVED POSITIVE: Phase 6.4 IS the offline queue
  RF18 raised concern that offline-queue ship status was unverified.
  Resolution: commit 45df782 (2026-05-10): "feat(scanner): Phase 6.4
  — frontend UUID + offline queue".  Master roadmap labeled it 6.6;
  execution renumbered to 6.4.  Offline queue exists in code.
  Severity: RESOLVED POSITIVE.
  Pending Layer 3: grep localStorage in frontend/src/features/scan/
  to confirm drain-on-reconnect + idempotent re-submission.

────────────────────────────────────────────────────────────

RED FLAG 35: Detector #6 (Warehouse Discrepancy) NEVER SHIPPED
  Master roadmap Phase 6.7 spec: "Anomaly detector #6 — Warehouse
  Discrepancy.  Compare requested-quantity vs scanned-quantity per
  restock.  Register in AlertsOrchestrator."
  
  Actual commit Phase 6.7 (40a82f9, 2026-05-11): "BarScanEmptiesPage
  (Bartender Mode C)".  COMPLETELY DIFFERENT WORK.  Phase 6.7 number
  reused for a Bartender page; the anomaly detector was not built.
  
  Cross-references:
    RF14 anticipated this might now be unblocked
    userMemories mentions only "Demand Spike detector"
    No commit grep matches "WarehouseDiscrepancy" pattern
  
  Severity: HIGH.  Anomaly detection was a stated Phase 6 deliverable.
  Fix scope: Layer 3 verification + Session 3 ship-before/after/no
  decision.

────────────────────────────────────────────────────────────

RED FLAG 36: Phase 6.11-6.12.4 is reconciliation work, not scanner
  Master roadmap Phase 6 = "Camera Scanner System" with 8 sub-steps.
  Actual Phase 6 extended through 6.14 including reconciliation
  feature work:
    6.11    reconciliation-report endpoint
    6.12.1  useReconciliationReport TanStack hook
    6.12.2  EventReconciliationPage viewer
    6.12.3  wire reconciliation route + button
    6.12.4  three-role browser verification
  
  These commits ARE in the repo; feature works.  Scope drifted without
  roadmap update.  Same pattern as RF2 and RF35.
  
  Severity: MEDIUM (doc/scope drift; not functional).
  Fix scope: Session 2 reconciles master roadmap with actual structure.

────────────────────────────────────────────────────────────

RED FLAG 37: Phase 7 was renumbered + scope-shrunk dramatically
  Master roadmap Phase 7 = "Cross-Role Bug Hunt" with 11 sub-steps
  (role walkthroughs, S1/S2 fixes, known-issues.md).
  
  Actual Phase 7 commits (4 total, all May 11 evening):
    7.1  add XProject favicon (1c3fcfc) — cosmetic
    7.2  React Router v7 future flags (2f15af6) — warning suppression
    7.3  reposition PermissionDeniedToast (3ab69e9) — UI position
    7.4  remove unused TypeScript import (d15c3bc) — code hygiene
  
  The 4 commits are SMALL UI FIXES that REUSED Phase 7 numbering.
  They DO NOT match the spec.  No walkthroughs, no severity-categorized
  bug list, no S1/S2 bug fixes, no docs/known-issues.md (verifies RF20).
  
  Severity: HIGH.  Phase 7 is STRUCTURALLY UNDONE.  Cross-role bug
  hunt never happened.  Latent S1/S2 bugs still in codebase, undiscovered.
  
  Compounds RF21: without Phase 7 catching bugs first, real Phase 8
  dress rehearsal will surface them under multi-role concurrent load.
  
  Fix scope: Session 3 schedules real Phase 7.  Time per spec: 4-5 days.

────────────────────────────────────────────────────────────

RED FLAG 38: Phase 7's renaming masks unfinished cross-role hunt
  userMemories records "Phase 7 (Polish) — 4 commits, COMPLETE".
  Matches 4 actual commits.  But "Polish" is NOT what Phase 7 was
  specified to be.
  
  Master roadmap Phase 7 done-criterion: "Zero S1 bugs, zero S2 bugs,
  S3/S4 documented in docs/known-issues.md, all role walkthroughs clean."
  
  Reality: zero of those criteria attempted.  "Phase 7 done" claim
  is structurally FALSE.
  
  Severity: HIGH.  Same axis as RF37, different dimension: the project
  lost track of what Phase 7 was supposed to BE.
  
  Pre-Sundance budget rebalance:
    RF33  Phase 1D auth migration         1-2 days
    RF37  Phase 7 cross-role bug hunt     4-5 days
    RF21  Phase 8 dress rehearsal         3-5 days
    Phase 9 ML + recipes (Omar-gated)     ~5 days
    Sundance buffer                       3-5 days
    Total: 16-22 days vs 32 days remaining.

────────────────────────────────────────────────────────────

## Appendix F — Layer 3 (Code) verification findings

Layer 3 directly verifies Layer 1 (doc claims) and Layer 2 (commit
claims) against actual code state.  This appendix records what
the code grep produced.

### F1.  RF35 — Detector #6 (Warehouse Discrepancy) CONFIRMED ABSENT

  Command: grep -rn "WarehouseDiscrepancy|warehouse_discrepancy"
           backend/app/
  Result:  ZERO matches.
  Severity: RF35 stays HIGH.  Detector #6 genuinely was not built;
            no alternate-naming hides it.
  Cross-check: alerts/detectors/ folder contains only DemandSpike
               detector per userMemories; this confirms by absence.

### F2.  RF18/RF34 — Offline queue CONFIRMED IMPLEMENTED

  Initially RF34 was marked RESOLVED POSITIVE based on commit
  message alone.  This is a Layer 2 anti-pattern (trusting
  commit text without code verification).  Layer 3 verifies:

  Command: grep -rn "offlineQueue|offline_queue|localStorage|
                     pendingScans|queueScan" frontend/src/
  Result:  Implementation lives at:
           frontend/src/features/warehouse/scanQueue.ts
           frontend/src/features/warehouse/useWarehouse.ts:530-555
  
  Note: NOT in features/scan/ — both Bartender and Warehouse scan
        flows route through features/warehouse/ since that's where
        the warehouse_scans table endpoint hooks live.
  
  Commit 45df782 message claims (all verified true):
    - Every scan carries client_event_id (UUID auto-generated)
    - localStorage stash on network failure
    - Auto-drain on browser 'online' event AND app mount
    - Server-side 4xx errors do NOT queue
    - Server idempotency makes replay safe
  
  Severity: RF18 + RF34 confirmed RESOLVED POSITIVE.
  Sundance offline tolerance: VERIFIED IMPLEMENTED.

### F3.  RF20 — docs/known-issues.md CONFIRMED MISSING

  Command: ls -la docs/known-issues.md
  Result:  No such file or directory.
  Severity: RF20 stays HIGH.  Confirms Phase 7 done-criterion
            structurally unmet (corroborates RF37, RF38).

### F4.  Codebase TODO/FIXME debt — LOW

  Commands:
    grep -rn "TODO|FIXME|XXX|HACK" backend/app/ --include="*.py"
    grep -rn "TODO|FIXME|XXX|HACK" frontend/src/ --include="*.ts*"
  Results:
    Backend:  7 occurrences
    Frontend: 3 occurrences
    Total:    10 across whole codebase
  
  Severity: LOW (no new RF).  Healthy debt level for a 6-week-old
  project with 193 commits.  Worth enumerating before Sundance
  to triage individual items.

### F5.  RF39 — Hypothesized then DISMISSED

  Hypothesis (during this Layer 3 dip): commit 45df782 message
  claimed offline queue but features/scan/ grep showed nothing.
  
  Resolution: queue lives in features/warehouse/, not features/scan/.
  Folder-naming confusion only.  Implementation is solid.
  
  Severity: DISMISSED.  Marker kept here so future audits don't
  re-raise the same hypothesis.

────────────────────────────────────────────────────────────

## Appendix E — Layer 2 phase-to-commit mapping (running)

This section maps roadmap-claimed phase completion to actual
commit hashes from git log.  Updated as Layer 2 progresses.

  Phase 0 — Recon                        2026-05-06
    Documented but no fix commits to verify (recon-only phase).
    Confirmed via b9af3d5 (2026-05-07): docs add roadmap.
    
  Phase 1A — Schema (backward-compat)   ⚠️ PARTIAL
  Phase 1B — Login endpoints alongside  ⚠️ PARTIAL
  Phase 1C — Frontend two-step + dropdown  ⚠️ PARTIAL
    Single commit 1a15439 (2026-05-07 17:53):
      "feat(auth): Phase 1 — multi-role login, two-step auth UI,
                   session-expiry modal"
    Encompasses 1A/B/C — exact granularity unverified.
    
  Phase 1D — Call-site migration        ❌ NOT DONE
    No commit found.  Verified by code grep (Appendix D RF33).
    
  Phase 2 — Owner experience            ✅ COMPLETE
    May 7: b8d7e4f (Batch A), c45be14 (Batch D)
    May 9: e71c770 (Batch B Inventory), e29e036 (Batch C polish),
           b64a78e (mark complete)
    Body section's "✅ COMPLETE 2026-05-07" refers to AUDIT date;
    commits land May 7 (A, D) and May 9 (B, C).
    
  Phase 3 — Manager experience          ✅ COMPLETE  
    May 9: 508621e (Batch E), 2739450 (Batch F), 7ba09eb (complete)
    Audit May 8; commits May 9.
    
  Phase 4 — Bartender experience        ✅ COMPLETE
    May 9: 8b1f67b (Batch G), 4cfa01d (complete)
    Audit May 8; commits May 9.
    
  Phase 5 — Warehouse Staff             ✅ COMPLETE
    May 9: b9befea (Batch H), 1f27ffb (complete)
    Audit May 8; commits May 9.
    
  Phase 6 — Camera Scanner System       ⚠️ PARTIAL
    22 commits land May 9-11.  Sub-phases shipped: 6.1-6.6.2,
    6.7 (REUSED for BarScanEmptiesPage NOT Detector #6),
    6.8, 6.9a, 6.11-6.12.4 (RECONCILIATION scope drift),
    6.13 (architecture doc), 6.14 (dress rehearsal CHECKLIST
    doc only, no actual rehearsal performed).
    Scanner functionality: SHIPPED
    Detector #6: NEVER SHIPPED (RF35)
    Physical dress rehearsal: DOC ONLY
    
  Phase 7 — Cross-Role Bug Hunt         ✅ CLAIMED (per memory)
    Detailed mapping pending Layer 2 continuation.
    docs/known-issues.md presence still unverified (RF20).
    
  Phase 8 — Sundance Dress Rehearsal    ❌ UNSTARTED
    No simulation event, no failure-mode tests, no performance
    verification commits found.  RF21 CRITICAL.
    
  Slesh Reconciliation Workstream       ✅ COMPLETE (May 11-17)
    11 commits ed98938 back through 331726d.
    Currently mis-labeled "Phase 8" in internal closure docs (RF2).
    
  Phase 9 — ML Model A                  ❌ UNSTARTED
    No commits matching ML / forecasting / pandas pipeline.
    Awaiting Phase 9 dependencies (recipes + Omar conversation).

────────────────────────────────────────────────────────────

## Appendix C — Audit findings inventory (running)

This section will collect every audit finding by severity for
end-of-session triage.  Updated each chunk.

### CRITICAL severity

  RF21  Real Phase 8 = Sundance Dress Rehearsal, UNSTARTED, this is
        the actual Sundance go/no-go (~2-3 days budget, 33 days left)
  RF33  Phase 1D NEVER HAPPENED — auth system in expand state of
        expand/contract migration, 20/20 legacy call sites unmigrated,
        get_active_role helper unused, users.role column still exists.
        Drift triggers (7 listed) any of which breaks the system.

### HIGH severity

  RF3   UX/Phase criteria never explicitly referenced in recent commits
  RF4   Test suite status unknown (now refined by RF8)
  RF8   Test-infrastructure debt formally documented + unresolved
  RF10  Phase 2 doc-internal contradiction (header says ⏸, body says ✅)
  RF11  Phase 1D critical sub-tasks unchecked (SUPERSEDED by RF33).
        Layer 2+3 confirmed: Phase 1D NEVER HAPPENED, see RF33.
  RF13  "Done" phases contain unchecked deferred items (refined; many
        resolved by body audits)
  RF17  Phase 6 header status doesn't match shipped reality
  RF18  Phase 6.6 offline-queue reliability not yet verified
  RF19  Phase 6.8 device-testing discipline deferred (Sundance reliability gap)
  RF20  Phase 7 known-issues.md may be missing (Phase 7 done-criterion gap)
  RF22  Phase 8.4 performance criteria specific + unverified (3 measurable)
  RF23  Phase 8.3 failure modes likely untested (4 categories)
  RF25  Phase 2 has dual sub-step systems (no cross-reference)
  RF27  B6.7-B6.14 polling worker tests deferred = critical test gap
  RF28  Phase-to-phase handoffs need cross-verification (Phase 4 → Phase 7)
  RF30  Four disconnected deferred-items lists (22+ items uncatalogued)
  RF35  Detector #6 (Warehouse Discrepancy) NEVER SHIPPED
  RF37  Phase 7 was renumbered + scope-shrunk (4 UI fixes instead
        of cross-role bug hunt)
  RF38  Phase 7 done-criterion structurally unmet

### MEDIUM severity

  RF2   Phase 8 naming collision (Slesh work vs dress rehearsal)
  RF6   Checkbox-DONE mismatch across sub-phases
  RF7   Empty completion records
  RF5   Branch hygiene rule violated (may indicate other drift)
  RF14  Detector #6 may be unblockable (resolved as RF16 cross-reference)
  RF26  ORM mapper init bug affects standalone scripts (Phase 9 risk)
  RF29  Warehouse Allocations UI missing (workaround exists)
  RF31  Alert text race may indicate broader adapter issue
  RF15  No consolidated deferred-items list (superseded by RF30)
  RF24  Appendix A is partial (superseded by RF30)
  RF36  Phase 6.11-6.12.4 is reconciliation scope drift (cosmetic)

### LOW severity

  RF1   Status pointer 11 days stale (mechanical fix)
  RF12  Phase 2 sub-step inventory now complete (14 sub-steps total)
  RF16  Detector #6 / Phase 2.13 -> Phase 6.7 cross-reference clarification
  RF34  Phase 6.4 IS the offline queue (RF18 resolved positive)

