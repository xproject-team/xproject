# Phase 8 / S7 — Three-Role Security Verification Record

**Status:** Verified 2026-05-13
**Verified by:** Hesam (technical lead) via Claude in Chrome browser agent
**Spec for:** Phase 8 of the Sundance Readiness Roadmap
**Endpoint under test:** GET /api/v1/events/{event_id}/reconciliation-report
**Frontend route under test:** /events/{event_id}/reconciliation

---

## 1. Why this exists

The reconciliation report exposes per-bar, per-product POS-aware variance
data — the over-pour / under-scan signal Omar pays the system to surface.
This data is Owner-only. Bartenders and Managers must not see it. Direct
URL navigation must not bypass the frontend gate. Direct API calls must
not bypass the route guard.

Three independent defense layers must each fail-closed for non-Owner roles:

  - Layer 1 (UI gate): no entry-point link is rendered for non-Owners
  - Layer 2 (Route guard): direct URL access triggers PermissionDeniedToast
                           and redirects to the role's home page
  - Layer 3 (Backend gate): /reconciliation-report endpoint returns 403
                            for non-Owner-bearing requests regardless of
                            how the request was constructed

This record documents the three-role verification that confirmed all
three layers fire correctly.

---

## 2. Test accounts

  Owner       omar@nomagroup.it             / xproject2026
  Manager     manager.cocktail@nomagroup.it / manager123
  Bartender   bartender.luca@nomagroup.it   / bartender123

The Owner is also the data controller under GDPR; the Manager and
Bartender are role-typical workplace accounts. Both Manager and
Bartender are assigned to Cocktail Bar (the active live event bar),
which is the worst-case scenario — accounts that DO have a legitimate
relationship to the event must still be blocked from the Owner-only
report.

---

## 3. Verification methodology

A single Claude in Chrome agent ran the full three-phase test. Each
phase tested one role against all three defense layers. Browser state
was reset between phases by clearing cookies and re-authenticating.

Layer 1 (UI gate) was tested by reading the rendered DOM via the
agent's read_page tool and grepping for any link, button, or menu
item with text "Reconciliation" (case insensitive).

Layer 2 (Route guard) was tested by force-navigating to the
reconciliation URL after login and observing the redirect target +
toast appearance.

Layer 3 (Backend gate) was tested by executing a credentialed fetch
to the reconciliation-report endpoint from the JavaScript console and
reading the HTTP response status.

---

## 4. Phase 1 — Owner (positive case)

The Owner role must succeed at every layer. Verification:

  - Login succeeded
  - The reconciliation page loaded fully at the direct URL
  - All 8 table columns present (Bar, Product, Arrived, Consumed, Net,
    POS sold, Variance, Status)
  - The S6 POS StatCards rendered (POS variance: OK, Over-pour flagged,
    Under-scan flagged, Pending recipes)
  - The single existing data row (Cocktail Bar / Bacardi Rum 1L)
    rendered honest no-data signaling: "—" in POS sold, "—" in
    Variance, "No POS data" gray status pill

Phase 1 result: PASS

---

## 5. Phase 2 — Manager (negative case)

The Manager role must be blocked at every layer despite being assigned
to the relevant bar. Verification:

  - Login succeeded (the Manager has legitimate access to the app)
  - The dashboard sidebar exposed: My Bar, Inventory, Scan Arrivals,
    Alerts, Chat, Settings. No Reconciliation link present (Layer 1
    PASS).
  - Direct navigation to /events/{id}/reconciliation redirected
    immediately to /dashboard. The PermissionDeniedToast fired on
    redirect with text "Access denied — You don't have permission
    to view /events/.../reconciliation." (Layer 2 PASS — see §7 for
    toast verification methodology note).
  - Credentialed fetch to the reconciliation-report endpoint returned
    HTTP 403 Forbidden (Layer 3 PASS).

Phase 2 result: PASS

---

## 6. Phase 3 — Bartender (negative case)

The Bartender role must be blocked at every layer. Verification:

  - Login succeeded as bartender.luca@nomagroup.it
  - The dashboard sidebar exposed: My Bar, Scan Empties, Inventory,
    Chat, Settings. No Reconciliation link present (Layer 1 PASS).
  - Direct navigation redirected immediately to /dashboard with the
    PermissionDeniedToast (Layer 2 PASS).
  - Credentialed fetch returned HTTP 403 Forbidden (Layer 3 PASS).

Phase 3 result: PASS

---

## 7. Toast verification methodology note

The first verification pass reported "redirect is silent; toast not
captured." Investigation via code recon (R3 and R4 of the followup
recon) confirmed the toast wiring is fully correct: RequirePermission
in routes.tsx dispatches a 'permission:denied' CustomEvent on redirect,
and PermissionDeniedToast (mounted globally) subscribes to that event.

The first verification was a timing artifact: the toast auto-dismisses
after 4 seconds and the agent's read_page was called after the
dismissal. A followup test using browser_batch (navigate + read_page in
a single round-trip, no scheduling delay between them) captured the
toast on the first read with full styling intact:

  role="status"
  classes: fixed top-[68px] left-1/2 -translate-x-1/2 z-[90]
           bg-[#FEE2E2] border border-[#EF4444] text-[#991B1B]
           rounded-xl shadow-lg
  text: "Access denied — You don't have permission to view
         /events/.../reconciliation."

This confirms the existing UX pattern from Phase 6 (commit f17e43c)
applies cleanly to the reconciliation route. No code change required.

---

## 8. Defense-in-depth summary

  Layer 1 (Frontend UI gate)
    Mechanism: route registration in src/app/routes.tsx line 274
               <RequirePermission flag="canGenerateReport">
    Permission rule: src/features/auth/usePermissions.ts line 58
                     canGenerateReport: role === 'owner'
    Result: Manager + Bartender never see the entry-point link

  Layer 2 (Route guard)
    Mechanism: RequirePermission component in src/app/routes.tsx
               function body. On permission denial, dispatches
               'permission:denied' CustomEvent and returns
               <Navigate to={home} replace />
    Toast: PermissionDeniedToast mounted at root listens for the
           event and renders the red banner for 4 seconds
    Result: direct URL navigation is blocked + user-visible

  Layer 3 (Backend gate)
    Mechanism: app/modules/events/router.py line 326
               response_model=ReconciliationReport plus FastAPI's
               role-based dependency injection
    Result: HTTP 403 Forbidden regardless of how the request was
            crafted, even with a valid auth cookie

All three layers fail-closed independently. Removing any one of them
would still leave the other two enforcing.

---

## 9. Next verifications

Two follow-up checks remain for full Sundance readiness, both deferred
to Phase 9 or to the pre-event smoke test 3 days before June 19:

  - End-to-end browser test on a real iOS Safari + Android Chrome
    device, not just desktop Chrome. Phase 6's dress rehearsal
    checklist already covers this for the scanner; the reconciliation
    page should be added to that checklist.

  - Re-verification after the Phase 9 recipe-cascade work lands. Once
    recipes exist, the variance signal will produce non-null values
    and the status pills will move out of NO_POS_DATA / NEEDS_RECIPE
    into the OK / OVER_POUR / UNDER_SCAN tiers. The same three-role
    pattern should be re-run at that point.

---

## 10. References

  Phase 8 S6 commit: 18e33d9 (frontend display, the page under test)
  Phase 8 S5 commit: f5b2594 (schema + service that populated the data)
  Phase 6 toast commit: f17e43c (the PermissionDeniedToast pattern reused here)
  Phase 6 verification commit: 5c4dc52 (the three-role precedent this followed)
