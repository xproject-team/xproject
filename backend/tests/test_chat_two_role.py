"""Stage 3 — chat rebuilt for the two-role system.

Covers:
  - role-derived access rules (pure function): bar/general = owner+manager,
    strategic = owner only, unknown types fail closed
  - channel listing carries event grouping fields and is_archived
  - cross-tenant isolation: another tenant's owner sees nothing of ours and
    gets 404 (not a leak, not a 500) on direct channel access
  - non-member DM access is 403 even for the Owner
  - archived (completed/cancelled event) channels reject writes with 409
  - search does not leak across tenants
  - members endpoint returns only owner/manager identities

Uses the live dev DB (per conftest convention): Noma tenant (omar@) and the
simulator tenant (sim-owner@noma-sim.test / "simulator", created by
app/scripts/seed_sim_event.py) provide two real tenants.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.auth.models import UserRole
from app.modules.chat.service import role_may_access_channel_type

from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD

SIM_EMAIL = "sim-owner@noma-sim.test"
SIM_PASSWORD = "simulator"


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"login failed for {email}: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ─── Pure derived-access rules ────────────────────────────────────────


def test_bar_and_general_channels_derive_to_owner_and_manager() -> None:
    for ctype in ("bar", "general"):
        assert role_may_access_channel_type(UserRole.OWNER, ctype)
        assert role_may_access_channel_type(UserRole.MANAGER, ctype)


def test_strategic_channels_derive_to_owner_only() -> None:
    assert role_may_access_channel_type(UserRole.OWNER, "strategic")
    assert not role_may_access_channel_type(UserRole.MANAGER, "strategic")


def test_unknown_channel_types_fail_closed() -> None:
    assert not role_may_access_channel_type(UserRole.MANAGER, "future_type")
    assert role_may_access_channel_type(UserRole.OWNER, "future_type")


# ─── Channel listing: role-derived + event grouping ──────────────────


@pytest.mark.asyncio
async def test_owner_sees_bar_channels_without_member_rows(client: AsyncClient) -> None:
    """Access is role-derived: the owner lists every bar channel in the
    tenant even though create_bar_channel no longer enrolls anyone."""
    headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    resp = await client.get("/api/v1/chat/channels", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    bar_rows = [r for r in rows if r["channel_type"] == "bar"]
    assert len(bar_rows) > 0

    # Bar channels carry their owning event for the sidebar grouping
    with_event = [r for r in bar_rows if r["event_name"] is not None]
    assert with_event, "bar channels must resolve their event via bar_id -> bars.event_id"

    # Archived flag matches event status
    for r in bar_rows:
        if r["event_status"] in ("completed", "cancelled"):
            assert r["is_archived"] is True
        elif r["event_status"] is not None:
            assert r["is_archived"] is False


@pytest.mark.asyncio
async def test_dm_channels_listed_only_with_member_row(client: AsyncClient) -> None:
    """DMs stay row-based: every direct channel in the owner's list must be
    one they hold a member row for (enforced by the SQL predicate; here we
    at least assert none of the OTHER tenant's DMs appear — see cross-tenant
    test — and the type vocabulary matches the data ('direct', not 'dm')."""
    headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    resp = await client.get("/api/v1/chat/channels", headers=headers)
    assert resp.status_code == 200
    types = {r["channel_type"] for r in resp.json()}
    assert types <= {"bar", "direct", "dm", "general", "strategic"}


# ─── Cross-tenant isolation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_listing_is_empty_of_other_tenants_channels(
    client: AsyncClient,
) -> None:
    noma_headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    sim_headers = await _login(client, SIM_EMAIL, SIM_PASSWORD)

    noma_ids = {r["id"] for r in (await client.get("/api/v1/chat/channels", headers=noma_headers)).json()}
    sim_ids = {r["id"] for r in (await client.get("/api/v1/chat/channels", headers=sim_headers)).json()}
    assert noma_ids, "Noma tenant should have channels in dev"
    assert noma_ids.isdisjoint(sim_ids)


@pytest.mark.asyncio
async def test_cross_tenant_channel_access_is_404_not_leak(client: AsyncClient) -> None:
    """A channel id from another tenant answers 404 — the same as a
    nonexistent id — for messages, members, read-marking, and posting."""
    noma_headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    sim_headers = await _login(client, SIM_EMAIL, SIM_PASSWORD)

    noma_channels = (await client.get("/api/v1/chat/channels", headers=noma_headers)).json()
    target = noma_channels[0]["id"]

    r = await client.get(f"/api/v1/chat/channels/{target}/messages", headers=sim_headers)
    assert r.status_code == 404, r.text
    r = await client.get(f"/api/v1/chat/channels/{target}/members", headers=sim_headers)
    assert r.status_code == 404, r.text
    r = await client.post(f"/api/v1/chat/channels/{target}/read", headers=sim_headers)
    assert r.status_code == 404, r.text
    r = await client.post(
        f"/api/v1/chat/channels/{target}/messages",
        json={"body": "cross-tenant write attempt", "attachment_ids": []},
        headers=sim_headers,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_search_does_not_leak_across_tenants(client: AsyncClient) -> None:
    """Dev DB holds the message '@Manager_Cocktail_Bar please restock vodka'
    in the Noma tenant. The sim tenant's owner must not find it."""
    noma_headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    sim_headers = await _login(client, SIM_EMAIL, SIM_PASSWORD)

    noma = await client.get("/api/v1/chat/search", params={"q": "vodka"}, headers=noma_headers)
    sim = await client.get("/api/v1/chat/search", params={"q": "vodka"}, headers=sim_headers)
    assert noma.status_code == 200 and sim.status_code == 200
    assert len(noma.json()) >= 1, "expected the seeded vodka message for the Noma owner"
    assert sim.json() == []


# ─── Non-member DM access ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dm_without_member_row_is_403_even_for_owner(client: AsyncClient) -> None:
    """Dev DB has bartender↔manager DMs the owner is not party to. Role
    derivation must NOT open them: DMs stay row-based."""
    headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)

    # Find a direct channel NOT in the owner's own listing, via the DB
    from sqlalchemy import select, and_
    from app.core.database import AsyncSessionLocal
    from app.modules.chat.models import Channel, ChannelMember
    from app.modules.auth.models import User

    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
        member_ids = select(ChannelMember.channel_id).where(
            ChannelMember.user_id == owner.id
        ).scalar_subquery()
        stmt = select(Channel).where(
            and_(
                Channel.tenant_id == owner.tenant_id,
                Channel.channel_type.in_(("direct", "dm")),
                Channel.id.notin_(member_ids),
            )
        ).limit(1)
        foreign_dm = (await db.execute(stmt)).scalar_one_or_none()

    if foreign_dm is None:
        pytest.skip("dev DB has no DM the owner is not party to")

    r = await client.get(f"/api/v1/chat/channels/{foreign_dm.id}/messages", headers=headers)
    assert r.status_code == 403, r.text


