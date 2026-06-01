"""Event state machine — single source of truth for status transitions.

See docs/backend-contract.md §2 for the full specification.

Rules:
- Transitions are one-way (no rollback from Completed to Live, etc).
- COMPLETED and CANCELLED are terminal states.
- All transitions must go through assert_transition_allowed() before
  touching the DB. This function raises a 409-mapped exception on invalid
  transitions, which the router translates to HTTPException.

Contract references:
  §2.1 — States
  §2.2 — Allowed transitions
  §2.3 — Invariant: one live event per tenant (enforced in service layer)
  §2.5 — Idempotency (idempotent transitions return current state, no error)
"""
from app.modules.events.models import EventStatus


# ─── Allowed transitions ──────────────────────────────────────────────────────
# Keys: current status. Values: set of statuses we can transition TO.

ALLOWED_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.DRAFT:     {EventStatus.ACTIVE, EventStatus.CANCELLED},
    EventStatus.ACTIVE:    {EventStatus.LIVE, EventStatus.CANCELLED},
    EventStatus.LIVE:      {EventStatus.COMPLETED},
    EventStatus.COMPLETED: set(),  # terminal
    EventStatus.CANCELLED: set(),  # terminal
}


# ─── Fields editable per status ───────────────────────────────────────────────
# Contract §3. Enforced by service layer before calling repository.update().

EDITABLE_FIELDS_PER_STATUS: dict[EventStatus, set[str]] = {
    EventStatus.DRAFT:     {"name", "venue_id", "scheduled_at", "scheduled_end_at",
                            "expected_guest_count", "ended_at"},
    EventStatus.ACTIVE:    {"name", "venue_id", "scheduled_at", "scheduled_end_at",
                            "expected_guest_count", "ended_at"},
    EventStatus.LIVE:      {"name", "expected_guest_count", "ended_at"},  # limited
    EventStatus.COMPLETED: set(),  # immutable
    EventStatus.CANCELLED: set(),  # immutable
}


# ─── Domain exceptions ────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed.

    Mapped by router to HTTP 409 Conflict.
    """
    def __init__(
        self,
        from_status: EventStatus,
        to_status: EventStatus,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition event from {from_status.value} to {to_status.value}"
        )


class FieldLockedError(Exception):
    """Raised when a client tries to edit a field that is locked in the current status.

    Mapped by router to HTTP 409 Conflict.
    """
    def __init__(self, field: str, status: EventStatus) -> None:
        self.field = field
        self.status = status
        super().__init__(
            f"Field '{field}' cannot be edited while event is in status '{status.value}'"
        )


# ─── Guard functions ──────────────────────────────────────────────────────────

def assert_transition_allowed(
    from_status: EventStatus,
    to_status: EventStatus,
) -> None:
    """Raise InvalidTransitionError if the transition is not allowed.

    Idempotent no-op: if from == to, return silently. This matches contract §2.5
    (calling /start on an already-Live event returns current state, no error).
    """
    if from_status == to_status:
        return  # idempotent
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidTransitionError(from_status, to_status)


def assert_fields_editable(
    status: EventStatus,
    fields_to_edit: set[str],
) -> None:
    """Raise FieldLockedError if any field is not editable in the current status.

    Call this in PATCH /events/{id} after the client payload has been
    reduced to only the non-null fields they intend to change.
    """
    editable = EDITABLE_FIELDS_PER_STATUS[status]
    for field in fields_to_edit:
        if field not in editable:
            raise FieldLockedError(field, status)
