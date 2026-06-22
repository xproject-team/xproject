"""Data access for the recharge module.

Read-only for Phase 2. The single public method `get_kpis_for_event`
returns the dashboard payload for the Recharge Desk card — one or more
stations, each with their devices and rolled-up aggregates split by
payment method.

The query is a single LEFT JOIN across stations + devices + transactions
with GROUP BY (station, device, payment_method). Python then folds rows
into the nested RechargeStationKpi shape with sums computed at three
levels: per-device, per-payment-method within device, and per-station.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recharge.schemas import (
    RechargeDeviceResponse,
    RechargeStationKpi,
)


_KPI_SQL = text("""
    SELECT
        rs.id          AS station_id,
        rs.name        AS station_name,
        rs.event_id    AS event_id,
        rd.id          AS device_id,
        rd.slesh_operator_id,
        rd.slesh_operator_email,
        rd.device_number,
        rd.role,
        rd.is_active,
        rd.last_order_at,
        rt.payment_method,
        COALESCE(SUM(rt.amount_cents), 0)      AS amount_cents,
        COALESCE(SUM(rt.transaction_count), 0) AS tx_count
    FROM recharge_stations rs
    LEFT JOIN recharge_devices       rd ON rd.recharge_station_id = rs.id
    LEFT JOIN ricarica_transactions  rt ON rt.recharge_device_id  = rd.id
    WHERE rs.tenant_id = :tenant_id
      AND rs.event_id  = :event_id
    GROUP BY
        rs.id, rs.name, rs.event_id,
        rd.id, rd.slesh_operator_id, rd.slesh_operator_email,
        rd.device_number, rd.role, rd.is_active, rd.last_order_at,
        rt.payment_method
    ORDER BY
        rs.id,
        rd.device_number NULLS LAST,
        rt.payment_method
""")


class RechargeRepository:
    """Pure data access for recharge stations and their aggregated KPIs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_kpis_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[RechargeStationKpi]:
        """Return all recharge stations for an event with rolled-up totals.

        Returns [] when no station exists. Returns a station with empty
        devices when station exists but no devices configured. Returns
        a device with zero aggregates when device exists but no
        transactions yet.
        """
        result = await self.db.execute(
            _KPI_SQL,
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        rows = list(result.mappings())
        if not rows:
            return []

        # Two-level fold: station -> devices -> payment-method aggregates
        stations: dict = {}
        for row in rows:
            sid = row["station_id"]
            if sid not in stations:
                stations[sid] = {
                    "id": sid,
                    "name": row["station_name"],
                    "event_id": row["event_id"],
                    "devices": {},  # device_id -> device dict
                }

            did = row["device_id"]
            if did is None:
                continue  # station has no devices yet

            devices = stations[sid]["devices"]
            if did not in devices:
                devices[did] = {
                    "id": did,
                    "event_id": row["event_id"],
                    "recharge_station_id": sid,
                    "slesh_operator_id": row["slesh_operator_id"],
                    "slesh_operator_email": row["slesh_operator_email"],
                    "device_number": row["device_number"],
                    "role": row["role"],
                    "is_active": row["is_active"],
                    "last_order_at": row["last_order_at"],
                    "total_amount_cents": 0,
                    "total_transactions": 0,
                    "stripe_ttp_amount_cents": 0,
                    "stripe_ttp_transactions": 0,
                    "contanti_amount_cents": 0,
                    "contanti_transactions": 0,
                }

            pm = row["payment_method"]
            if pm is None:
                continue  # device has no transactions yet

            amount = int(row["amount_cents"])
            count = int(row["tx_count"])
            d = devices[did]
            d["total_amount_cents"] += amount
            d["total_transactions"] += count
            if pm == "stripe_ttp":
                d["stripe_ttp_amount_cents"] += amount
                d["stripe_ttp_transactions"] += count
            elif pm == "contanti":
                d["contanti_amount_cents"] += amount
                d["contanti_transactions"] += count
            # Other payment methods contribute to total only.

        # Build response, computing station-level roll-ups
        out: list[RechargeStationKpi] = []
        for sd in stations.values():
            devs = [
                RechargeDeviceResponse(**d) for d in sd["devices"].values()
            ]
            out.append(RechargeStationKpi(
                id=sd["id"],
                event_id=sd["event_id"],
                name=sd["name"],
                devices=devs,
                devices_total=len(devs),
                devices_active=sum(1 for d in devs if d.is_active),
                total_amount_cents=sum(d.total_amount_cents for d in devs),
                total_transactions=sum(d.total_transactions for d in devs),
                stripe_ttp_amount_cents=sum(
                    d.stripe_ttp_amount_cents for d in devs
                ),
                stripe_ttp_transactions=sum(
                    d.stripe_ttp_transactions for d in devs
                ),
                contanti_amount_cents=sum(
                    d.contanti_amount_cents for d in devs
                ),
                contanti_transactions=sum(
                    d.contanti_transactions for d in devs
                ),
            ))
        return out
