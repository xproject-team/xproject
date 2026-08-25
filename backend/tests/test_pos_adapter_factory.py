"""POS adapter factory — one construction seam for every app code path.

Staging runs a fake POS adapter serving provider-shaped payloads from
generated data; production keeps the real one. Selection is the
POS_ADAPTER setting: "slesh" (default — production behavior unchanged
with the variable absent) or "fake". All app construction sites route
through get_pos_adapter(); a mis-set Slesh variable can never reach the
fake because the factory constructs it with no Slesh settings at all.

Written FIRST, before the factory existed, per the failing-test rule.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


def test_default_selects_slesh_adapter(monkeypatch):
    """POS_ADAPTER unset (field default 'slesh') → the real adapter,
    constructed exactly as production constructs it today."""
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.slesh import SleshAdapter

    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    adapter = get_pos_adapter()
    assert isinstance(adapter, SleshAdapter)


def test_fake_selects_fake_adapter(monkeypatch):
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.fake import FakePOSAdapter

    monkeypatch.setattr(settings, "pos_adapter", "fake")
    adapter = get_pos_adapter()
    assert isinstance(adapter, FakePOSAdapter)


def test_unknown_value_raises_a_clear_error(monkeypatch):
    from app.modules.pos.adapters.factory import get_pos_adapter

    monkeypatch.setattr(settings, "pos_adapter", "sandbox")
    with pytest.raises(ValueError) as exc:
        get_pos_adapter()
    # The error must name the bad value and the accepted ones — this is
    # the message an operator sees after a typo in a service variable.
    assert "sandbox" in str(exc.value)
    assert "slesh" in str(exc.value) and "fake" in str(exc.value)


def test_selection_is_case_and_whitespace_tolerant(monkeypatch):
    """' Fake ' from a hand-typed dashboard variable must still select
    the fake — a silent fallback to the real adapter on sloppy input
    would point staging at the live provider."""
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.fake import FakePOSAdapter

    monkeypatch.setattr(settings, "pos_adapter", " Fake ")
    assert isinstance(get_pos_adapter(), FakePOSAdapter)


def test_dead_posservice_is_gone():
    """pos/service.py held a stub POSService constructing SleshAdapter()
    with no credentials; nothing imported it (verified repo-wide). It is
    deleted rather than routed through the factory — dead code carrying
    an adapter construction is exactly what the factory must not leave
    behind."""
    with pytest.raises(ModuleNotFoundError):
        import app.modules.pos.service  # noqa: F401