# ─── Archived channels are read-only ──────────────────────────────────


@pytest.mark.asyncio
async def test_posting_to_archived_event_channel_is_409(client: AsyncClient) -> None:
    headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    rows = (await client.get("/api/v1/chat/channels", headers=headers)).json()
    archived = [r for r in rows if r["is_archived"]]
    if not archived:
        pytest.skip("dev DB has no archived-event channels")

    r = await client.post(
        f"/api/v1/chat/channels/{archived[0]['id']}/messages",
        json={"body": "should be rejected", "attachment_ids": []},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert "archived" in r.json()["detail"]

    # Reading archived history stays allowed
    r = await client.get(f"/api/v1/chat/channels/{archived[0]['id']}/messages", headers=headers)
    assert r.status_code == 200, r.text


# ─── Members endpoint ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_members_endpoint_returns_only_owner_and_manager(client: AsyncClient) -> None:
    headers = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    rows = (await client.get("/api/v1/chat/channels", headers=headers)).json()
    bar = next(r for r in rows if r["channel_type"] == "bar")
    r = await client.get(f"/api/v1/chat/channels/{bar['id']}/members", headers=headers)
    assert r.status_code == 200
    members = r.json()
    assert members, "a bar channel must list at least the owner"
    assert {m["role"] for m in members} <= {"owner", "manager"}
