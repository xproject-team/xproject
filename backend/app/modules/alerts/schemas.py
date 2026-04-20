"""Pydantic v2 request/response schemas for the Alerts module.

These schemas are the contract between the backend API and:
- Frontend TanStack Query hooks (1:1 mapped to TS interfaces)
- The evaluator/detector services (internal payload shapes)
- The future report generator (historical narrative source)

The field names MUST mirror the ORM model exactly; the frontend mockData.ts
will define TypeScript interfaces with the same names. Drift here breaks
the contract-first architecture.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums (literal-typed for runtime + IDE safety) ───────────────────────────
AlertType = Literal["depletion", "anomaly", "discrepancy", "system"]
AlertSeverity = Literal["info", "warning", "critical", "anomaly"]
AlertAudience = Literal["owner_only", "owner_and_manager"]
AlertLifecycleState = Literal["active", "acknowledged", "auto_resolved", "expired"]


# ─── Context sub-schemas (typed shapes for context_json per alert_type) ───────
# Each detector documents its expected context shape here. The column itself
# is JSONB, but typed schemas give the frontend + service layer confidence.


class AlertContextDepletion(BaseModel):
    """Context shape for alert_type='depletion'.

    Populated by DepletionEvaluator from the burn-rate endpoint output.
    """
    current_stock: float = Field(
        description="Units remaining at time of alert evaluation.",
    )
    burn_rate_per_hour: float = Field(
        description="Consumption rate used in the time-to-depletion math.",
    )
    ttd_minutes: float = Field(
        description="Time-to-depletion in minutes (current_stock / rate).",
    )
    window_label: str = Field(
        description="Which window produced the rate (last_30m / last_60m / "
                    "last_120m / event_wide).",
    )
    product_name: str | None = Field(
        default=None,
        description="Human-readable product name, snapshot at alert time.",
    )
    bar_name: str | None = Field(
        default=None,
        description="Human-readable bar name, snapshot at alert time.",
    )


# Future anomaly context schemas will live here — one per detector:
# class AlertContextConsumptionRatio(BaseModel): ...
# class AlertContextRevenueAnomaly(BaseModel): ...


# ─── Internal service-layer payload ───────────────────────────────────────────
# Not exposed via API. Used by AlertsService.create_alert().


class AlertCreate(BaseModel):
    """Internal payload for creating an alert from the evaluator.

    Tenant_id comes from the evaluator's execution context, not this payload,
    to prevent cross-tenant leaks.
    """
    event_id: UUID
    bar_id: UUID
    product_id: UUID | None = None
    alert_type: AlertType
    severity: AlertSeverity
    audience: AlertAudience
    title: str = Field(max_length=160)
    owner_message: str
    manager_message: str | None = None
    suggested_action: str | None = None
    context_json: dict[str, Any] = Field(default_factory=dict)


# ─── Request schemas (HTTP bodies) ────────────────────────────────────────────


class AlertAcknowledge(BaseModel):
    """Body for PATCH /alerts/{id}/acknowledge.

    The version field implements optimistic locking — if the alert has been
    modified since the client loaded it, the service returns 409 Conflict and
    the client must refetch.
    """
    version: int = Field(
        description="Current version known to the client. Service returns "
                    "409 if the DB has a newer version.",
    )


# ─── Response schemas ─────────────────────────────────────────────────────────


class AlertResponse(BaseModel):
    """Single alert as exposed via the API.

    Shape is identical whether the reader is Owner or Manager — but the
    response is filtered at the service/router layer based on:
    - Manager: audience must be 'owner_and_manager' AND their bar_id must
      match; they see manager_message, not owner_message.
    - Owner: sees everything tenant-scoped; reads owner_message.
    Never mixed in one response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_id: UUID
    bar_id: UUID
    product_id: UUID | None

    alert_type: AlertType
    severity: AlertSeverity
    audience: AlertAudience

    title: str
    # For owner responses this carries owner_message; for manager responses it
    # carries manager_message. Router-level transformation keeps the frontend
    # contract simple (one `message` field).
    message: str
    suggested_action: str | None
    ai_advisory: str | None
    context_json: dict[str, Any]

    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None
    auto_resolved_at: datetime | None
    expired_at: datetime | None

    lifecycle_state: AlertLifecycleState
    version: int


class AlertListResponse(BaseModel):
    """Paginated list response for /alerts list endpoints.

    Total is the full count matching the filter (not just the page), so the
    frontend can render 'X of Y active alerts' without a second query.
    """
    items: list[AlertResponse]
    total: int


# ─── Acknowledge response (explicit type for clarity) ─────────────────────────


class AlertAcknowledgeResponse(BaseModel):
    """Returned by PATCH /alerts/{id}/acknowledge on success.

    Separate from AlertResponse so the frontend has a narrow type signal
    for 'ack succeeded' vs generic reads.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    acknowledged_at: datetime
    acknowledged_by_user_id: UUID
    version: int
    lifecycle_state: AlertLifecycleState