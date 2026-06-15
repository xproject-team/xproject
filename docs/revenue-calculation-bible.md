# Revenue Calculation Bible

The canonical math behind RevenueBreakdownService and the dashboard revenue
popup. **Do not change the service without updating this document.**

## Core principles

1. **Source of truth**: EventOrder.subtotal_cents (= Slesh __subtotal) is
   what the customer paid at the till. It already includes VAT and deposits.
2. **Refunded orders are excluded** from all revenue calculations.
3. **Refunded lines within completed orders** (cup deposit returns) are
   tracked via stock_transactions.pos_line_status='refunded'.
4. **Data-driven categorization**: Bar.bar_type and
   Event.food_revenue_share_pct. No name-matching in revenue logic.
5. **Slesh dashboard 'Transato' is NOT revenue.** Transato also includes
   unspent wristband ricariche (top-ups not yet consumed), which the Slesh
   public API does not expose. Vera revenue is therefore expected to be
   lower than Slesh's Transato by the unspent amount.

## Formulas

    GROSS_REVENUE     = sum(subtotal_cents)      WHERE status != 'refunded'
    VAT_COLLECTED     = sum(vat_cents)           WHERE status != 'refunded'
    DEPOSITS_TAKEN    = sum(deposit_cents)       WHERE status != 'refunded'
    FISCAL_REVENUE    = sum(fiscal_gross_cents)  WHERE status != 'refunded'
                        (= GROSS - DEPOSITS_TAKEN, reported to fisc authorities)

    DRINKS_GROSS      = sum(subtotal_cents) WHERE bar.bar_type in (drinks, mixed)
    FOOD_GROSS        = sum(subtotal_cents) WHERE bar.bar_type = food
    CASH_DESK_GROSS   = sum(subtotal_cents) WHERE order_type   = cash-desk

    DEPOSITS_RETURNED = sum(stock_tx.qty * price_cents)
                        WHERE pos_line_status = 'refunded'
                        AND product matches deposit pattern
    DEPOSITS_FORFEITED = DEPOSITS_TAKEN - DEPOSITS_RETURNED

    FOOD_OWNER_SHARE  = FOOD_GROSS * (event.food_revenue_share_pct / 100)
    FOOD_VENDOR_SHARE = FOOD_GROSS - FOOD_OWNER_SHARE

    OWNER_NET_TAKEHOME = GROSS_REVENUE
                         - DEPOSITS_RETURNED   (cust got deposit back)
                         - VAT_COLLECTED       (to Stato)
                         - FOOD_VENDOR_SHARE   (to food-truck partner)

## Why forfeited deposits are NOT added on top

GROSS_REVENUE already includes DEPOSITS_TAKEN (the customer paid
gross-with-deposit at the till). The forfeited portion stays with the
owner only because the customer never returned. So:

* Adding FORFEITED on top of GROSS would double-count.
* Subtracting RETURNED from GROSS correctly leaves the forfeited
  portion as owner-kept income.

## Sundance 14 verification (2026-06-14)

With food_revenue_share_pct = 30:

| Metric | Value | Source |
|---|---|---|
| GROSS_REVENUE | EUR 55,261 | service compute |
| Drinks gross | EUR 48,389 | Bar Main + Bar Stage + Bar n.3 |
| Food gross | EUR 6,412 | three food trucks |
| Cash-desk | EUR 460 | direct cash |
| DEPOSITS_TAKEN | EUR 1,244 | 1229 cups + bottles |
| DEPOSITS_RETURNED | EUR 465 | 411 cups returned |
| DEPOSITS_FORFEITED | EUR 779 | 818 lost (37% return rate) |
| VAT_COLLECTED | EUR 5,024 | ~10% on drinks/food |
| FOOD_VENDOR_SHARE | EUR 4,488 | 70% of EUR 6,412 |
| OWNER_NET_TAKEHOME | **EUR 45,284** | gross - returned - VAT - vendor |

Slesh dashboard 'Transato': EUR 59,998. The EUR 4,737 gap = unspent ricariche.

## Things this is NOT

- Ricariche (wristband top-ups): not in Slesh public API. Requires manual
  entry to display.
- Unspent balance: derived (ricariche minus consumption).
- Cost of goods sold: not tracked yet.
- Labor, venue, supplier costs: not tracked yet.

## Future improvements

- Manual ricariche entry: Event.ricariche_total_cents, exposes unspent
  balance in CashFlow.
- VAT-aware owner net (currently uses raw VAT, doesn't differentiate
  VAT-on-deposits which is 0).
- Per-product VAT rate (food trucks may have 22% rate vs drinks 10%).
- Promote CartLine._isDeposit to schema, retire name-based deposit matching.
