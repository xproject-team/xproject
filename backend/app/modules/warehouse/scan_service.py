"""ScanService — the hot path. Every camera detection + every manual scan
submission flows through here.

Responsibilities:
  1. Resolve barcode -> product (or return unknown for manual-entry fallback).
  2. Enforce role-to-scan-type permissions per spec S3.5 matrix.
  3. Validate per-scan-type context (INTAKE needs invoice, DISPATCH needs
     event+bar, etc.).
  4. Mutate downstream state atomically:
       INTAKE     -> warehouse_inventory += qty; flag is_unexpected if product
                     not on invoice (pending_review queue)
       DISPATCH   -> warehouse_inventory -= qty AND warehouse_allocations
                     .dispatched_qty += qty
       RETURN     -> warehouse_inventory += qty AND warehouse_allocations
                     .dispatched_qty -= qty (returns flow stock back)
       ADJUSTMENT -> delta can be positive or negative; Owner-only
       INSPECT    -> no state change; scan is still logged for the audit trail
       CONSUMED   -> warehouse_inventory -= qty (bar consumed, no return flow)
  5. Own transaction boundary: commits after the full scan + all side effects.

Spec: docs/warehouse-module-spec.md S3.5 + S6 + S9.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product
from app.modules.warehouse.models import (
    InvoiceItem,
    WarehouseAllocation,
    WarehouseScan,
)
from app.modules.warehouse.repository import (
    AllocationRepository,
    InventoryRepository,
    InvoiceRepository,
    ScanRepository,
)
from app.modules.warehouse.schemas import (
    BarcodeResolveResponse,
    ScanCreate,
)


# ─── Domain exceptions ────────────────────────────────────────────────────────

class ScanValidationError(Exception):
    """400 — missing required context or invalid combination."""


class ScanPermissionError(Exception):
    """403 — role not allowed to perform this scan_type."""


class InvoiceNotActiveError(Exception):
    """409 — INTAKE scan attempted against non-SCANNING invoice."""


class AllocationNotFoundError(Exception):
    """409 — DISPATCH/RETURN needs an existing allocation row."""


# ─── Role-to-scan-type permission matrix (spec S3.5) ─────────────────────────
# Keys = scanner role, values = set of allowed scan_types for that role.
# Backend enforces AT SERVICE LAYER so it's not just cosmetic frontend security.

class ScanVoidError(Exception):
    """Cannot void this scan — too old, already voided, scan_type not
    supported by the undo path, or scan is in pending_review state.
    Maps to 409 in the router."""


_ROLE_SCAN_PERMISSIONS: dict[str, set[str]] = {
    "owner": {"INTAKE", "DISPATCH", "RETURN", "ADJUSTMENT", "INSPECT", "CONSUMED"},
    # Phase 2 two-role model: Manager absorbs the warehouse-execution scans
    # (INTAKE — invoice intake sessions are owner+manager now) and the
    # bar-floor CONSUMED scan from the retired Bartender role. ADJUSTMENT
    # and INSPECT stay Owner-only audit actions.
    "manager": {"INTAKE", "DISPATCH", "RETURN", "CONSUMED"},
}


class ScanService:
    """Orchestrates scan submissions. Services commit; repos flush."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.scan_repo = ScanRepository(db)
        self.inv_repo = InventoryRepository(db)
        self.alloc_repo = AllocationRepository(db)
        self.invoice_repo = InvoiceRepository(db)

    # ─── Barcode resolution (called before submit to give immediate UI feedback) ─

    async def resolve_barcode(
        self,
        tenant_id: UUID,
        barcode: str,
    ) -> BarcodeResolveResponse:
        """Look up a barcode against the product catalog.

        v1.0 scheme: Product.barcode column holds the EAN/UPC string.
        If product catalog doesn't have a `barcode` field, this falls back
        to matching against Product.name (best-effort for manual dropdowns).

        Returns known + product_name OR unknown (lets UI fall to manual entry).
        """
        # Try barcode column if it exists on Product, else fallback to name match
        # (guards against schema drift if Products hasn't been fully wired yet)
        barcode_col = getattr(Product, "barcode", None)
        if barcode_col is not None:
            stmt = select(Product).where(
                Product.tenant_id == tenant_id,
                barcode_col == barcode,
            )
        else:
            # Fallback — just exact name match until Product gets a barcode column
            stmt = select(Product).where(
                Product.tenant_id == tenant_id,
                Product.name == barcode,
            )

        product = (await self.db.execute(stmt)).scalar_one_or_none()

        if product is None:
            return BarcodeResolveResponse(
                status="unknown",
                barcode=barcode,
            )
        return BarcodeResolveResponse(
            status="known",
            barcode=barcode,
            product_id=product.id,
            product_name=product.name,
        )

    # ─── The hot path: submit a scan ─────────────────────────────────────────

    async def submit_scan(
        self,
        tenant_id: UUID,
        data: ScanCreate,
        *,
        scanned_by_user_id: UUID,
        scanned_by_role: str,
    ) -> WarehouseScan:
        """Record a scan + apply its side effects atomically.

        scanned_by_role is captured as a snapshot — even if the user's role
        changes later, the scan row keeps the role they had at scan time.

        Per-scan-type workflows documented inline below.
        """
        # 0. Idempotency early-out: if the same client_event_id was already
        #    persisted for this tenant, return that row without writing or
        #    mutating inventory. Critical Sundance-safety property — retries
        #    (network blip, double-tap, queue replay) collapse to one row.
        if data.client_event_id is not None:
            existing = await self.scan_repo.find_by_client_event_id(
                tenant_id, data.client_event_id,
            )
            if existing is not None:
                return existing

        # 1. Role permission gate
        allowed_types = _ROLE_SCAN_PERMISSIONS.get(scanned_by_role, set())
        if data.scan_type not in allowed_types:
            raise ScanPermissionError(
                f"Role '{scanned_by_role}' cannot perform {data.scan_type} scans"
            )

        # 2. Resolve product (if barcode given, look it up; else use product_id)
        product_id = data.product_id
        if product_id is None and data.barcode_raw:
            resolve = await self.resolve_barcode(tenant_id, data.barcode_raw)
            if resolve.status == "known":
                product_id = resolve.product_id
            # else leave product_id None — downstream logic handles unknown

        # 3. Per-scan-type validation + side effects
        is_unexpected = False
        pending_review = False

        if data.scan_type == "INTAKE":
            product_id, is_unexpected, pending_review = await self._handle_intake(
                tenant_id=tenant_id,
                data=data,
                resolved_product_id=product_id,
            )

        elif data.scan_type == "DISPATCH":
            await self._handle_dispatch(
                tenant_id=tenant_id,
                data=data,
                resolved_product_id=product_id,
            )

        elif data.scan_type == "RETURN":
            await self._handle_return(
                tenant_id=tenant_id,
                data=data,
                resolved_product_id=product_id,
            )

        elif data.scan_type == "ADJUSTMENT":
            # Owner already gated above; no context required beyond product_id
            if product_id is None:
                raise ScanValidationError(
                    "ADJUSTMENT requires a recognized product (provide product_id or a resolvable barcode)"
                )
            # qty can be signed negative via Decimal? No — schema enforces > 0.
            # v1.0 convention: ADJUSTMENT qty is always positive; direction
            # is implicit (Owner uses this for found-items). Negative
            # adjustments go through RETURN instead.
            await self.inv_repo.upsert_delta(tenant_id, product_id, data.qty)

        elif data.scan_type == "INSPECT":
            # Read-only — NO state mutation. Still log the scan for audit.
            pass

        elif data.scan_type == "CONSUMED":
            # Bartender scan at the bar — warehouse stock decrements.
            # (Bar stock is handled by the stock_transactions module, not us.)
            if product_id is None:
                raise ScanValidationError(
                    "CONSUMED requires a recognized product"
                )
            if data.event_id is None or data.bar_id is None:
                raise ScanValidationError(
                    "CONSUMED requires event_id and bar_id (bar context)"
                )
            await self.inv_repo.upsert_delta(
                tenant_id, product_id, -data.qty
            )

        # 4. Finally, write the scan row (audit trail, always happens)
        scan = await self.scan_repo.create(
            tenant_id=tenant_id,
            scan_type=data.scan_type,
            scanned_by_role=scanned_by_role,
            qty=data.qty,
            product_id=product_id,
            barcode_raw=data.barcode_raw,
            invoice_id=data.invoice_id,
            event_id=data.event_id,
            bar_id=data.bar_id,
            is_unexpected=is_unexpected,
            pending_review=pending_review,
            scanned_by_user_id=scanned_by_user_id,
            client_event_id=data.client_event_id,
        )
        await self.db.commit()
        # Re-fetch with relationships eager-loaded so the router's response
        # serializer doesn't trigger lazy-loads on a closed async session.
        loaded = await self.scan_repo.get_by_id_with_relationships(
            tenant_id, scan.id,
        )
        return loaded if loaded is not None else scan

    # ─── Pending-review workflow (Owner approves/rejects unexpected scans) ───

    async def approve_pending(
        self, tenant_id: UUID, scan_id: UUID
    ) -> WarehouseScan:
        """Owner confirms an unexpected scan is legit — keep the inventory
        delta (already applied), just clear the pending flag.
        """
        scan = await self.scan_repo.get_by_id(tenant_id, scan_id)
        if scan is None or not scan.pending_review:
            raise ScanValidationError(
                f"Scan {scan_id} not found or not pending review"
            )
        await self.scan_repo.clear_pending_review(scan)
        await self.db.commit()
        return scan

    async def reject_pending(
        self, tenant_id: UUID, scan_id: UUID
    ) -> WarehouseScan:
        """Owner rejects — reverse the inventory delta that was applied on
        INTAKE, then clear the pending flag.
        """
        scan = await self.scan_repo.get_by_id(tenant_id, scan_id)
        if scan is None or not scan.pending_review:
            raise ScanValidationError(
                f"Scan {scan_id} not found or not pending review"
            )
        # Reverse the inventory delta (INTAKE added qty, so we subtract)
        if scan.product_id is not None and scan.scan_type == "INTAKE":
            await self.inv_repo.upsert_delta(
                tenant_id, scan.product_id, -Decimal(scan.qty)
            )
        await self.scan_repo.clear_pending_review(scan)
        await self.db.commit()
        return scan

    # ─── Private per-scan-type handlers ──────────────────────────────────────

    async def _handle_intake(
        self,
        *,
        tenant_id: UUID,
        data: ScanCreate,
        resolved_product_id: UUID | None,
    ) -> tuple[UUID | None, bool, bool]:
        """INTAKE: validate invoice session, check product against invoice
        line items, apply inventory delta, flag unexpected if needed.

        Returns: (product_id, is_unexpected, pending_review).
        """
        if data.invoice_id is None:
            raise ScanValidationError(
                "INTAKE scans must include invoice_id (the active delivery session)"
            )

        invoice = await self.invoice_repo.get_by_id(tenant_id, data.invoice_id)
        if invoice is None:
            raise ScanValidationError(f"Invoice {data.invoice_id} not found")
        if invoice.status not in ("SCANNING", "EXPECTED"):
            # EXPECTED is allowed — the first scan auto-transitions to SCANNING
            # but since we commit the scan here, the router can orchestrate the
            # transition beforehand. Strictly, expect SCANNING by the time we get here.
            raise InvoiceNotActiveError(
                f"Invoice is in status {invoice.status}; "
                "cannot accept new INTAKE scans"
            )

        # Check if the scanned product is on the invoice's expected items
        is_unexpected = False
        if resolved_product_id is not None:
            matched = any(
                (item.product_id == resolved_product_id)
                for item in invoice.items
                if item.kind == "catalog_product"
            )
            if not matched:
                is_unexpected = True

        # Inventory delta: INTAKE adds qty regardless of is_unexpected.
        # If Owner later REJECTS a pending scan, we reverse the delta then.
        if resolved_product_id is not None:
            await self.inv_repo.upsert_delta(
                tenant_id, resolved_product_id, data.qty
            )

        # pending_review mirrors is_unexpected for INTAKE
        return resolved_product_id, is_unexpected, is_unexpected

    async def _handle_dispatch(
        self,
        *,
        tenant_id: UUID,
        data: ScanCreate,
        resolved_product_id: UUID | None,
    ) -> None:
        """DISPATCH: move stock from warehouse to a bar for an event.

        Decrements warehouse_inventory; increments allocation.dispatched_qty.
        DB CHECK enforces dispatched_qty <= reserved_qty, so we fail loudly
        if Owner forgot to allocate.
        """
        if resolved_product_id is None:
            raise ScanValidationError(
                "DISPATCH requires a recognized product"
            )
        if data.event_id is None or data.bar_id is None:
            raise ScanValidationError(
                "DISPATCH requires event_id and bar_id (destination bar)"
            )

        # Find the allocation row — must exist for this event+product
        allocation = await self.alloc_repo.get_by_event_product(
            tenant_id, data.event_id, resolved_product_id
        )
        if allocation is None:
            raise AllocationNotFoundError(
                f"No allocation found for event {data.event_id} "
                f"+ product {resolved_product_id}. Configure stock before dispatching."
            )

        # Apply: warehouse stock -= qty, allocation.dispatched_qty += qty
        await self.inv_repo.upsert_delta(
            tenant_id, resolved_product_id, -data.qty
        )
        await self.alloc_repo.increment_dispatched(allocation, data.qty)

    async def _handle_return(
        self,
        *,
        tenant_id: UUID,
        data: ScanCreate,
        resolved_product_id: UUID | None,
    ) -> None:
        """RETURN: bar returns unused stock to warehouse.

        Increments warehouse_inventory; decrements allocation.dispatched_qty.
        """
        if resolved_product_id is None:
            raise ScanValidationError(
                "RETURN requires a recognized product"
            )
        if data.event_id is None or data.bar_id is None:
            raise ScanValidationError(
                "RETURN requires event_id and bar_id (source bar)"
            )

        allocation = await self.alloc_repo.get_by_event_product(
            tenant_id, data.event_id, resolved_product_id
        )
        if allocation is None:
            raise AllocationNotFoundError(
                f"No allocation found for event {data.event_id} "
                f"+ product {resolved_product_id}. Cannot return what wasn't dispatched."
            )

        # Apply: warehouse stock += qty, allocation.dispatched_qty -= qty
        await self.inv_repo.upsert_delta(
            tenant_id, resolved_product_id, data.qty
        )
        await self.alloc_repo.increment_dispatched(allocation, -data.qty)

    # ─── Undo (Federico's safety net) ────────────────────────────────────────

    VOIDABLE_SCAN_TYPES: frozenset[str] = frozenset({"DISPATCH", "CONSUMED"})
    VOID_WINDOW_SECONDS: int = 300  # 5 minutes (UI shows 5s; server is generous)

    async def void_scan(
        self,
        tenant_id: UUID,
        scan_id: UUID,
        *,
        voiding_user_id: UUID,
        voiding_user_role: str,
    ) -> WarehouseScan:
        """Reverse the inventory effect of a scan and mark it voided.

        Guards (in order — service is authoritative even if UI is buggy):
          1. Scan exists in this tenant
          2. Scan is one of VOIDABLE_SCAN_TYPES (DISPATCH, CONSUMED)
          3. Scan is not already voided (idempotent: returns same row)
          4. Scan is not in pending_review (Owner approval flow takes precedence)
          5. Scan is younger than VOID_WINDOW_SECONDS (5 minutes)
          6. Voider is either the original scanner OR an Owner

        Atomicity: the inventory reversal + voided_at set happen in the
        same transaction. If anything fails, NEITHER lands.
        """
        scan = await self.scan_repo.get_by_id_with_relationships(tenant_id, scan_id)
        if scan is None:
            raise ScanValidationError(f"Scan {scan_id} not found")

        # Idempotency — already voided is OK, return the row
        if scan.voided_at is not None:
            return scan

        # Authorization
        is_owner = voiding_user_role.lower() == "owner"
        is_original_scanner = scan.scanned_by_user_id == voiding_user_id
        if not (is_owner or is_original_scanner):
            raise ScanPermissionError(
                "Only the original scanner or an Owner can void a scan"
            )

        # Type guard — DISPATCH and CONSUMED only in v1
        if scan.scan_type not in self.VOIDABLE_SCAN_TYPES:
            raise ScanVoidError(
                f"scan_type={scan.scan_type} cannot be undone via this endpoint. "
                f"Owner adjustments / invoice corrections use a separate flow."
            )

        # Pending-review guard — Owner approval flow owns this row
        if scan.pending_review:
            raise ScanVoidError(
                "Scan is awaiting Owner review; resolve via approve/reject instead of void"
            )

        # 5-minute window guard
        from datetime import datetime, timezone
        age_seconds = (datetime.now(timezone.utc) - scan.scanned_at).total_seconds()
        if age_seconds > self.VOID_WINDOW_SECONDS:
            raise ScanVoidError(
                f"Scan is {int(age_seconds)}s old (> {self.VOID_WINDOW_SECONDS}s window). "
                f"Use Owner adjustment to correct older scans."
            )

        # ─── Reverse inventory by scan_type ─────────────────────────────────
        if scan.scan_type == "DISPATCH":
            # Forward: inv -= qty, allocation.dispatched_qty += qty
            # Reverse: inv += qty, allocation.dispatched_qty -= qty
            if scan.product_id is None or scan.event_id is None:
                raise ScanVoidError("DISPATCH scan missing product/event context")
            await self.inv_repo.upsert_delta(
                tenant_id, scan.product_id, scan.qty,  # positive = restore
            )
            allocation = await self.alloc_repo.get_by_event_product(
                tenant_id, scan.event_id, scan.product_id,
            )
            if allocation is not None:
                await self.alloc_repo.increment_dispatched(allocation, -scan.qty)
            # If allocation is None (e.g. deleted by Owner mid-event), we still
            # reverse the inventory delta — the warehouse is the source of truth.
        elif scan.scan_type == "CONSUMED":
            # Forward: inv -= qty (only)
            # Reverse: inv += qty
            if scan.product_id is None:
                raise ScanVoidError("CONSUMED scan missing product context")
            await self.inv_repo.upsert_delta(
                tenant_id, scan.product_id, scan.qty,
            )

        # Mark voided
        scan.voided_at = datetime.now(timezone.utc)
        scan.voided_by_user_id = voiding_user_id
        await self.db.flush()
        await self.db.commit()

        # Re-fetch with relationships eager-loaded for response serialization
        loaded = await self.scan_repo.get_by_id_with_relationships(tenant_id, scan_id)
        return loaded if loaded is not None else scan
