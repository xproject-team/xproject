"""Pydantic v2 response schemas for the recharge module.

The dashboard fetches recharge data via a single endpoint:
    GET /api/v1/recharge-stations/by-event/{event_id}

which returns a list of `RechargeStationKpi`, each containing rolled-up
totals plus the per-device + per-payment-method breakdown needed by
the Recharge Desk card.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RechargeDeviceResponse(BaseModel):
    """A POS device at a recharge station, with its aggregated metrics."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    recharge_station_id: UUID
    slesh_operator_id: str
    slesh_operator_email: str
    device_number: int | None = None
    role: str
    is_active: bool
    last_order_at: datetime | None = None

    # Aggregates derived from ricarica_transactions for this device.
    # Populated at read time by the service layer; not stored on the
    # underlying ORM model.
    total_amount_cents: int = 0
    total_transactions: int = 0
    stripe_ttp_amount_cents: int = 0
    stripe_ttp_transactions: int = 0
    contanti_amount_cents: int = 0
    contanti_transactions: int = 0


class RechargeStationKpi(BaseModel):
    """A recharge station with its devices and rolled-up totals.

    This is the dashboard payload for the Recharge Desk card.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    name: str

    devices: list[RechargeDeviceResponse] = []
    devices_total: int = 0
    devices_active: int = 0

    # Roll-ups across all devices at this station.
    total_amount_cents: int = 0
    total_transactions: int = 0
    stripe_ttp_amount_cents: int = 0
    stripe_ttp_transactions: int = 0
    contanti_amount_cents: int = 0
    contanti_transactions: int = 0
