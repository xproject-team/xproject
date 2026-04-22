"""AlertsService — core business logic for the Alerts module.

Responsibilities:
- Create alerts with deduplication (no floods of identical alerts)
- List active / historical alerts, filtered by severity, bar, type
- Acknowledge alerts with optimistic locking (two-tab race-safe)
- Auto-resolve alerts whose underlying condition stopped applying
- Expire alerts when their event ends unresolved
- Project Alert ORM rows into role-appropriate AlertResponse payloads
  (owners see full detail, managers see sanitized operational text only,
  anomaly alerts never reach managers)

Design principles reinforced here:

1. Tenant isolation is NON-NEGOTIABLE. Every query filters by tenant_id.
   No method accepts a bare alert_id without a tenant_id next to it.

2. Deduplication happens INSIDE the create transaction with row-level
   locking so two concurrent evaluator runs can't both insert.

3. Audience filter lives here, not in the router. Router just passes the
   caller's role; the service decides what to return. Single rule, any
   consumer (REST, WebSocket, future CLI) gets the same enforcement.

4. Lifecycle state transitions are unidirectional:
      active → acknowledged  (Owner click)
      active → auto_resolved (evaluator says condition ended)
      active → expired       (event ended while still unresolved)
   Two states can coexist (acknowledged + auto_resolved) — we surface
   the most informative one via the ORM's lifecycle_state property.

5. Optimistic locking via version column on Ack. Same pattern as Events.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import (
    AlertAcknowledgeResponse,
    AlertCreate,
    AlertListResponse,
    AlertResponse,
)

logger = logging.getLogger(__name__)


# ─── Domain exceptions ────────────────────────────────────────────────────────
# Router maps each to an HTTP status + typed error envelope.


class AlertNotFoundError(Exception):
    """Alert does not exist for this tenant."""


class StaleAlertVersionError(Exception):
    """Optimistic lock conflict on acknowledge. Client must refetch."""

    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__(f"stale version; current is {current_version}")


class AlertAlreadyAcknowledgedError(Exception):
    """Alert has already been acknowledged; re-ack is a no-op but we
    surface this to the client so it can refresh its local state."""


class AlertAccessDeniedError(Exception):
    """Manager tried to read an alert they shouldn't see (owner_only, or
    wrong bar). Router surfaces as 403 — never 404, because 404 would leak
    existence information."""


# ─── Role type for audience filtering ─────────────────────────────────────────
UserRole = Literal["owner", "manager", "bartender"]


class AlertsService:
    """Thin, stateless wrapper around the alerts table.

    One instance per request. Holds the AsyncSession; does not cache state
    across calls.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── Realtime broadcast helper ─────────────────────────────────────
    # Publishes a tiny "something changed" frame to Redis. WebSocket
    # subscribers invalidate their frontend cache and refetch via HTTP.
    # Broadcast failure must NEVER fail the REST request.
    async def _broadcast(self, event_id, payload_type: str, alert_id=None):
        try:
            # Lazy import avoids circular deps (realtime -> alerts -> realtime)
            from app.core.redis_client import publish as _ws_publish
            payload = {"type": payload_type, "event_id": str(event_id)}
            if alert_id is not None:
                payload["alert_id"] = str(alert_id)
            await _ws_publish(f"alerts:{event_id}", json.dumps(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("alerts broadcast failed: %s", exc)

    # ─── Chat tie-in helper (anomaly acknowledgements) ─────────────────────
    async def _auto_post_stock_count_request(
        self,
        tenant_id,
        bar_id,
        sender_id,
    ) -> None:
        """Post a neutral stock-count-request message to the bar's chat channel.

        Bypasses ChatService.post_message to avoid its internal commit (which
        would prematurely end our acknowledge transaction). Also publishes the
        chat:{channel_id} frame so connected chat WebSocket listeners render
        the message live. If no bar channel exists yet, silently no-ops.
        """
        from sqlalchemy import and_, select
        from app.modules.chat.models import Channel, ChatMessage

        chan_stmt = select(Channel).where(and_(
            Channel.bar_id == bar_id,
            Channel.channel_type == "bar",
            Channel.tenant_id == tenant_id,
        ))
        channel = (await self.db.execute(chan_stmt)).scalar_one_or_none()
        if channel is None:
            logger.info(
                "chat tie-in: no bar channel for bar=%s; skipping", bar_id,
            )
            return

        message = ChatMessage(
            tenant_id=tenant_id,
            channel_id=channel.id,
            sender_id=sender_id,
            body=(
                "When convenient, please do a routine count of your bar "
                "inventory and send totals. Thanks."
            ),
        )
        self.db.add(message)
        await self.db.flush()  # flush only; let the caller commit
        logger.info(
            "chat tie-in: posted stock-count request to channel=%s for bar=%s",
            channel.id, bar_id,
        )

        # Publish on the chat:{channel_id} key so any connected chat WS
        # subscribers see the message live. Same lazy-import pattern as
        # the alerts broadcast helper above.
        try:
            from app.core.redis_client import publish as _ws_publish
            payload = {
                "type": "message_posted",
                "channel_id": str(channel.id),
                "message_id": str(message.id),
            }
            await _ws_publish(f"chat:{channel.id}", json.dumps(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat tie-in: broadcast failed: %s", exc)

    # ── Internal: project an ORM Alert → role-appropriate AlertResponse ──

    def _view(
        self,
        alert: Alert,
        user_role: UserRole,
        user_bar_id: UUID | None = None,
    ) -> AlertResponse:
        """Role-aware projection. Raises AlertAccessDeniedError if the
        caller must not see this alert at all.

        Rules:
        - Owners see every tenant-scoped alert, full owner_message.
        - Managers only see alerts where audience='owner_and_manager' AND
          the alert's bar_id matches their assigned bar. They see
          manager_message (never owner_message). They NEVER see anomaly
          alerts (which are owner_only by design).
        - Bartenders: same rules as managers for now; revisit when we have
          role-specific UX.
        """
        if user_role == "owner":
            message = alert.owner_message
        else:
            # Manager/bartender audience gate
            if alert.audience == "owner_only":
                raise AlertAccessDeniedError()
            if user_bar_id is None or alert.bar_id != user_bar_id:
                raise AlertAccessDeniedError()
            # manager_message may legitimately be None for edge cases; fall
            # back to title so the UI always has something to render.
            message = alert.manager_message or alert.title

        return AlertResponse(
            id=alert.id,
            tenant_id=alert.tenant_id,
            event_id=alert.event_id,
            bar_id=alert.bar_id,
            product_id=alert.product_id,
            alert_type=alert.alert_type,
            severity=alert.severity,
            audience=alert.audience,
            title=alert.title,
            message=message,
            suggested_action=alert.suggested_action,
            ai_advisory=alert.ai_advisory,
            context_json=alert.context_json or {},
            created_at=alert.created_at,
            acknowledged_at=alert.acknowledged_at,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            auto_resolved_at=alert.auto_resolved_at,
            expired_at=alert.expired_at,
            lifecycle_state=alert.lifecycle_state,
            version=alert.version,
        )

    # ── CREATE (with dedup) ─────────────────────────────────────────────────

    async def create_alert(
        self,
        tenant_id: UUID,
        payload: AlertCreate,
    ) -> Alert:
        """Create or update-via-dedup. Returns the row (updated or new).

        Dedup rule: if an active alert exists for the same
        (tenant, event, bar, product, alert_type), DO NOT insert a new row.
        Instead, update severity + context_json + bump version. This prevents
        alert floods when the same condition persists across evaluator cycles.

        Concurrency: SELECT ... FOR UPDATE on the dedup lookup serializes
        concurrent creates of the same key. The per-tenant scheduler enforces
        single-writer at the top, but FOR UPDATE is cheap insurance.
        """
        dedup_filter = and_(
            Alert.tenant_id == tenant_id,
            Alert.event_id == payload.event_id,
            Alert.bar_id == payload.bar_id,
            Alert.alert_type == payload.alert_type,
            # product_id can be NULL; use IS NOT DISTINCT FROM semantics
            or_(
                Alert.product_id == payload.product_id,
                and_(
                    Alert.product_id.is_(None),
                    payload.product_id is None,
                ),
            ),
            Alert.acknowledged_at.is_(None),
            Alert.auto_resolved_at.is_(None),
            Alert.expired_at.is_(None),
        )

        existing = (
            await self.db.execute(
                select(Alert).where(dedup_filter).with_for_update()
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Update severity + context on the live row. Don't touch audience
            # or type (those are invariants after first fire).
            existing.severity = payload.severity
            existing.context_json = payload.context_json
            existing.suggested_action = payload.suggested_action
            existing.version += 1
            await self.db.flush()
            logger.info(
                "alert dedup-update id=%s severity=%s version=%s",
                existing.id, existing.severity, existing.version,
            )
            return existing

        row = Alert(
            tenant_id=tenant_id,
            event_id=payload.event_id,
            bar_id=payload.bar_id,
            product_id=payload.product_id,
            alert_type=payload.alert_type,
            severity=payload.severity,
            audience=payload.audience,
            title=payload.title,
            owner_message=payload.owner_message,
            manager_message=payload.manager_message,
            suggested_action=payload.suggested_action,
            context_json=payload.context_json,
        )
        self.db.add(row)
        await self.db.flush()
        logger.info(
            "alert created id=%s type=%s severity=%s event=%s bar=%s",
            row.id, row.alert_type, row.severity,
            row.event_id, row.bar_id,
        )
        await self._broadcast(row.event_id, "alert_changed", row.id)
        return row

    # ── READ ────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        user_role: UserRole,
        user_bar_id: UUID | None = None,
        only_active: bool = True,
        severity: str | None = None,
    ) -> AlertListResponse:
        """List alerts for an event, filtered by the caller's role.

        Managers are automatically restricted to their own bar's alerts
        with audience='owner_and_manager'. Owners see everything tenant-
        scoped.
        """
        conditions = [
            Alert.tenant_id == tenant_id,
            Alert.event_id == event_id,
        ]
        if only_active:
            conditions.extend([
                Alert.acknowledged_at.is_(None),
                Alert.auto_resolved_at.is_(None),
                Alert.expired_at.is_(None),
            ])
        if severity is not None:
            conditions.append(Alert.severity == severity)

        # Manager gate at the SQL layer for performance: don't even load
        # rows the manager can't see.
        if user_role != "owner":
            if user_bar_id is None:
                return AlertListResponse(items=[], total=0)
            conditions.extend([
                Alert.audience == "owner_and_manager",
                Alert.bar_id == user_bar_id,
            ])

        stmt = (
            select(Alert)
            .where(and_(*conditions))
            .order_by(Alert.created_at.desc())
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        items: list[AlertResponse] = []
        for row in rows:
            try:
                items.append(self._view(row, user_role, user_bar_id))
            except AlertAccessDeniedError:
                # Defense in depth: shouldn't happen given SQL filter above.
                continue

        return AlertListResponse(items=items, total=len(items))

    async def get_by_id(
        self,
        tenant_id: UUID,
        alert_id: UUID,
        user_role: UserRole,
        user_bar_id: UUID | None = None,
    ) -> AlertResponse:
        """Fetch a single alert, projected for the caller.

        Raises AlertNotFoundError for missing or cross-tenant lookup.
        Raises AlertAccessDeniedError for role/bar mismatch.
        """
        row = (
            await self.db.execute(
                select(Alert).where(
                    and_(
                        Alert.id == alert_id,
                        Alert.tenant_id == tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if row is None:
            raise AlertNotFoundError()

        return self._view(row, user_role, user_bar_id)

    # ── ACKNOWLEDGE (optimistic lock) ───────────────────────────────────────

    async def acknowledge(
        self,
        tenant_id: UUID,
        alert_id: UUID,
        user_id: UUID,
        expected_version: int,
    ) -> AlertAcknowledgeResponse:
        """Mark an alert acknowledged. Optimistic lock via version.

        Idempotent-friendly: if the alert is already acknowledged, we
        raise AlertAlreadyAcknowledgedError so the client refreshes;
        we do NOT silently overwrite acknowledged_by / acknowledged_at.
        """
        row = (
            await self.db.execute(
                select(Alert).where(
                    and_(
                        Alert.id == alert_id,
                        Alert.tenant_id == tenant_id,
                    )
                ).with_for_update()
            )
        ).scalar_one_or_none()

        if row is None:
            raise AlertNotFoundError()

        if row.version != expected_version:
            raise StaleAlertVersionError(current_version=row.version)

        if row.acknowledged_at is not None:
            raise AlertAlreadyAcknowledgedError()

        now = datetime.now().astimezone()
        row.acknowledged_at = now
        row.acknowledged_by_user_id = user_id
        row.version += 1
        await self.db.flush()

        logger.info(
            "alert acknowledged id=%s by=%s",
            row.id, user_id,
        )

        await self._broadcast(row.event_id, "alert_changed", row.id)

        # ─── Chat tie-in: silent investigation for anomalies ───────────────
        # When the Owner acknowledges an anomaly alert, auto-post a neutral
        # "please do a count" message to the bar channel. Owner-authored
        # (appears from the acknowledging user). Generic wording — no product
        # name — so the bartender cannot reverse-engineer which item we're
        # auditing. If the post fails for any reason, it must NEVER fail the
        # acknowledge request; log and swallow.
        if row.alert_type == "anomaly" and row.audience == "owner_only":
            try:
                await self._auto_post_stock_count_request(
                    tenant_id=tenant_id,
                    bar_id=row.bar_id,
                    sender_id=user_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chat tie-in failed for alert=%s: %s", row.id, exc,
                )

        return AlertAcknowledgeResponse(
            id=row.id,
            acknowledged_at=row.acknowledged_at,
            acknowledged_by_user_id=row.acknowledged_by_user_id,
            version=row.version,
            lifecycle_state=row.lifecycle_state,
        )

    # ── LIFECYCLE: auto-resolve + expire ────────────────────────────────────

    async def auto_resolve_missing(
        self,
        tenant_id: UUID,
        event_id: UUID,
        still_active_keys: set[tuple[UUID, UUID | None, str]],
    ) -> int:
        """Auto-resolve alerts whose dedup key is NOT in the provided set.

        Called by the evaluator AFTER it has finished a full pass and
        produced the set of keys that should still be active. Any active
        alert not in that set represents a condition that has ended
        (e.g. stock restocked, burn rate dropped below INFO threshold).

        Returns the number of rows updated. Bounded per-call so the
        background loop stays responsive; the evaluator cycles anyway.
        """
        active_stmt = select(Alert).where(
            and_(
                Alert.tenant_id == tenant_id,
                Alert.event_id == event_id,
                Alert.acknowledged_at.is_(None),
                Alert.auto_resolved_at.is_(None),
                Alert.expired_at.is_(None),
            )
        )
        rows = (await self.db.execute(active_stmt)).scalars().all()

        now = datetime.now().astimezone()
        count = 0
        for row in rows:
            key = (row.bar_id, row.product_id, row.alert_type)
            if key in still_active_keys:
                continue
            row.auto_resolved_at = now
            row.version += 1
            count += 1

        if count:
            await self.db.flush()
            logger.info(
                "auto-resolved %d alerts for event=%s", count, event_id,
            )
            # Broadcast a single change frame; frontend invalidates + refetches.
            await self._broadcast(event_id, "alerts_auto_resolved", None)
        return count

    async def expire_event_alerts(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> int:
        """Called when an event transitions to COMPLETED. Any still-active
        alert is marked expired so the report shows 'Owner never acted'.
        Returns number of rows updated.
        """
        now = datetime.now().astimezone()
        stmt = (
            update(Alert)
            .where(
                and_(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id == event_id,
                    Alert.acknowledged_at.is_(None),
                    Alert.auto_resolved_at.is_(None),
                    Alert.expired_at.is_(None),
                )
            )
            .values(expired_at=now, version=Alert.version + 1)
        )
        result = await self.db.execute(stmt)
        count = result.rowcount or 0
        if count:
            logger.info(
                "expired %d active alerts for event=%s", count, event_id,
            )
        return count

    # ── COUNTS (for top-bar badge, Dashboard red dots) ─────────────────────

    async def count_active(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> dict[str, int]:
        """Return {severity: count} for active alerts in an event.

        Used by:
        - Top-bar 'Alerts • 7' counter
        - Dashboard BarCard pulsing red dot decision
        - AlertsPage filter summary
        """
        stmt = (
            select(Alert.severity, func.count(Alert.id))
            .where(
                and_(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id == event_id,
                    Alert.acknowledged_at.is_(None),
                    Alert.auto_resolved_at.is_(None),
                    Alert.expired_at.is_(None),
                )
            )
            .group_by(Alert.severity)
        )
        rows = (await self.db.execute(stmt)).all()
        out = {"info": 0, "warning": 0, "critical": 0, "anomaly": 0}
        for severity, count in rows:
            out[severity] = count
        out["total"] = sum(out.values())
        return out

    async def count_active_by_bar(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> dict[UUID, dict[str, int]]:
        """Return {bar_id: {severity: count, 'total': N}} for Dashboard
        BarCard red-dot / badge rendering. One SQL round-trip for all bars.
        """
        stmt = (
            select(Alert.bar_id, Alert.severity, func.count(Alert.id))
            .where(
                and_(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id == event_id,
                    Alert.acknowledged_at.is_(None),
                    Alert.auto_resolved_at.is_(None),
                    Alert.expired_at.is_(None),
                )
            )
            .group_by(Alert.bar_id, Alert.severity)
        )
        rows = (await self.db.execute(stmt)).all()
        out: dict[UUID, dict[str, int]] = {}
        for bar_id, severity, count in rows:
            bucket = out.setdefault(
                bar_id,
                {"info": 0, "warning": 0, "critical": 0, "anomaly": 0, "total": 0},
            )
            bucket[severity] = count
            bucket["total"] += count
        return out