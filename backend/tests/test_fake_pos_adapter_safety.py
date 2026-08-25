"""Safety: the fake adapter can make NO outbound call and reads NO
Slesh setting — even when every Slesh variable is populated.

"No outbound call" is asserted, not assumed: the OS socket layer is
patched to raise on any connection attempt (socket.connect,
socket.create_connection, getaddrinfo), and the fake's entire surface —
all five contract methods, full event window consumed — runs under that
block. A control case proves the instrument works: the REAL adapter
under the same block, given dummy credentials, trips the alarm the
moment it tries to reach the provider.
"""
from __future__ import annotations

import inspect
import socket

import pytest

from app.core.config import settings

pytestmark = pytest.mark.asyncio


class _OutboundAttempt(Exception):
    pass


@pytest.fixture
def no_network(monkeypatch):
    """Raise on ANY attempt to open a network connection."""
    def _blocked(*args, **kwargs):
        raise _OutboundAttempt(f"outbound network attempted: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


async def test_control_the_block_catches_the_real_adapter(no_network):
    """Instrument check: the REAL adapter under the same socket block,
    with dummy credentials, must trip the alarm when used. If this test
    ever passes silently, the safety harness is broken and the fake's
    'no outbound call' result means nothing."""
    from app.modules.pos.adapters.slesh import SleshAdapter

    with pytest.raises(_OutboundAttempt):
        async with SleshAdapter(token="dummy", brand_id="0" * 24) as adapter:
            await adapter.verify_token()


async def test_fake_makes_no_outbound_call_even_with_slesh_settings_set(
    no_network, monkeypatch,
):
    """Populate every Slesh setting, select the fake through the factory
    (as staging does), and exercise the complete adapter surface under
    the socket block. Zero connection attempts — or _OutboundAttempt
    fails the test."""
    from datetime import datetime, timedelta

    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.fake import LOCAL_TZ, FakePOSAdapter

    monkeypatch.setattr(settings, "pos_adapter", "fake")
    monkeypatch.setattr(settings, "slesh_api_token", "leaked-token-must-not-matter")
    monkeypatch.setattr(settings, "slesh_brand_id", "f" * 24)
    monkeypatch.setattr(settings, "slesh_base_url", "https://api.slesh.it/api")

    adapter = get_pos_adapter()
    assert isinstance(adapter, FakePOSAdapter)

    since = datetime(2026, 9, 5, 16, 0, tzinfo=LOCAL_TZ)
    until = since + timedelta(hours=10)

    async with adapter:
        brand = await adapter.verify_token()
        shops = await adapter.list_shops()
        categories = await adapter.list_categories()
        products = await adapter.list_products()
        count = 0
        async for _order in adapter.list_orders(since, until, order_type=None):
            count += 1

    assert brand.id and shops and categories and products and count > 3000


def test_fake_module_reads_no_slesh_configuration():
    """Structural guarantee behind the runtime one: the fake's module
    imports neither the settings object nor an HTTP client, references
    no Slesh setting name in code (AST scan — docstrings and comments
    that merely DOCUMENT the rule don't count), and its constructor
    accepts no configuration — there is no parameter a mis-set variable
    could arrive through."""
    import ast

    import app.modules.pos.adapters.fake as fake_module

    tree = ast.parse(inspect.getsource(fake_module))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(m == "httpx" or m.startswith("httpx.") for m in imported), imported
    assert not any("app.core.config" in m for m in imported), imported

    identifiers = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    for forbidden in ("settings", "slesh_api_token", "slesh_brand_id", "slesh_base_url"):
        assert forbidden not in identifiers, forbidden

    params = inspect.signature(fake_module.FakePOSAdapter.__init__).parameters
    assert list(params) == ["self"], "FakePOSAdapter must take no configuration"
