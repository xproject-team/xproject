# Scanner Dress Rehearsal — Physical Device Checklist

**Phase 6.14 of the Sundance Readiness Roadmap.**
**Purpose:** verify the four things DevTools cannot test (audio, haptic, real camera, real offline behaviour) before Sundance go-live on 2026-06-19.
**Time required:** ~30 minutes once you have the phone + a few bottles in hand.
**Where to do it:** at home, then at the actual Sundance venue once accessible.

This is a *runnable* checklist. Each test has a pass/fail criterion. Mark each one ✅, ⚠, or ❌ as you go. Bring the laptop to look at backend logs / database state if needed.

---

## Pre-flight — 5 minutes

Before any test, confirm the environment is ready.

- [ ] **Phone has battery > 50%** — camera + screen drain power fast
- [ ] **Phone is on the same WiFi as the laptop** (or backend is reachable from phone's cellular)
- [ ] **Backend is running** — `curl -sI http://<laptop-ip>:8000/docs` returns 200 from phone's browser
- [ ] **Frontend is running with `--host 0.0.0.0`** — `vite` in `frontend/` started with the `dev` script
- [ ] **Phone can reach frontend** — open `http://<laptop-ip>:5173/` on phone, confirm app shell loads
- [ ] **Have 3+ real bottles ready** — at minimum one with a known-catalog barcode (Bacardi 7501055309603 if seeded)
- [ ] **Have headphones AND speaker mode tested** — to confirm audio works at different volumes

---

## TEST 1 — Audio feedback (5 minutes)

**Setup:** Login as Manager → /scan/arrivals. Phone unmuted, volume at ~70%.

- [ ] Tap "Allow camera" → camera opens
- [ ] Camera-permission tap satisfies iOS audio-policy → `primeAudio()` should fire
- [ ] Scan or manual-enter a known barcode
- [ ] **PASS criterion:** clear ascending chirp on success (200 Hz sine, 80 ms)
- [ ] Try an UNKNOWN barcode (e.g. type 0000000000000)
- [ ] **PASS criterion:** lower-pitched buzz on failure (90 Hz sawtooth, 200 ms) — distinguishable from success
- [ ] Tap Undo on a synced scan within 5 s
- [ ] **PASS criterion:** middle-pitched triple-blip on undo (150 Hz triangle, 120 ms)

**FAIL TROUBLESHOOTING:** if no sound at all, check phone Silent switch (iPhone hardware mute overrides Web Audio). If sound is muffled/clicky, the envelope attack/decay timing in `feedback.ts` may need re-tuning for the device.

---

## TEST 2 — Haptic feedback (3 minutes)

**Setup:** same page, phone in hand (not on table).

- [ ] Scan a known barcode
- [ ] **PASS criterion:** single 60 ms vibration pulse felt clearly
- [ ] Type unknown barcode, hit Scan
- [ ] **PASS criterion:** three-pulse pattern (60-100-60 ms) felt — different rhythm from success
- [ ] Tap Undo
- [ ] **PASS criterion:** double-pulse pattern (40-50-40 ms) felt

**iOS NOTE:** Safari on iOS deliberately ignores `navigator.vibrate()`. If you're on iPhone, haptic is expected to be silent. Mark as ⚠ "iOS-expected" not ❌. Android Chrome/Firefox should work.

---

## TEST 3 — Real camera barcode scan (10 minutes)

**Setup:** Manager on /scan/arrivals, holding 3+ real bottles.

- [ ] Hold a Bacardi-style bottle ~15 cm from the back camera, barcode squarely in the dotted frame
- [ ] **PASS criterion:** decoded + green flash + product name appears in Recent scans within 2 seconds
- [ ] Try at an oblique angle (~30°)
- [ ] **PASS criterion:** still decodes within ~3 seconds (may need to rotate)
- [ ] Try in low light (cup hand over barcode, dim room)
- [ ] **PASS criterion:** decodes within 5 seconds OR consistently fails to decode (no false positives)
- [ ] Try a curved bottle (round wine bottle)
- [ ] **PASS criterion:** decodes when barcode is centered; user can rotate bottle to find readable angle
- [ ] Try a damaged / partially-obscured barcode
- [ ] **PASS criterion:** does NOT decode (no false hit); user falls through to manual entry

**FAIL TROUBLESHOOTING:** if decode rate < 70% on clean barcodes, the `qrbox` dimensions in `BottleScanCard.tsx` may need to be widened (currently 240×160). If false positives occur, the `lastBarcodeRef` dedup window (2000ms) is the safety net.

---

## TEST 4 — Manual fallback under stress (3 minutes)

**Setup:** Manager on /scan/arrivals. Camera intentionally degraded — point at ceiling so it can't decode.

- [ ] Type 13-digit barcode into manual input
- [ ] Tap "Scan" (or hit Enter)
- [ ] **PASS criterion:** decode + submit succeeds in < 2 seconds total
- [ ] Repeat 5 times consecutively
- [ ] **PASS criterion:** 5 rows appear in Recent scans, no duplicates, no skipped
- [ ] **PASS criterion:** "Scan" button stays tappable (>= 44 px), works with a gloved thumb if available

---

## TEST 5 — Cross-role gating on real phone (3 minutes)

**Setup:** sign out, login as Bartender.

- [ ] **PASS criterion:** Bartender sidebar shows "Scan Empties" but NOT "Scan Arrivals"
- [ ] Tap "Scan Empties" → CONSUMED page renders
- [ ] In address bar, manually type `/scan/arrivals` → submit
- [ ] **PASS criterion:** red "Access denied" toast appears at top-center for ~4 seconds
- [ ] **PASS criterion:** redirected to /dashboard
- [ ] Tap the toast before it auto-dismisses
- [ ] **PASS criterion:** toast disappears instantly on tap

---

## TEST 6 — Offline queue drain (6 minutes — the trickiest one)

**Setup:** Manager on /scan/arrivals. Have laptop visible to watch backend logs.

- [ ] Confirm green "online" indicator at top-right of scanner page
- [ ] **Enable airplane mode on phone** (drop WiFi + cell at the same time)
- [ ] Wait ~5 seconds for the frontend to detect offline state
- [ ] **PASS criterion:** sync indicator changes to amber "1 pending sync" (or "N pending" if you've scanned already)
- [ ] Scan a known barcode (or manual-enter)
- [ ] **PASS criterion:** row appears in Recent scans with ⏳ "pending sync" subtitle, not ✓
- [ ] Scan 2-3 more times
- [ ] **PASS criterion:** all rows appear as pending; indicator says "3 pending sync" (or whatever count)
- [ ] **Disable airplane mode** — phone reconnects to WiFi
- [ ] Wait ~10 seconds for the auto-drain to fire
- [ ] **PASS criterion:** all ⏳ rows update to ✓ synced
- [ ] **PASS criterion:** indicator returns to green "online"
- [ ] On the laptop, check the database — `SELECT * FROM warehouse_scans WHERE event_id = '...' ORDER BY scanned_at DESC LIMIT 10;`
- [ ] **PASS criterion:** all the offline scans are present, each with its `client_event_id`, no duplicates

**FAIL TROUBLESHOOTING:** if rows don't drain on reconnect, `useScanQueueAutoDrain` may have a bug. Check `localStorage["xproject:scanQueue:<userId>"]` — items should be there pre-drain, gone post-drain. If duplicates appear, the server-side dedup on `(tenant_id, client_event_id)` failed (it shouldn't — verified in 6.3 smoke test).

---

## TEST 7 — Reconciliation report on phone (2 minutes)

**Setup:** sign out, login as Owner. Open the Sundance 2026 event detail page.

- [ ] **PASS criterion:** "View Reconciliation" button visible, primary navy styling, tappable
- [ ] Tap it
- [ ] **PASS criterion:** reconciliation page renders within 2 seconds
- [ ] **PASS criterion:** at-a-glance stat cards all visible on phone portrait (~375 px wide) — no horizontal scroll
- [ ] **PASS criterion:** Delivery gaps section renders green "All clear" or red gaps card readably
- [ ] **PASS criterion:** bar × product table renders — may scroll horizontally on phone, but column headers + data align

---

## TEST 8 — Battery + heat sanity check (passive — runs in background)

Across all the above tests:

- [ ] Phone is at how much battery? Note start: ___%, end: ___%
- [ ] **PASS criterion:** total drain < 15% over 30 minutes of camera-active scanning
- [ ] Is the phone uncomfortably hot to hold?
- [ ] **PASS criterion:** phone is warm but not painful — camera + JS engine combined should not thermal-throttle

---

## Final acceptance

All ✅ across Tests 1-8 (with iOS-haptic ⚠ acceptable) means:

- Scanner is production-ready for Sundance
- Real bartenders / managers can use it under realistic conditions
- Offline queue + idempotency + permission gating + business-value endpoint all work end-to-end including on phone

If ANY test fails, log the failure with reproduction steps and we patch in Phase 7 before go-live.

---

## After running this checklist

Open a git commit with the title `verify(phase-6.14): physical-device dress rehearsal {date}` and include this checklist's results as the commit body. That closes Phase 6 with a verifiable record on origin.

