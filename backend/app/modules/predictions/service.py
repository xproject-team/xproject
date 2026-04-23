"""Business logic for the Predictions module — orchestrates the full flow.

Contract reference: §1.1 (layered architecture), §1.5 (service owns transactions).

The service layer:
  1. Validates tenant scoping (never trusts router to filter by tenant).
  2. Chooses the predictor engine (MLPredictor if ready, else Heuristic).
  3. Orchestrates: repository.create → predictor.predict → repository.mark_*
  4. Handles generation failures: catches exceptions from predictors, marks
     row failed with reason, then re-raises so the caller sees the error.
  5. Owns the transaction boundary: repositories flush, services commit.
  6. Translates domain concerns into typed exceptions; router maps them to
     HTTP status codes.

Spec: docs/predictions-module-spec.md §5 + §6 + §7.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.models import Prediction
from app.modules.predictions.predictors import (
    BasePredictor,
    HeuristicPredictor,
    MLPredictor,
)
from app.modules.predictions.repository import PredictionRepository
from app.modules.predictions.schemas import (
    PredictionData,
    PredictionInsufficientData,
)


# ─── Domain exceptions ────────────────────────────────────────────────────────
# Router layer maps each to the appropriate HTTP status code.

class PredictionNotFoundError(Exception):
    """Prediction does not exist OR belongs to a different tenant. Maps to 404."""


class PredictionGenerationError(Exception):
    """Predictor engine crashed during generation.
    The row has been marked `failed` with a reason; caller gets 500.
    """


class PredictionService:
    """All business logic for prediction operations.

    Services commit transactions. Repositories only flush. This lets one
    service call orchestrate multiple repo operations atomically.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PredictionRepository(db)

    # ─── Engine selection ────────────────────────────────────────────────────

    async def _select_predictor(self, tenant_id: UUID) -> BasePredictor:
        """Choose which predictor to use for this tenant.

        v1.0 policy: if MLPredictor.is_ready returns True (Track 2), use it.
        Otherwise fall back to HeuristicPredictor. Today this always returns
        HeuristicPredictor because MLPredictor.is_ready is hardcoded False.

        Track 2: MLPredictor.is_ready gets real logic and this function
        starts preferring ML when the tenant has enough training data.
        """
        ml = MLPredictor(self.db)
        if await ml.is_ready(tenant_id):
            return ml
        return HeuristicPredictor(self.db)

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_prediction(
        self, tenant_id: UUID, prediction_id: UUID
    ) -> Prediction:
        """Fetch a single prediction. Raises PredictionNotFoundError if missing."""
        prediction = await self.repo.get_by_id(tenant_id, prediction_id)
        if prediction is None:
            raise PredictionNotFoundError(f"Prediction {prediction_id} not found")
        return prediction

    async def get_latest_for_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> Prediction | None:
        """Get the latest prediction for an event, or None if never generated.

        Returns None (not an exception) because 'no prediction yet' is a
        valid state — the UI renders a 'Generate Predictions' CTA for it.
        """
        return await self.repo.get_latest_for_event(tenant_id, event_id)

    async def list_history(
        self, tenant_id: UUID, event_id: UUID
    ) -> Sequence[Prediction]:
        """All prediction versions for an event, newest first."""
        return await self.repo.list_for_event(tenant_id, event_id)

    # ─── Generation (on-demand) ──────────────────────────────────────────────

    async def generate_on_demand(
        self,
        tenant_id: UUID,
        event_id: UUID,
        generated_by: UUID | None = None,
    ) -> Prediction:
        """User clicks 'Generate Predictions' → creates & populates a new row.

        Idempotency: if a `ready` or `insufficient_data` prediction already
        exists for (event, latest version) AND the event config hasn't
        changed since, returns the existing row instead of creating a duplicate.

        Propagates predictor errors as PredictionGenerationError after
        marking the row failed.
        """
        existing = await self.repo.get_latest_for_event(tenant_id, event_id)
        # Idempotency: if latest is in a terminal non-failed state, return it.
        # (Owner can still force regeneration via POST /regenerate.)
        if existing is not None and existing.status in ("ready", "insufficient_data"):
            return existing

        version = (existing.version + 1) if existing is not None else 1
        predictor = await self._select_predictor(tenant_id)

        prediction = await self.repo.create(
            tenant_id=tenant_id,
            event_id=event_id,
            predictor_type=predictor.predictor_type,
            version=version,
            generated_by=generated_by,
        )

        return await self._populate_prediction(prediction, predictor)

    # ─── Regeneration (admin-only, creates v+1) ──────────────────────────────

    async def regenerate(
        self,
        tenant_id: UUID,
        prediction_id: UUID,
        *,
        generated_by: UUID | None = None,
    ) -> Prediction:
        """Create a fresh version of an existing prediction.

        Sets old.superseded_by = new.id. Old row is NEVER deleted (audit trail).
        Used by Owner to force a refresh when configuration changed or the
        previous prediction looked wrong.
        """
        old = await self.repo.get_by_id(tenant_id, prediction_id)
        if old is None:
            raise PredictionNotFoundError(f"Prediction {prediction_id} not found")

        predictor = await self._select_predictor(tenant_id)
        new_version = old.version + 1

        new = await self.repo.create(
            tenant_id=tenant_id,
            event_id=old.event_id,
            predictor_type=predictor.predictor_type,
            version=new_version,
            generated_by=generated_by,
        )
        await self.repo.supersede(old, new.id)

        return await self._populate_prediction(new, predictor)

    # ─── Auto-regen (called by EventService on config change) ────────────────

    async def trigger_auto_regen_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Prediction | None:
        """Fire-and-forget regeneration triggered by event config changes.

        Called by EventService.update_event when fields that affect predictions
        are mutated (bars list, expected_guest_count, menu, stock). This method
        SWALLOWS failures — predictions are a nice-to-have; a failure here
        must never break the event update that triggered it.

        Returns the new prediction row if generation succeeded, or None if
        there was no existing prediction (nothing to regenerate) or if
        something went wrong.
        """
        try:
            existing = await self.repo.get_latest_for_event(tenant_id, event_id)
            if existing is None:
                # No prior prediction — don't force a generation, just skip.
                # User can click 'Generate Predictions' when ready.
                return None

            # Create v+1 and regenerate
            predictor = await self._select_predictor(tenant_id)
            new = await self.repo.create(
                tenant_id=tenant_id,
                event_id=event_id,
                predictor_type=predictor.predictor_type,
                version=existing.version + 1,
                generated_by=None,   # system-triggered
            )
            await self.repo.supersede(existing, new.id)
            return await self._populate_prediction(new, predictor)
        except Exception:
            # Soft failure — never bubble up to the caller (EventService).
            # The prior prediction (if any) remains the latest-ready.
            return None

    # ─── Private: the generation pipeline ────────────────────────────────────

    async def _populate_prediction(
        self,
        prediction: Prediction,
        predictor: BasePredictor,
    ) -> Prediction:
        """Runs mark_generating → predictor.predict → mark_{ready|insufficient|failed}.

        Three terminal paths:
          - PredictionData returned → mark_ready with the snapshot
          - PredictionInsufficientData returned → mark_insufficient_data
            (valid outcome, NOT an error)
          - Exception raised → mark_failed + re-raise as PredictionGenerationError

        The row is committed after every terminal transition so the status
        is durable even if the caller's transaction later rolls back.
        """
        try:
            await self.repo.mark_generating(prediction)

            result = await predictor.predict(
                tenant_id=prediction.tenant_id,
                event_id=prediction.event_id,
            )

            if isinstance(result, PredictionInsufficientData):
                await self.repo.mark_insufficient_data(
                    prediction,
                    message=result.user_message,
                    events_available=result.events_available,
                )
                await self.db.commit()
                return prediction

            # It's a PredictionData — overwrite the prediction_id + version
            # fields to match the row we just created (predictor doesn't know
            # these until the service creates the row).
            result_with_ids = result.model_copy(update={
                "prediction_id": prediction.id,
                "version": prediction.version,
            })
            data_json = result_with_ids.model_dump(mode="json")

            await self.repo.mark_ready(
                prediction,
                data_json=data_json,
                based_on_event_count=result_with_ids.based_on_event_count,
                confidence_tier=result_with_ids.confidence_tier,
            )
            await self.db.commit()
            return prediction

        except Exception as exc:
            # Predictor crash — persist the failure for diagnostics, then
            # surface as PredictionGenerationError.
            await self.repo.mark_failed(
                prediction,
                reason=f"{type(exc).__name__}: {exc}",
            )
            await self.db.commit()
            raise PredictionGenerationError(
                f"Prediction generation failed for {prediction.id}: {exc}"
            ) from exc
