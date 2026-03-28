"""Database seed script — populates the DB with realistic sample data for development.

Run via: make seed
Or directly: python -m app.scripts.seed
"""
import asyncio

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password


async def seed_users() -> None:
    """Create the four role-representative seed users."""
    async with AsyncSessionLocal() as db:
        # TODO: upsert seed users — owner (Omar), manager, bartender, warehouse
        print("  Users seeded.")


async def seed_event() -> None:
    """Create a sample Sundance 2026 event with two bars and inventory."""
    async with AsyncSessionLocal() as db:
        # TODO: create event, bars, and ~20 inventory items
        print("  Event + inventory seeded.")


async def main() -> None:
    print("Seeding database...")
    await seed_users()
    await seed_event()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
