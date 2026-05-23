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

_(populated by the structured smoke test below)_

## Round 2 — Manager walkthrough

_(pending)_

## Round 3 — Bartender walkthrough

_(pending)_

## Round 4 — Warehouse walkthrough

_(pending)_

## Round 5 — Synthetic stress

_(pending)_

## Round 6 — Event lifecycle

_(pending)_
