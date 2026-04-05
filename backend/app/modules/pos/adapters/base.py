"""Abstract base class defining the POS adapter interface.

All POS integrations must subclass BasePOSAdapter so they can be swapped
without changing any business logic in POSService.
"""
from abc import ABC, abstractmethod


class BasePOSAdapter(ABC):
    """Defines the contract every POS adapter must fulfil."""

    @abstractmethod
    async def process_transaction(self, payload: dict) -> dict:
        """Process a sale transaction and return the normalised result."""
        ...

    @abstractmethod
    async def get_balance(self, wristband_id: str) -> float:
        """Return the current credit balance on a wristband."""
        ...
