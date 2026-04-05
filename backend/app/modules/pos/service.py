"""Business logic for the POS module — transaction processing and adapter orchestration."""
from app.modules.pos.adapters.slesh import SleshAdapter


class POSService:
    """Orchestrates POS transactions through the configured adapter."""

    def __init__(self) -> None:
        self.adapter = SleshAdapter()
