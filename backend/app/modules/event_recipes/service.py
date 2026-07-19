"""Business logic for the event_recipes module.

Every write (create/patch/delete/bulk) requires the parent event to be
DRAFT — once an event goes LIVE/COMPLETED, depletion rules are locked
(the recipe editor becomes read-only in the FE). Reads are always
allowed; GET surfaces a `read_only` flag instead of erroring so Omar
can still review what was configured for a past event.

Contract reference: service commits, repository flushes (see
app/modules/venues/service.py).
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.events.service import EventNotDraftError, EventNotFoundError, EventService
from app.modules.event_recipes.repository import EventRecipeRepository
from app.modules.event_recipes.schemas import (
    EventRecipeBulkCreate,
    EventRecipeCreate,
    EventRecipeItemError,
    EventRecipePatch,
    EventRecipeRow,
)


class EventRecipeNotFoundError(Exception):
    """Row does not exist OR belongs to a different tenant. Maps to 404."""

    def __init__(self, row_id: UUID) -> None:
        self.row_id = row_id
        super().__init__(f"Recipe row {row_id} not found")


class EventRecipeDuplicateError(Exception):
    """A row with the same (event_id, drink_name, bar_id,
    supplier_product_id) already exists. Maps to 422 error='row_exists'."""

    def __init__(self, drink_name: str) -> None:
        self.drink_name = drink_name
        super().__init__(
            f"A recipe row for '{drink_name}' at this bar/bottle already exists",
        )


class ProductNotFoundError(Exception):
    """drink_name has no matching catalog Product. product_id is
    NOT NULL since migration aa6, so the row cannot be inserted.
    Maps to 422."""

    def __init__(self, drink_name: str) -> None:
        self.drink_name = drink_name
        super().__init__(f"No catalog product named '{drink_name}'")


class BarNotFoundError(Exception):
    """bar_id does not exist, belongs to a different tenant, or a
    different event. Maps to 422 error='bar_not_found'."""

    def __init__(self, bar_id: UUID) -> None:
        self.bar_id = bar_id
        super().__init__(f"Bar {bar_id} not found on this event")


class SupplierProductNotFoundError(Exception):
    """supplier_product_id does not exist or belongs to a different
    tenant. Maps to 422 error='supplier_product_not_found'."""

    def __init__(self, supplier_product_id: UUID) -> None:
        self.supplier_product_id = supplier_product_id
        super().__init__(f"Supplier product {supplier_product_id} not found")


class EventRecipeBulkValidationError(Exception):
    """One or more rows in a bulk payload failed validation. The whole
    batch is rejected — nothing is inserted. Maps to 422 with a
    per-row `items` list, mirroring FullEventValidationError."""

    def __init__(self, items: list[EventRecipeItemError]) -> None:
        self.items = items
        super().__init__(f"{len(items)} row(s) failed validation")


def _row_to_schema(row) -> EventRecipeRow:
    """Map a joined repository row (see list_for_event) to the response
    schema. `row` here is a SQLAlchemy Row, not the ORM model."""
    return EventRecipeRow(
        id=row.id,
        event_id=row.event_id,
        drink_name=row.slesh_category,
        bar_id=row.bar_id,
        bar_name=row.bar_name if row.bar_name is not None else "All bars",
        supplier_product_id=row.supplier_product_id,
        supplier_product_name=row.supplier_product_name,
        ml_per_sale=float(row.ml_per_sale),
        is_optional=row.is_optional,
    )


class EventRecipeService:
    """All business logic for event-recipe (EventCategoryIngredient) CRUD."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = EventRecipeRepository(db)

    async def _get_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        """Raises EventNotFoundError if missing/cross-tenant."""
        return await EventService(self.db).get_event(tenant_id, event_id)

    async def _require_draft(self, tenant_id: UUID, event_id: UUID) -> Event:
        event = await self._get_event(tenant_id, event_id)
        if event.status != EventStatus.DRAFT:
            raise EventNotDraftError(
                f"Event {event_id} is {event.status}; recipes are read-only "
                "once an event leaves DRAFT",
            )
        return event

    # ─── Reads ──────────────────────────────────────────────────────────

    async def list_for_event(
        self, tenant_id: UUID, event_id: UUID,
    ) -> tuple[list[EventRecipeRow], bool]:
        """Raises EventNotFoundError if missing/cross-tenant."""
        event = await self._get_event(tenant_id, event_id)
        rows = await self.repo.list_for_event(tenant_id, event_id)
        read_only = event.status != EventStatus.DRAFT
        return [_row_to_schema(r) for r in rows], read_only

    # ─── Single-row writes ─────────────────────────────────────────────

    async def create(
        self, tenant_id: UUID, data: EventRecipeCreate,
    ) -> EventRecipeRow:
        await self._require_draft(tenant_id, data.event_id)
        bar = await self.repo.get_bar(tenant_id, data.event_id, data.bar_id)
        if bar is None:
            raise BarNotFoundError(data.bar_id)
        sp = await self.repo.get_supplier_product(tenant_id, data.supplier_product_id)
        if sp is None:
            raise SupplierProductNotFoundError(data.supplier_product_id)
        if await self.repo.exists(
            tenant_id, data.event_id, data.drink_name, data.bar_id, data.supplier_product_id,
        ):
            raise EventRecipeDuplicateError(data.drink_name)

        # product_id is NOT NULL since migration aa6 (see bulk_create).
        prod = await self.repo.get_product_by_name(tenant_id, data.drink_name)
        if prod is None:
            raise ProductNotFoundError(data.drink_name)

        row = await self.repo.create(tenant_id, data, prod.id)
        await self.db.commit()
        return EventRecipeRow(
            id=row.id,
            event_id=row.event_id,
            drink_name=row.slesh_category,
            bar_id=row.bar_id,
            bar_name=bar.name,
            supplier_product_id=row.supplier_product_id,
            supplier_product_name=sp.item_name,
            ml_per_sale=float(row.ml_per_sale),
            is_optional=row.is_optional,
        )

    async def update(
        self, tenant_id: UUID, row_id: UUID, patch: EventRecipePatch,
    ) -> EventRecipeRow:
        row = await self.repo.get_by_id(tenant_id, row_id)
        if row is None:
            raise EventRecipeNotFoundError(row_id)
        await self._require_draft(tenant_id, row.event_id)

        row = await self.repo.update(row, patch)
        await self.db.commit()

        bar = (
            await self.repo.get_bar(tenant_id, row.event_id, row.bar_id)
            if row.bar_id is not None else None
        )
        sp = await self.repo.get_supplier_product(tenant_id, row.supplier_product_id)
        return EventRecipeRow(
            id=row.id,
            event_id=row.event_id,
            drink_name=row.slesh_category,
            bar_id=row.bar_id,
            bar_name=bar.name if bar is not None else "All bars",
            supplier_product_id=row.supplier_product_id,
            supplier_product_name=sp.item_name if sp is not None else "",
            ml_per_sale=float(row.ml_per_sale),
            is_optional=row.is_optional,
        )

    async def delete(self, tenant_id: UUID, row_id: UUID) -> None:
        row = await self.repo.get_by_id(tenant_id, row_id)
        if row is None:
            raise EventRecipeNotFoundError(row_id)
        await self._require_draft(tenant_id, row.event_id)
        await self.repo.delete(row)
        await self.db.commit()

    # ─── Bulk create ────────────────────────────────────────────────────

    async def bulk_create(
        self, tenant_id: UUID, data: EventRecipeBulkCreate,
    ) -> list[EventRecipeRow]:
        """Atomic add-only insert. Every row is validated BEFORE any
        write happens; if any row is invalid the whole batch is
        rejected and nothing is inserted (existing rows untouched)."""
        await self._require_draft(tenant_id, data.event_id)

        existing_keys = await self.repo.existing_keys(tenant_id, data.event_id)
        seen_in_batch: set[tuple[str, UUID, UUID]] = set()
        errors: list[EventRecipeItemError] = []
        bars_by_id = {}
        supplier_products_by_id = {}
        products_by_name: dict[str, UUID] = {}

        for i, r in enumerate(data.rows):
            if r.event_id != data.event_id:
                errors.append(EventRecipeItemError(
                    index=i, error="event_id does not match the batch's event_id",
                ))
                continue

            bar = bars_by_id.get(r.bar_id)
            if bar is None:
                bar = await self.repo.get_bar(tenant_id, r.event_id, r.bar_id)
                if bar is not None:
                    bars_by_id[r.bar_id] = bar
            if bar is None:
                errors.append(EventRecipeItemError(
                    index=i, error=f"bar {r.bar_id} not found on this event",
                ))
                continue

            sp = supplier_products_by_id.get(r.supplier_product_id)
            if sp is None:
                sp = await self.repo.get_supplier_product(tenant_id, r.supplier_product_id)
                if sp is not None:
                    supplier_products_by_id[r.supplier_product_id] = sp
            if sp is None:
                errors.append(EventRecipeItemError(
                    index=i, error=f"supplier_product {r.supplier_product_id} not found",
                ))
                continue

            # product_id is NOT NULL since migration aa6 — resolve the
            # drink_name to its catalog Product before inserting, instead
            # of relying on the free-text slesh_category join that drifted
            # apart and caused the Jul-5 depletion outage.
            dn = r.drink_name.strip().lower()
            if dn not in products_by_name:
                prod = await self.repo.get_product_by_name(tenant_id, r.drink_name)
                if prod is None:
                    errors.append(EventRecipeItemError(
                        index=i,
                        error=f"no catalog product named '{r.drink_name}'",
                    ))
                    continue
                products_by_name[dn] = prod.id

            key = (r.drink_name.strip().lower(), r.bar_id, r.supplier_product_id)
            if key in existing_keys or key in seen_in_batch:
                errors.append(EventRecipeItemError(
                    index=i, error=f"duplicate row for '{r.drink_name}' in payload",
                ))
                continue
            seen_in_batch.add(key)

        if errors:
            raise EventRecipeBulkValidationError(errors)

        created: list[EventRecipeRow] = []
        for r in data.rows:
            row = await self.repo.create(
                tenant_id, r, products_by_name[r.drink_name.strip().lower()],
            )
            created.append(EventRecipeRow(
                id=row.id,
                event_id=row.event_id,
                drink_name=row.slesh_category,
                bar_id=row.bar_id,
                bar_name=bars_by_id[r.bar_id].name,
                supplier_product_id=row.supplier_product_id,
                supplier_product_name=supplier_products_by_id[r.supplier_product_id].item_name,
                ml_per_sale=float(row.ml_per_sale),
                is_optional=row.is_optional,
            ))
        await self.db.commit()
        return created
