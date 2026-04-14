"""Idempotent seeder for the XProject communication tree.

Creates the hierarchical chat structure:

    Owner-Managers Chat  ──  Omar + 3 Managers
    Bar Team: Cocktail   ──  Manager.cocktail + 2 Bartenders (Marco, Luca)
    Bar Team: Focacceria ──  Manager.focacceria + 2 Bartenders (Giulia, Sofia)
    Bar Team: Malandrino ──  Manager.malandrino + 1 Bartender (Paolo)

Rules enforced:
  - Omar is NOT in any Bar Team chat (hierarchy: Omar → Managers only)
  - Bartenders are ONLY in their own Bar Team chat (cannot reach Omar directly)
  - Managers bridge the two layers (strategic + operational)

Run:  python -m app.seeds.communication_tree
"""
import asyncio
from uuid import UUID

from sqlalchemy import select, delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.bars.models import Bar            # noqa: F401 (register FK target)
from app.modules.chat.models import Channel, ChannelMember


# Bar IDs — will lookup by name for portability
BARTENDERS = [
    ("bartender.marco@nomagroup.it",   "Marco Rossi",      "Cocktail Bar"),
    ("bartender.luca@nomagroup.it",    "Luca Bianchi",     "Cocktail Bar"),
    ("bartender.giulia@nomagroup.it",  "Giulia Esposito",  "Focacceria"),
    ("bartender.sofia@nomagroup.it",   "Sofia Romano",     "Focacceria"),
    ("bartender.paolo@nomagroup.it",   "Paolo Ferrari",    "Malandrino"),
]
BARTENDER_PASSWORD = "bartender123"

CHANNEL_RENAMES = {
    "Cocktail Bar Chat":  "Bar Team: Cocktail",
    "Focacceria Chat":    "Bar Team: Focacceria",
    "Malandrino Chat":    "Bar Team: Malandrino",
}
BAR_TO_CHANNEL = {
    "Cocktail Bar": "Bar Team: Cocktail",
    "Focacceria":   "Bar Team: Focacceria",
    "Malandrino":   "Bar Team: Malandrino",
}


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # ── Load existing users + bars ──
        omar = (await db.execute(
            select(User).where(User.email == "omar@nomagroup.it")
        )).scalar_one()
        tenant_id = omar.tenant_id

        bars = {b.name: b for b in (await db.execute(select(Bar))).scalars().all()}

        managers_by_bar: dict[str, User] = {}
        for email, bar_name in [
            ("manager.cocktail@nomagroup.it",   "Cocktail Bar"),
            ("manager.focacceria@nomagroup.it", "Focacceria"),
            ("manager.malandrino@nomagroup.it", "Malandrino"),
        ]:
            m = (await db.execute(select(User).where(User.email == email))).scalar_one()
            managers_by_bar[bar_name] = m

        print(f"Tenant: {tenant_id} | Owner: {omar.full_name}")

        # ── 1. Seed bartenders (idempotent) ──
        bartenders_by_bar: dict[str, list[User]] = {bar: [] for bar in BAR_TO_CHANNEL}
        for email, full_name, bar_name in BARTENDERS:
            existing = (await db.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if existing:
                bartenders_by_bar[bar_name].append(existing)
                continue

            new_bt = User(
                email=email,
                hashed_password=hash_password(BARTENDER_PASSWORD),
                full_name=full_name,
                role=UserRole.BARTENDER,
                is_active=True,
                bar_id=bars[bar_name].id,
                tenant_id=tenant_id,
            )
            db.add(new_bt)
            await db.flush()
            bartenders_by_bar[bar_name].append(new_bt)
            print(f"  + bartender: {full_name} @ {bar_name}")
        await db.commit()

        # ── 2. Owner-Managers Chat (idempotent create + membership) ──
        om_chan = (await db.execute(
            select(Channel).where(Channel.name == "Owner-Managers Chat")
        )).scalar_one_or_none()
        if om_chan is None:
            om_chan = Channel(
                name="Owner-Managers Chat",
                channel_type="strategic",
                tenant_id=tenant_id,
                created_by=omar.id,
            )
            db.add(om_chan)
            await db.flush()
            print(f"  + channel: Owner-Managers Chat")

        wanted = [omar] + list(managers_by_bar.values())
        existing_ids = {
            row.user_id for row in (await db.execute(
                select(ChannelMember).where(ChannelMember.channel_id == om_chan.id)
            )).scalars().all()
        }
        for u in wanted:
            if u.id in existing_ids:
                continue
            db.add(ChannelMember(
                channel_id=om_chan.id,
                user_id=u.id,
                tenant_id=tenant_id,
            ))
        await db.commit()

        # ── 3. Rename bar channels (idempotent) ──
        for old_name, new_name in CHANNEL_RENAMES.items():
            ch = (await db.execute(
                select(Channel).where(Channel.name == old_name)
            )).scalar_one_or_none()
            if ch:
                ch.name = new_name
        await db.commit()

        # ── 4. For each Bar Team channel: remove Omar, add bartenders ──
        for bar_name in BAR_TO_CHANNEL:
            ch = (await db.execute(
                select(Channel).where(Channel.name == BAR_TO_CHANNEL[bar_name])
            )).scalar_one()

            await db.execute(
                delete(ChannelMember).where(
                    ChannelMember.channel_id == ch.id,
                    ChannelMember.user_id == omar.id,
                )
            )
            existing_ids = {
                row.user_id for row in (await db.execute(
                    select(ChannelMember).where(ChannelMember.channel_id == ch.id)
                )).scalars().all()
            }
            for bt in bartenders_by_bar[bar_name]:
                if bt.id in existing_ids:
                    continue
                db.add(ChannelMember(
                    channel_id=ch.id,
                    user_id=bt.id,
                    tenant_id=tenant_id,
                ))
        await db.commit()
        print("Communication tree seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
