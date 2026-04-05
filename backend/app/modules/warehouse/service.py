"""Business logic for the warehouse module — scan processing and inventory updates."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.barcode import decode_barcode


class WarehouseService:
    """Processes barcode scans, resolves SKUs, and updates warehouse inventory."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
