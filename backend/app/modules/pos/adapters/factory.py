"""POS adapter factory — the single construction seam for the app.

Every application code path that needs a POS adapter (order poller,
bars sync cron, event-wizard shop list) calls get_pos_adapter() instead
of constructing SleshAdapter directly. Selection is settings.pos_adapter
(env POS_ADAPTER):

  "slesh"  — the real provider adapter, constructed from the Slesh
             settings exactly as the call sites did before the factory
             existed. This is the default, so production — which does
             not set POS_ADAPTER — is byte-for-byte unchanged.
  "fake"   — FakePOSAdapter serving provider-shaped payloads from
             generated data (staging). Constructed with NO Slesh
             settings whatsoever: a mis-set SLESH_* variable cannot
             leak into it because nothing is passed in.

Ops scripts (backfills, reference sync) intentionally keep constructing
SleshAdapter directly — they are provider-specific tools that must never
run against generated data.

pos_adapter_configured() is the cron guard: "is a POS adapter configured
and usable?" — replacing the old direct check on slesh_api_token, which
made it impossible for a token-less staging to exercise the ingestion
path at all.
"""
from __future__ import annotations

from app.core.config import settings
from app.modules.pos.adapters.base import BasePOSAdapter

# Brand identifier the fake adapter answers for. slesh_poll_state rows
# are keyed by brand_id, so the fake needs a stable one for the poll
# cursor machinery to work exactly as it does against the real provider.
FAKE_BRAND_ID = "fakebrand000000000000fa9e"

_VALID = ("slesh", "fake")


def _selected() -> str:
    return (settings.pos_adapter or "slesh").strip().lower()


def pos_adapter_configured() -> bool:
    """True when a POS adapter can actually be used.

    "fake" needs no credentials — it is always usable. "slesh" is usable
    only with an API token. An unknown selection reports unconfigured
    (the crons then skip; the loud ValueError surfaces on explicit use).
    """
    kind = _selected()
    if kind == "fake":
        return True
    if kind == "slesh":
        return bool(settings.slesh_api_token)
    return False


def default_brand_id() -> str:
    """Brand id for poll-state scoping when the caller has none."""
    return FAKE_BRAND_ID if _selected() == "fake" else settings.slesh_brand_id


def get_pos_adapter(*, brand_id: str | None = None) -> BasePOSAdapter:
    """Construct the selected POS adapter (an async context manager).

    brand_id: optional override for the real adapter (the poller passes
    the brand from its cursor row). Ignored by the fake — it has exactly
    one brand, FAKE_BRAND_ID.
    """
    kind = _selected()

    if kind == "slesh":
        from app.modules.pos.adapters.slesh import SleshAdapter

        return SleshAdapter(
            token=settings.slesh_api_token,
            brand_id=brand_id or settings.slesh_brand_id,
            base_url=settings.slesh_base_url,
            request_timeout=settings.slesh_request_timeout,
            rate_limit_rps=settings.slesh_rate_limit_rps,
            max_retries=settings.slesh_max_retries,
        )

    if kind == "fake":
        from app.modules.pos.adapters.fake import FakePOSAdapter

        # Deliberately constructed with nothing: the fake must never
        # see a Slesh setting, so a mis-set variable cannot leak in.
        return FakePOSAdapter()

    raise ValueError(
        f"Unknown POS_ADAPTER value {settings.pos_adapter!r} — "
        f"expected one of {_VALID!r}. Fix the service variable; "
        "refusing to guess which provider to talk to."
    )
