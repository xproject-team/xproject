# XProject — Manager Cheat Sheet

**You are the link between bartenders and the owner. Read this once before the event.**

---

## 1. Logging in

1. Open XProject on your tablet or laptop
2. Tap the **Manager** card
3. Enter your email + password (the owner provides these)
4. You'll land on the dashboard for **your bar only**

If you manage multiple bars, you have separate accounts — log in with the one for the bar you're currently at.

---

## 2. What you see vs what bartenders see

| Thing | You | Bartender |
|---|---|---|
| Stock levels | ✅ | ✅ |
| Revenue | ✅ | ✅ |
| Critical depletion alerts | ✅ | ✅ |
| **Warning alerts** | ✅ | ✅ |
| **Anomaly alerts (recipe deviation, demand spike)** | ❌ | ❌ |
| Chat from owner | ✅ | ✅ |
| Other bars | ❌ | ❌ |

**Anomaly alerts are Owner-only by design.** If the owner asks you to "do a routine count" of a specific product, do it promptly — the platform flags stock anomalies and asks for a count to confirm or rule them out. You don't need to know what triggered it; just count and report back via chat.

---

## 3. Scanner — your 2 actions

| Action | When to use it |
|---|---|
| **DISPATCH** | "I'm sending this case from the warehouse to my bar" — increases bar stock, decreases warehouse stock |
| **RETURN** | "I'm sending this back to the warehouse" — decreases bar stock, increases warehouse stock |

Always scan **before** physically moving product, not after. The system needs the timestamp to match reality.

---

## 4. Acknowledging alerts

When a depletion alert fires, you have 3 choices:

1. **Acknowledge** — "I see it, I'm handling it" → alert goes from active to acknowledged
2. **Take action** — DISPATCH more product to the bar, then acknowledge
3. **Ignore** — alert auto-resolves when stock goes back above threshold

Acknowledge ASAP even if you can't fix it immediately. The owner can see un-acked alerts piling up — that's a bad signal.

---

## 5. Chat — your two-way comms

- **From bartender:** "Bacardi 1L is at 2 bottles" → respond with action: "Dispatching now" or "Ride it out, restock at 11pm"
- **From owner:** assume any owner message needs a response within 5 minutes — they're firefighting from a high level

Brevity > completeness. The owner has 5 bars; long messages slow them down.

---

## 6. If something is broken

| Symptom | First action |
|---|---|
| Dashboard won't load | Refresh the page (Cmd+R or pull-down on tablet) |
| Scanner won't open camera | Quit app, reopen, accept camera permission |
| Stock numbers look wrong | Don't fix it — message the owner. Wrong numbers might mean a bug we need to log |
| Bartender can't log in | Confirm with owner that the bartender's account exists |
| Whole system seems down | Owner's problem; you keep operating manually with paper |

The bar continues running even if XProject is down. Sales go through the Slesh POS as normal. XProject is the **observability layer**, not the cash layer.

---

## 7. End of event

- Do a final walk-through of your bar's stock — INSPECT scan anything that wasn't tracked tonight
- Confirm via chat with the owner that your bar is "closed out"
- Log out

---

**Emergency contacts during the event:**
- **Owner (Omar):** _[pre-filled by owner]_
- **XProject technical (Hesam):** _[pre-filled by owner]_
- **Slesh POS support:** _[pre-filled by owner]_
