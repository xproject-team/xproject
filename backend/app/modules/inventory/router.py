# ═══════════════════════════════════════════════════════════════════════════
# DEPRECATED MODULE — Scheduled for replacement in Step 4 (Stock module)
# ═══════════════════════════════════════════════════════════════════════════
# This module was scaffolded with Integer IDs and broken FKs (events.id is UUID
# in the current schema). Frontend hits GET /inventory?event_id=X which currently
# returns empty or 500s. Kept alive to avoid breaking /inventory and
# /warehouse/inventory pages. Will be cleanly replaced by the Stock module
# per the XProject build roadmap. Do NOT extend this file.
# ═══════════════════════════════════════════════════════════════════════════

"""HTTP router for the inventory module — input validation and response formatting only."""
from fastapi import APIRouter

router = APIRouter()
