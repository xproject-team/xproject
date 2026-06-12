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

from app.modules.event_storage.models import EventStockItem, SupplierProduct
from app.modules.event_storage.repository import (
    EventStockItemRepository,
    SupplierProductRepository,
)
from app.modules.event_storage.schemas import (
    EventStockItemCreate,
    StorageSummaryResponse,
    StorageSummaryRow,
)


# ─── Domain exceptions ────────────────────────────────────────────────
# Mapped to 4xx in the router (commit 3).

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
        """Aggregation for the warehouse + inventory pages. v1 returns
        received qty only; allocated / remaining join with BarStock in
        Phase 2.1 once the supplier_product -> product mapping is
        established (today the link is implicit via recipes)."""
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

        rows: list[StorageSummaryRow] = []
        by_category: dict[str, int] = {}
        total_value = Decimal("0")
        has_any_value = False

        for item in items:
            sp = sp_map.get(item.supplier_product_id)
            if sp is None:
                continue

            rows.append(StorageSummaryRow(
                supplier_product_id=item.supplier_product_id,
                item_name=sp.item_name,
                category=sp.category,
                unit=item.unit,
                qty_received=item.qty_received,
                line_total_eur=item.line_total_eur,
            ))
            by_category[sp.category] = by_category.get(sp.category, 0) + 1
            if item.line_total_eur is not None:
                total_value += item.line_total_eur
                has_any_value = True

        return StorageSummaryResponse(
            event_id=event_id,
            total_items=len(items),
            total_line_value_eur=total_value if has_any_value else None,
            by_category=by_category,
            rows=rows,
        )
