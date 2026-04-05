"""Slesh NFC wristband POS adapter — implements BasePOSAdapter for the Slesh hardware/API."""
from app.modules.pos.adapters.base import BasePOSAdapter


class SleshAdapter(BasePOSAdapter):
    """Adapter for the Slesh NFC wristband payment system used at Sundance events."""

    async def process_transaction(self, payload: dict) -> dict:
        """Forward the transaction to the Slesh API and return a normalised result."""
        raise NotImplementedError("SleshAdapter.process_transaction not yet implemented")

    async def get_balance(self, wristband_id: str) -> float:
        """Query the Slesh API for the wristband's current balance."""
        raise NotImplementedError("SleshAdapter.get_balance not yet implemented")
