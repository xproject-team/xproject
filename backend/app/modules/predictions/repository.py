"""Database queries for the predictions module — pure data access, no business logic.

This file owns ALL SQL for the predictions domain. Services never write SQL.
Transaction boundaries are OWNED BY SERVICES — every method here flushes
but NEVER commits.

Spec: docs/predictions-module-spec.md §4 + §6.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus
from app.modules.predictions.models import Prediction


class PredictionRepository:
    """Handles all SQL operations for Prediction records.

    Tenant isolation is NON-NEGOTIABLE — every public method takes tenant_id
    as the first argument and filters at SQL level. A missing tenant_id filter
    is a security bug; reviewers should fail the PR.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        tenant_id: UUID,
        prediction_id: UUID,
    ) -> Prediction | None:
        """Fetch a single prediction by ID, scoped to tenant."""
        stmt = (
            select(Prediction)
            .where(
                Prediction.tenant_id == tenant_id,
                Prediction.id == prediction_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Prediction | None:
        """Return the highest-version prediction for (tenant, event).

        Powers GET /predictions/events/{event_id} — the 'what's the current
        prediction for this event' query. Also used by the on-demand
        generation path for idempotency (if latest is already 'ready', return
        it instead of creating a duplicate when nothing has changed).
        """
        stmt = (
            select(Prediction)
            .where(
                Prediction.tenant_id == tenant_id,
                Prediction.event_id == event_id,
            )
            .order_by(Prediction.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Sequence[Prediction]:
        """All prediction versions for an event, newest first.

        Powers GET /predictions/events/{event_id}/history — shows the full
        audit trail including superseded versions.
        """
        stmt = (
            select(Prediction)
            .options(selectinload(Prediction.event))
            .where(
                Prediction.tenant_id == tenant_id,
                Prediction.event_id == event_id,
            )
            .order_by(Prediction.version.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_historical_completed_events(
        self,
        tenant_id: UUID,
        exclude_event_id: UUID | None = None,
        limit: int = 50,
    ) -> Sequence[Event]:
        """Return completed events used as training data for predictions.

        Called by HeuristicPredictor to compute per-guest averages.
        Excludes the event being predicted so we don't leak its own data
        into the prediction inputs.

        Only COMPLETED events with started_at + ended_at populated qualify.
        Ordered by ended_at DESC so recent events weight the prediction
        more heavily (if the predictor cares about recency).
        """
        stmt = (
            select(Event)
            .where(
                Event.tenant_id == tenant_id,
                Event.status == EventStatus.COMPLETED,
                Event.started_at.is_not(None),
                Event.ended_at.is_not(None),
            )
            .order_by(Event.ended_at.desc())
            .limit(limit)
        )
        if exclude_event_id is not None:
            stmt = stmt.where(Event.id != exclude_event_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    # ─── Writes (pending/generating/ready/failed/insufficient_data lifecycle) ─

    async def create(
        self,
        tenant_id: UUID,
        event_id: UUID,
        predictor_type: str = "heuristic",
        version: int = 1,
        generated_by: UUID | None = None,
    ) -> Prediction:
        """Insert a new prediction row with status=pending.

        Service layer is responsible for resolving the correct version —
        typically 1 for first generation, or previous.version+1 for regenerate.
        Flushes to assign id + populate server-side defaults. Does NOT commit.
        """
        prediction = Prediction(
            tenant_id=tenant_id,
            event_id=event_id,
            predictor_type=predictor_type,
            version=version,
            status="pending",
            generated_by=generated_by,
        )
        self.db.add(prediction)
        await self.db.flush()
        await self.db.refresh(prediction)
        return prediction

    async def mark_generating(self, prediction: Prediction) -> Prediction:
        """Transition pending → generating. Flushes but does not commit."""
        prediction.status = "generating"
        await self.db.flush()
        await self.db.refresh(prediction)
        return prediction

    async def mark_ready(
        self,
        prediction: Prediction,
        data_json: dict,
        based_on_event_count: int,
        confidence_tier: str,
    ) -> Prediction:
        """Transition generating → ready, writes the frozen snapshot.

        Also records how many historical events informed this prediction
        and the confidence tier (low/medium/high). These appear in the
        Summary response so the UI can show 'Based on N past events · low
        confidence' honestly.
        Flushes but does not commit.
        """
        prediction.status = "ready"
        prediction.data_json = data_json
        prediction.based_on_event_count = based_on_event_count
        prediction.confidence_tier = confidence_tier
        prediction.generated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(prediction)
        return prediction

    async def mark_insufficient_data(
        self,
        prediction: Prediction,
        message: str,
        events_available: int,
    ) -> Prediction:
        """Transition * → insufficient_data.

        NOT an error — a valid terminal state. Happens when history is below
        the predictor's minimum threshold (zero-history case on day 1).
        Frontend renders the calm empty state; user can regenerate later
        once more events have completed.
        Flushes but does not commit.
        """
        prediction.status = "insufficient_data"
        prediction.insufficient_data_message = message
        prediction.based_on_event_count = events_available
        prediction.generated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(prediction)
        return prediction

    async def mark_failed(
        self,
        prediction: Prediction,
        reason: str,
    ) -> Prediction:
        """Transition * → failed with a human-readable reason.

        No auto-retry — service layer surfaces the error to the caller.
        Manual retry via POST /predictions/{id}/regenerate creates a NEW
        row with version+1.
        Flushes but does not commit.
        """
        prediction.status = "failed"
        prediction.failure_reason = reason
        await self.db.flush()
        await self.db.refresh(prediction)
        return prediction

    async def supersede(
        self,
        old_prediction: Prediction,
        new_prediction_id: UUID,
    ) -> Prediction:
        """Point old_prediction.superseded_by at new_prediction_id.

        Called during regeneration AFTER the new row is created but BEFORE
        we enqueue its generation job. The old row's status is unchanged —
        it remains in whatever terminal state it reached. The CHECK constraint
        ck_predictions_no_self_supersede prevents accidental self-reference.
        Flushes but does not commit.
        """
        old_prediction.superseded_by = new_prediction_id
        await self.db.flush()
        await self.db.refresh(old_prediction)
        return old_prediction
