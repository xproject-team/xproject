"""InvoiceService — business logic for delivery invoice lifecycle.

The service layer:
  1. Validates tenant scoping (never trusts router).
  2. Enforces the spec S5 state machine
     (EXPECTED -> SCANNING <-> PAUSED -> VERIFIED/DISCREPANCY/DISPUTED -> CLOSED).
  3. Orchestrates: repository writes + ReconciliationEngine on close.
  4. Owns the transaction boundary: repositories flush, service commits.
  5. Translates domain concerns into typed exceptions.

Spec: docs/warehouse-module-spec.md S5 + S7.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import DeliveryInvoice
from app.modules.warehouse.reconciliation import (
    build_expected_items_from_orm,
    build_scanned_items_from_orm,
    compute_discrepancy,
)
from app.modules.warehouse.repository import (
    InvoiceRepository,
    ScanRepository,
)
from app.modules.warehouse.schemas import (
    DiscrepancyReport,
    InvoiceCreate,
    InvoiceUpdate,
)


# ─── Domain exceptions (router maps to HTTP codes) ───────────────────────────

class InvoiceNotFoundError(Exception):
    """404 — invoice missing or cross-tenant."""


class InvalidInvoiceTransitionError(Exception):
    """409 — attempted state transition violates spec S5."""


class InvoiceNotEditableError(Exception):
    """409 — header fields frozen past EXPECTED state."""


# Allowed transitions per spec S5 state machine
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "EXPECTED": {"SCANNING"},
    "SCANNING": {"PAUSED", "VERIFIED", "DISCREPANCY"},
    "PAUSED": {"SCANNING", "DISCREPANCY"},
    "VERIFIED": {"CLOSED"},
    "DISCREPANCY": {"DISPUTED", "CLOSED"},
    "DISPUTED": {"CLOSED"},
    "CLOSED": set(),  # terminal
}


class InvoiceService:
    """All business logic for invoice operations. Services commit; repos flush."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = InvoiceRepository(db)
        self.scan_repo = ScanRepository(db)

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_invoice(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DeliveryInvoice:
        """Fetch one invoice with items eager-loaded.
        Raises InvoiceNotFoundError if missing.
        """
        invoice = await self.repo.get_by_id(tenant_id, invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"Invoice {invoice_id} not found")
        return invoice

    async def list_invoices(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> Sequence[DeliveryInvoice]:
        return await self.repo.list_for_tenant(tenant_id, status=status, limit=limit)

    async def list_pending_deliveries(
        self, tenant_id: UUID
    ) -> Sequence[DeliveryInvoice]:
        """Dashboard strip: EXPECTED/SCANNING/PAUSED."""
        return await self.repo.list_pending_deliveries(tenant_id)

    # ─── Create ──────────────────────────────────────────────────────────────

    async def create_invoice(
        self,
        tenant_id: UUID,
        data: InvoiceCreate,
    ) -> DeliveryInvoice:
        """Create a new invoice + its line items atomically.

        Pydantic already validated each item's kind/product_id/misc consistency.
        The DB CHECK constraints are a belt-and-braces safety net.
        """
        invoice = await self.repo.create(
            tenant_id=tenant_id,
            invoice_number=data.invoice_number,
            supplier_name=data.supplier_name,
            expected_arrival_date=data.expected_arrival_date,
            notes=data.notes,
        )
        for item in data.items:
            await self.repo.add_item(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                kind=item.kind,
                product_id=item.product_id,
                miscellaneous_description=item.miscellaneous_description,
                expected_qty=item.expected_qty,
                unit_price_cents=item.unit_price_cents,
            )
        await self.db.commit()
        # Re-fetch with items loaded for the response
        return await self.get_invoice(tenant_id, invoice.id)

    # ─── Update (only while EXPECTED) ────────────────────────────────────────

    async def update_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        data: InvoiceUpdate,
    ) -> DeliveryInvoice:
        """Edit invoice header fields. Only allowed while status=EXPECTED."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != "EXPECTED":
            raise InvoiceNotEditableError(
                f"Invoice is in status {invoice.status}; "
                "header is frozen once scanning begins."
            )
        # Pydantic model_dump(exclude_unset=True) gives only provided fields
        updates = data.model_dump(exclude_unset=True)
        if updates:
            await self.repo.update_fields(invoice, updates)
            await self.db.commit()
        return await self.get_invoice(tenant_id, invoice_id)

    # ─── State transitions ───────────────────────────────────────────────────

    async def start_scan(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DeliveryInvoice:
        """EXPECTED -> SCANNING. First scan against this invoice."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        self._assert_transition(invoice.status, "SCANNING")
        await self.repo.update_status(
            invoice,
            "SCANNING",
            scan_started_at=datetime.now(timezone.utc),
        )
        await self.db.commit()
        return invoice

    async def pause_scan(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DeliveryInvoice:
        """SCANNING -> PAUSED. 48h auto-close is handled by a cron job (v1.1)."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        self._assert_transition(invoice.status, "PAUSED")
        await self.repo.update_status(invoice, "PAUSED")
        await self.db.commit()
        return invoice

    async def resume_scan(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DeliveryInvoice:
        """PAUSED -> SCANNING."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        self._assert_transition(invoice.status, "SCANNING")
        await self.repo.update_status(invoice, "SCANNING")
        await self.db.commit()
        return invoice

    async def close_scan(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        *,
        closed_by: UUID | None = None,
    ) -> tuple[DeliveryInvoice, DiscrepancyReport]:
        """SCANNING/PAUSED -> VERIFIED or DISCREPANCY.

        The moment of truth: runs the reconciliation engine on the session's
        scans and sets final status based on the result.
        """
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status not in ("SCANNING", "PAUSED"):
            raise InvalidInvoiceTransitionError(
                f"Cannot close invoice in status {invoice.status}"
            )

        # Load scans for this invoice session, with products eager-loaded
        scans = await self.scan_repo.list_for_invoice(tenant_id, invoice_id)

        # Run the pure engine
        report = compute_discrepancy(
            invoice_id=invoice.id,
            supplier_name=invoice.supplier_name,
            expected_items=build_expected_items_from_orm(invoice.items),
            scanned_items=build_scanned_items_from_orm(scans),
        )

        # Pick final status from the report
        final_status = "VERIFIED" if report.overall_status == "match" else "DISCREPANCY"
        self._assert_transition(invoice.status, final_status)
        await self.repo.update_status(
            invoice,
            final_status,
            scan_closed_at=datetime.now(timezone.utc),
            closed_by=closed_by,
        )
        await self.db.commit()
        return invoice, report

    async def open_dispute(
        self, tenant_id: UUID, invoice_id: UUID, reason: str
    ) -> DeliveryInvoice:
        """DISCREPANCY -> DISPUTED. Owner formally disputes with supplier."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        self._assert_transition(invoice.status, "DISPUTED")
        # Append dispute reason into notes; keep the prior notes intact
        prior = invoice.notes or ""
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        dispute_note = f"[{stamp}] Dispute opened: {reason}"
        new_notes = f"{prior}\n\n{dispute_note}" if prior else dispute_note
        await self.repo.update_fields(invoice, {"notes": new_notes})
        await self.repo.update_status(invoice, "DISPUTED")
        await self.db.commit()
        return invoice

    async def archive(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DeliveryInvoice:
        """VERIFIED/DISCREPANCY/DISPUTED -> CLOSED. Terminal state."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        self._assert_transition(invoice.status, "CLOSED")
        await self.repo.update_status(invoice, "CLOSED")
        await self.db.commit()
        return invoice

    # ─── Reconciliation report (on-demand) ───────────────────────────────────

    async def compute_report(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> DiscrepancyReport:
        """Return the DiscrepancyReport for an invoice at ANY state.

        Useful for live 'how am I doing so far' during SCANNING, or for
        re-showing the report after CLOSED without mutating state.
        """
        invoice = await self.get_invoice(tenant_id, invoice_id)
        scans = await self.scan_repo.list_for_invoice(tenant_id, invoice_id)
        return compute_discrepancy(
            invoice_id=invoice.id,
            supplier_name=invoice.supplier_name,
            expected_items=build_expected_items_from_orm(invoice.items),
            scanned_items=build_scanned_items_from_orm(scans),
        )

    # ─── Private helpers ─────────────────────────────────────────────────────

    def _assert_transition(self, from_status: str, to_status: str) -> None:
        """Raise InvalidInvoiceTransitionError if (from, to) is not allowed."""
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise InvalidInvoiceTransitionError(
                f"Invalid transition: {from_status} -> {to_status}. "
                f"Allowed from {from_status}: {sorted(allowed)}"
            )
