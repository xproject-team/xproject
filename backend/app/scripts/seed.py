"""Database seed script — idempotent, safe to re-run.

Inserts the root tenant (Noma Group), its first venue (Sundance Venue),
and its owner user (Omar). Running the script twice is a no-op.

Run via:
    python -m app.scripts.seed
"""
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Tenant, User, UserRole
from app.modules.venues.models import Venue


async def seed() -> None:
    """Create Noma Group + Sundance Venue + Omar (OWNER). Idempotent."""
    async with AsyncSessionLocal() as db:
        # ─── 1. Tenant: Noma Group ───────────────────────────────────
        existing = await db.execute(
            select(Tenant).where(Tenant.slug == "noma-group")
        )
        tenant = existing.scalar_one_or_none()

        if tenant is not None:
            print(f"  Tenant 'Noma Group' already exists (id={tenant.id}) — skipping.")
            return

        tenant = Tenant(name="Noma Group", slug="noma-group")
        db.add(tenant)
        await db.flush()  # assign tenant.id without committing yet
        print(f"  Created tenant: Noma Group (id={tenant.id})")

        # ─── 2. Venue: Sundance Venue ────────────────────────────────
        venue = Venue(
            tenant_id=tenant.id,
            name="Sundance Venue",
            address="Roma, Italia",
            capacity=5000,
        )
        db.add(venue)
        await db.flush()
        print(f"  Created venue: Sundance Venue (id={venue.id})")

        # ─── 3. User: Omar (OWNER) ───────────────────────────────────
        omar = User(
            tenant_id=tenant.id,
            email="omar@nomagroup.it",
            hashed_password=hash_password("change-me-on-first-login"),
            full_name="Omar Abdelbari El Asry",
            role=UserRole.OWNER,
            is_active=True,
        )
        db.add(omar)
        await db.flush()
        print(f"  Created user: Omar (role=OWNER, id={omar.id})")

        await db.commit()
        print("  Commit successful.")


async def main() -> None:
    print("Seeding XProject database...")
    await seed()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
