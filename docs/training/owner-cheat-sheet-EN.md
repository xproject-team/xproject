# XProject — Owner Cheat Sheet

**For Omar. The platform works for you, not the other way around. Two pages.**

---

## 1. The dashboard tells you 4 things at a glance

1. **Total revenue tonight** — top of screen, updates every few seconds
2. **Bar grid** — one card per bar, with a colored border showing health
   - Green border = all good
   - Yellow border = at least one warning alert
   - Red border = at least one critical alert
3. **Alerts column (right side)** — every alert across all bars, newest first
4. **Chat window** — your two-way line to every manager

Tap any bar card to drill into that bar's detail view.

---

## 2. The 3 alert classes you'll see

| Class | What it means | Audience |
|---|---|---|
| **Depletion** | A specific product will run out in <2 hours | You + the bar's manager |
| **Anomaly — Demand spike** | One product is selling 2-3× faster than normal | You only (manager doesn't see the alert itself) |
| **Anomaly — Recipe deviation** | A bar is using more ingredient than the recipe says | You only (manager doesn't see the alert itself) |

Anomaly alerts are owner-only on purpose — they let you spot potential stock issues (over-pouring, miscounting, or training gaps) before they become operational problems. When you **acknowledge an anomaly alert**, the system auto-posts a neutral "please do a routine count" message to the bar's chat **from your account**. The manager sees a request from you to count a product; they don't see the underlying anomaly that triggered it.

---

## 3. Acknowledging alerts

Tap an alert card → **Acknowledge**

What happens:
- The alert moves out of the active list
- For anomalies: a neutral chat message gets auto-posted to that bar's channel
- The acknowledgment is logged forever (you can audit later)

You can also **resolve** an alert manually if you've handled it. Resolution is permanent.

---

## 4. The chat — your remote control

- Message any bar manager directly
- Messages are delivered in real-time
- The manager sees your name and the timestamp
- Use chat to ask for counts, send instructions, or just to say "thanks"

You **cannot** message a bartender directly — by design. All comms go through the manager. This keeps your channel count manageable across 5+ bars.

---

## 5. When to NOT trust the dashboard

XProject reads sales data from Slesh, which has its own latency. Realistic numbers:

- Revenue updates: **every 30 seconds** (cron polls Slesh)
- Stock updates: **immediate** when a scan happens, **30 sec lag** when sales reduce stock
- Alert evaluation: **every 5 minutes** (cron)

If the cron is stuck, alerts go silent. Diagnostic:

```bash
cat > /Users/mohammadhesam/Projects/xproject/docs/training/owner-cheat-sheet-EN.md << 'MD_EOF'
# XProject — Owner Cheat Sheet

**For Omar. The platform works for you, not the other way around. Two pages.**


## 6. If something goes wrong

| Symptom | First action |
|---|---|
| Dashboard shows nothing | Run the deep health check (above) — pick the failing component |
| Bar X looks dead | Call the bar manager. The bar might just be in a quiet stretch |
| An alert seems wrong | Trust it. Send a manager to verify physically. False positives are rare and worth a 30-sec check |
| The whole site is unreachable | Slesh keeps running. The bar keeps selling. Hesam fixes the platform from his laptop. You keep working from your gut |

The platform is **insurance + leverage**, not a single point of failure. The bars run with or without it.

---

## 7. End-of-event report

After Sundance ends:
- The Reports page auto-generates a per-event PDF (Italian + English)
- Includes: total revenue, top products, top bars, anomalies detected, stock variances
- Send it to your CFO / accountant the next morning

If you want a specific cut of the data (e.g. "revenue per hour for cocktails"), tell Hesam — he'll add it to the report template for next time.

---

## 8. Direct line

- **XProject technical (Hesam):** _[your number]_
- **Slesh POS support:** _[Slesh contact]_

Call, don't text. During the event your screen is full of dashboards.
