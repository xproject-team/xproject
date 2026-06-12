"""Business logic for event_storage.

Two surfaces:
- Supplier products (master list): upsert + list. The wizard's
  autocomplete reads list_supplier_products; new items added on the
  fly (e.g. Omar buys something not in the master list) get inserted
  via upsert_supplier_product.
- Event stock items (per-event): bulk upsert, list, delete, summary.
  The wizard's "Storage" tab POSTs the entire row set on save and
  re-fetches on load. Idempotent on (tenant_id, event_id,
  supplier_product_id).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.auth.models import User
from app.modules.event_storage.models import (
    EventStockBarAllocation,
    EventStockItem,
    SupplierProduct,
)
from app.modules.event_storage.repository import (
    EventStockItemRepository,
    SupplierProductRepository,
)
from app.modules.event_storage.schemas import (
    EventStockItemCreate,
    StorageSummaryResponse,
    StorageSummaryRow,
    DispatchCreate,
    ActivityFeedRow,
    BarAllocationSummary,
    BarAllocationItem,
)


# ─── Domain exceptions ────────────────────────────────────────────────
# Mapped to 4xx in the router (commit 3).

class BarNotFoundError(Exception):
    """Raised when a bar doesn't exist, belongs to another tenant,
    or belongs to a different event than the one being dispatched to."""

    def __init__(self, bar_id):
        self.bar_id = bar_id
        super().__init__(f"Bar {bar_id} not found or not in event")


class SupplierProductNotFoundError(Exception):
    """Supplier product id doesn't exist in this tenant."""
    def __init__(self, supplier_product_id: UUID):
        self.supplier_product_id = supplier_product_id


class EventStockItemNotFoundError(Exception):
    """Event stock item id doesn't exist in this tenant."""
    def __init__(self, item_id: UUID):
        self.item_id = item_id


# ─── Service ──────────────────────────────────────────────────────────

class EventStorageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.supplier_products_repo = SupplierProductRepository(db)
        self.event_stock_items_repo = EventStockItemRepository(db)

    # ── Supplier products (master list) ───────────────────────────────

    async def upsert_supplier_product(
        self, tenant_id: UUID, *,
        supplier_sku: str,
        item_name: str,
        category: str,
        default_unit: str,
        units_per_pack: int = 1,
        volume_per_unit_ml: int | None = None,
        last_unit_price_eur: Decimal | None = None,
        supplier_name: str = "Partesa",
    ) -> SupplierProduct:
        """Get-or-create a supplier_product by (tenant_id, supplier_sku).

        If the row exists and last_unit_price_eur is provided, the stored
        price is refreshed (so the wizard's "last price" prefill stays
        current). Other fields are NOT overwritten on update — owner
        should edit via PATCH if they change.
        """
        existing = await self.supplier_products_repo.get_by_sku(
            tenant_id, supplier_sku,
        )
        if existing is not None:
            if last_unit_price_eur is not None:
                existing.last_unit_price_eur = last_unit_price_eur
                await self.db.flush()
            return existing

        sp = SupplierProduct(
            tenant_id=tenant_id,
            supplier_name=supplier_name,
            supplier_sku=supplier_sku,
            item_name=item_name,
            category=category,
            default_unit=default_unit,
            units_per_pack=units_per_pack,
            volume_per_unit_ml=volume_per_unit_ml,
            last_unit_price_eur=last_unit_price_eur,
        )
        self.db.add(sp)
        await self.db.flush()
        return sp

    async def list_supplier_products(
        self, tenant_id: UUID, category: str | None = None,
    ) -> list[SupplierProduct]:
        return await self.supplier_products_repo.list_for_tenant(
            tenant_id, category,
        )

    # ── Event stock items ─────────────────────────────────────────────

    async def bulk_upsert_event_stock_items(
        self, tenant_id: UUID, event_id: UUID,
        items: list[EventStockItemCreate],
    ) -> list[EventStockItem]:
        """Upsert N rows in one transaction. Idempotent on
        (tenant_id, event_id, supplier_product_id). Existing rows have
        all mutable fields refreshed from the payload. As a side effect,
        each supplier_product's last_unit_price_eur is updated when the
        row carries a unit_price_eur (keeps the master-list price fresh
        for future events).

        Raises SupplierProductNotFoundError if any supplier_product_id
        does not belong to this tenant — the entire bulk is aborted.
        """
        if not items:
            return []

        # Pre-validate every supplier_product_id belongs to this tenant.
        # Done in one query so we don't half-commit on a bad payload.
        sp_ids = {item.supplier_product_id for item in items}
        sp_rows = (await self.db.execute(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.id.in_(sp_ids),
            )
        )).scalars().all()
        sp_by_id = {sp.id: sp for sp in sp_rows}
        for sp_id in sp_ids:
            if sp_id not in sp_by_id:
                raise SupplierProductNotFoundError(sp_id)

        # Load existing rows for this event in one query.
        existing_rows = (await self.db.execute(
            select(EventStockItem).where(
                EventStockItem.tenant_id == tenant_id,
                EventStockItem.event_id == event_id,
                EventStockItem.supplier_product_id.in_(sp_ids),
            )
        )).scalars().all()
        existing_by_sp = {row.supplier_product_id: row for row in existing_rows}

        result: list[EventStockItem] = []
        for item in items:
            sp = sp_by_id[item.supplier_product_id]
            row = existing_by_sp.get(item.supplier_product_id)

            if row is None:
                row = EventStockItem(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    supplier_product_id=item.supplier_product_id,
                    qty_received=item.qty_received,
                    unit=item.unit,
                    unit_price_eur=item.unit_price_eur,
                    discount_amount_eur=item.discount_amount_eur,
                    line_total_eur=item.line_total_eur,
                    vat_pct=item.vat_pct,
                    invoice_number=item.invoice_number,
                    invoice_date=item.invoice_date,
                    notes=item.notes,
                )
                self.db.add(row)
            else:
                row.qty_received = item.qty_received
                row.unit = item.unit
                row.unit_price_eur = item.unit_price_eur
                row.discount_amount_eur = item.discount_amount_eur
                row.line_total_eur = item.line_total_eur
                row.vat_pct = item.vat_pct
                row.invoice_number = item.invoice_number
                row.invoice_date = item.invoice_date
                row.notes = item.notes

            if item.unit_price_eur is not None:
                sp.last_unit_price_eur = item.unit_price_eur

            result.append(row)

        await self.db.flush()
        return result

    async def list_event_stock_items(
        self, tenant_id: UUID, event_id: UUID,
    ) -> list[EventStockItem]:
        return await self.event_stock_items_repo.list_for_event(
            tenant_id, event_id,
        )

    async def delete_event_stock_item(
        self, tenant_id: UUID, item_id: UUID,
    ) -> None:
        stmt = (
            select(EventStockItem)
            .where(EventStockItem.tenant_id == tenant_id)
            .where(EventStockItem.id == item_id)
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise EventStockItemNotFoundError(item_id)
        await self.db.delete(row)
        await self.db.flush()

    # ── Aggregations ──────────────────────────────────────────────────

    async def get_storage_summary(
        self, tenant_id: UUID, event_id: UUID,
    ) -> StorageSummaryResponse:
        """Aggregation for the warehouse + inventory pages.

        qty_received  comes from event_stock_items.
        qty_allocated is SUM(event_stock_bar_allocations.qty_allocated)
                      across all bars for that (event, supplier_product).
        qty_available = received - allocated (warehouse remaining).

        Single round-trip: pull items, supplier_products, and an
        aggregated allocations map in three queries, then compose.
        """
        items = await self.list_event_stock_items(tenant_id, event_id)
        sp_ids = {item.supplier_product_id for item in items}

        sp_map: dict[UUID, SupplierProduct] = {}
        if sp_ids:
            sp_rows = (await self.db.execute(
                select(SupplierProduct).where(
                    SupplierProduct.id.in_(sp_ids),
                )
            )).scalars().all()
            sp_map = {sp.id: sp for sp in sp_rows}

        # Per-supplier_product total allocated across all bars for this event
        from sqlalchemy import func
        allocated_map: dict[UUID, Decimal] = {}
        if sp_ids:
            stmt = (
                select(
                    EventStockBarAllocation.supplier_product_id,
                    func.coalesce(
                        func.sum(EventStockBarAllocation.qty_allocated),
                        Decimal("0"),
                    ),
                )
                .where(
                    EventStockBarAllocation.tenant_id == tenant_id,
                    EventStockBarAllocation.event_id == event_id,
                    EventStockBarAllocation.supplier_product_id.in_(sp_ids),
                )
                .group_by(EventStockBarAllocation.supplier_product_id)
            )
            for sp_id, total in (await self.db.execute(stmt)).all():
                allocated_map[sp_id] = total

        rows: list[StorageSummaryRow] = []
        by_category: dict[str, int] = {}
        total_value = Decimal("0")
        has_any_value = False
        total_received = Decimal("0")
        total_allocated = Decimal("0")

        for item in items:
            sp = sp_map.get(item.supplier_product_id)
            if sp is None:
                continue

            qty_allocated = allocated_map.get(
                item.supplier_product_id, Decimal("0"),
            )
            qty_available = item.qty_received - qty_allocated

            rows.append(StorageSummaryRow(
                supplier_product_id=item.supplier_product_id,
                item_name=sp.item_name,
                category=sp.category,
                unit=item.unit,
                qty_received=item.qty_received,
                qty_allocated=qty_allocated,
                qty_available=qty_available,
                line_total_eur=item.line_total_eur,
            ))
            by_category[sp.category] = by_category.get(sp.category, 0) + 1
            total_received += item.qty_received
            total_allocated += qty_allocated
            if item.line_total_eur is not None:
                total_value += item.line_total_eur
                has_any_value = True

        return StorageSummaryResponse(
            event_id=event_id,
            total_items=len(items),
            total_qty_received=total_received,
            total_qty_allocated=total_allocated,
            total_line_value_eur=total_value if has_any_value else None,
            by_category=by_category,
            rows=rows,
        )

    # ─── Dispatch (event_stock_bar_allocations) ──────────────────────

    async def _validate_bar(
        self, tenant_id: UUID, event_id: UUID, bar_id: UUID,
    ) -> Bar:
        bar = (await self.db.execute(
            select(Bar).where(
                Bar.id == bar_id,
                Bar.tenant_id == tenant_id,
                Bar.event_id == event_id,
            )
        )).scalars().first()
        if bar is None:
            raise BarNotFoundError(bar_id)
        return bar

    async def _validate_supplier_product(
        self, tenant_id: UUID, supplier_product_id: UUID,
    ) -> SupplierProduct:
        sp = (await self.db.execute(
            select(SupplierProduct).where(
                SupplierProduct.id == supplier_product_id,
                SupplierProduct.tenant_id == tenant_id,
            )
        )).scalars().first()
        if sp is None:
            raise SupplierProductNotFoundError(supplier_product_id)
        return sp

    async def create_dispatch(
        self,
        tenant_id: UUID,
        event_id: UUID,
        payload: DispatchCreate,
        dispatched_by_user_id: UUID | None = None,
    ) -> EventStockBarAllocation:
        """One dispatch = one row. History-preserving."""
        await self._validate_supplier_product(
            tenant_id, payload.supplier_product_id,
        )
        await self._validate_bar(tenant_id, event_id, payload.bar_id)

        row = EventStockBarAllocation(
            tenant_id=tenant_id,
            event_id=event_id,
            supplier_product_id=payload.supplier_product_id,
            bar_id=payload.bar_id,
            qty_allocated=payload.qty_allocated,
            dispatched_by_user_id=dispatched_by_user_id,
            notes=payload.notes,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def bulk_create_dispatches(
        self,
        tenant_id: UUID,
        event_id: UUID,
        items: list[DispatchCreate],
        dispatched_by_user_id: UUID | None = None,
    ) -> list[EventStockBarAllocation]:
        """Atomic — pre-validate ALL bars and supplier_products
        belong to (tenant, event). All-or-nothing insert."""
        if not items:
            return []

        sp_ids = {item.supplier_product_id for item in items}
        bar_ids = {item.bar_id for item in items}

        # Validate all supplier_products in one query
        valid_sp_ids = set((await self.db.execute(
            select(SupplierProduct.id).where(
                SupplierProduct.id.in_(sp_ids),
                SupplierProduct.tenant_id == tenant_id,
            )
        )).scalars().all())
        missing_sp = sp_ids - valid_sp_ids
        if missing_sp:
            raise SupplierProductNotFoundError(next(iter(missing_sp)))

        # Validate all bars belong to (tenant, event) in one query
        valid_bar_ids = set((await self.db.execute(
            select(Bar.id).where(
                Bar.id.in_(bar_ids),
                Bar.tenant_id == tenant_id,
                Bar.event_id == event_id,
            )
        )).scalars().all())
        missing_bars = bar_ids - valid_bar_ids
        if missing_bars:
            raise BarNotFoundError(next(iter(missing_bars)))

        rows = [
            EventStockBarAllocation(
                tenant_id=tenant_id,
                event_id=event_id,
                supplier_product_id=item.supplier_product_id,
                bar_id=item.bar_id,
                qty_allocated=item.qty_allocated,
                dispatched_by_user_id=dispatched_by_user_id,
                notes=item.notes,
            )
            for item in items
        ]
        self.db.add_all(rows)
        await self.db.flush()
        for row in rows:
            await self.db.refresh(row)
        return rows

    async def list_activity_feed(
        self,
        tenant_id: UUID,
        event_id: UUID,
        limit: int = 50,
    ) -> list[ActivityFeedRow]:
        """Recent dispatches joined with item + bar + user names.
        Powers the right-sidebar feed on the Warehouse page."""
        stmt = (
            select(
                EventStockBarAllocation.id,
                EventStockBarAllocation.qty_allocated,
                EventStockBarAllocation.created_at,
                SupplierProduct.item_name,
                SupplierProduct.default_unit,
                Bar.name.label("bar_name"),
                User.full_name,
                User.role,
            )
            .select_from(EventStockBarAllocation)
            .join(
                SupplierProduct,
                SupplierProduct.id
                == EventStockBarAllocation.supplier_product_id,
            )
            .join(Bar, Bar.id == EventStockBarAllocation.bar_id)
            .outerjoin(
                User, User.id == EventStockBarAllocation.dispatched_by_user_id,
            )
            .where(
                EventStockBarAllocation.tenant_id == tenant_id,
                EventStockBarAllocation.event_id == event_id,
            )
            .order_by(EventStockBarAllocation.created_at.desc())
            .limit(limit)
        )
        result = (await self.db.execute(stmt)).all()
        return [
            ActivityFeedRow(
                id=r.id,
                qty_allocated=r.qty_allocated,
                item_name=r.item_name,
                item_unit=r.default_unit,
                bar_name=r.bar_name,
                user_name=r.full_name,
                user_role=(
                    r.role.value if hasattr(r.role, "value") else
                    (str(r.role) if r.role is not None else None)
                ),
                dispatched_at=r.created_at,
            )
            for r in result
        ]

    async def list_bar_allocations(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[BarAllocationSummary]:
        """Per-bar grouped totals — Inventory page summary."""
        from sqlalchemy import func
        stmt = (
            select(
                Bar.id.label("bar_id"),
                Bar.name.label("bar_name"),
                EventStockBarAllocation.supplier_product_id,
                SupplierProduct.item_name,
                SupplierProduct.default_unit,
                func.coalesce(
                    func.sum(EventStockBarAllocation.qty_allocated),
                    Decimal("0"),
                ).label("total_qty"),
            )
            .select_from(EventStockBarAllocation)
            .join(Bar, Bar.id == EventStockBarAllocation.bar_id)
            .join(
                SupplierProduct,
                SupplierProduct.id
                == EventStockBarAllocation.supplier_product_id,
            )
            .where(
                EventStockBarAllocation.tenant_id == tenant_id,
                EventStockBarAllocation.event_id == event_id,
            )
            .group_by(
                Bar.id,
                Bar.name,
                EventStockBarAllocation.supplier_product_id,
                SupplierProduct.item_name,
                SupplierProduct.default_unit,
            )
            .order_by(Bar.name, SupplierProduct.item_name)
        )
        result = (await self.db.execute(stmt)).all()

        by_bar: dict[UUID, BarAllocationSummary] = {}
        for r in result:
            if r.bar_id not in by_bar:
                by_bar[r.bar_id] = BarAllocationSummary(
                    bar_id=r.bar_id,
                    bar_name=r.bar_name,
                    items=[],
                )
            by_bar[r.bar_id].items.append(BarAllocationItem(
                supplier_product_id=r.supplier_product_id,
                item_name=r.item_name,
                unit=r.default_unit,
                qty_total_allocated=r.total_qty,
            ))
        return list(by_bar.values())
