"""Constants for the customer-intelligence panel — see service.py for
where each is used.
"""
from __future__ import annotations

from uuid import UUID

# The 3 events with real customer identity data (Slesh user._id present
# on a meaningful share of orders) — the only source "returning guest"
# recognition can draw on. Excludes the 9 historical 2024/2025 events
# (no per-order identity was ever extracted for those, see Day 3) and
# any future event, which naturally can't be a "prior" event yet.
IDENTITY_EVENT_IDS = frozenset({
    UUID("6bd035a9-3ab4-4c7f-8f68-c811aef9fa47"),  # Sundance 14 (Jun-14 2026)
    UUID("0888f4b7-7030-426b-815c-938e6ca447a6"),  # Jul-5 2026
    UUID("9ae0dc52-8a01-4998-b430-3814bd8cdabe"),  # Jul-19 2026
})

# Spend-segment thresholds, derived from customer_sessions.total_spend_cents
# across the 3 IDENTITY_EVENT_IDS (n=3,442 sessions, read 2026-07-30):
#   p33 = 2,400c (EUR 24) — bottom third -> "light"
#   p85 = 6,800c (EUR 68) — top 15%     -> "whale"
# Middle band (2,400 < spend < 6,800) -> "regular". Not invented round
# numbers — these are the actual percentile values off the real
# distribution (median EUR 35, p90 EUR 80, p95 EUR 100). See the Day 4
# report for the full percentile table.
LIGHT_SPEND_MAX_CENTS = 2400
WHALE_SPEND_MIN_CENTS = 6800
