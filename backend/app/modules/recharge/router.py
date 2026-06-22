"""HTTP router for the recharge module.

Endpoints:
    GET   /recharge-stations/by-event/{event_id}    KPI for dashboard

Phase 2 (Jun 21 2026): single read-only endpoint that the dashboard
Recharge Desk card consumes. Returns rolled-up aggregates (total
recharged, devices_total, devices_active, stripe_ttp/contanti payment
split per device + per station).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.recharge.repository import RechargeRepository
from app.modules.recharge.schemas import RechargeStationKpi


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


@router.get(
    "/by-event/{event_id}",
    response_model=list[RechargeStationKpi],
)
async def list_recharge_kpis_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[RechargeStationKpi]:
    """Return all recharge stations for the event with rolled-up
    aggregates. Returns [] when no station has been configured.
    """
    repo = RechargeRepository(db)
    return await repo.get_kpis_for_event(tenant_id, event_id)
