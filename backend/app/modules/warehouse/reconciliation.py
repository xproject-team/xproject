"""Reconciliation engine — pure function that computes DiscrepancyReport.

This is the heart of the Warehouse module's hero feature. Given an invoice
(with its expected line items) and the scans that happened during its
session, it produces the report Omar waves at the driver.

Pure: no DB access, no side effects, no async. Takes plain data in, returns
plain data out. Testable in isolation with tiny in-memory fixtures.

The service layer calls this AFTER querying the invoice + its scans; the
engine doesn't care where those came from. Makes unit testing trivial.

Spec: docs/warehouse-module-spec.md §7.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.modules.warehouse.schemas import (
    DiscrepancyLine,
    DiscrepancyLineStatus,
    DiscrepancyReport,
    OverallDiscrepancyStatus,
)


# A light "expected item" shape — decoupled from the ORM so tests
# don't need SQLAlchemy to construct fixtures.
class _ExpectedItem:
    """In-memory representation of an invoice line, for the engine."""
    def __init__(
        self,
        *,
        product_id: UUID | None,
        display_name: str,
        expected_qty: Decimal,
        unit_price_cents: int | None,
    ) -> None:
        self.product_id = product_id
        self.display_name = display_name
        self.expected_qty = expected_qty
        self.unit_price_cents = unit_price_cents


class _ScannedItem:
    """In-memory representation of a scan, for the engine.

    Scans against freetext (miscellaneous) invoice lines are matched by
    a synthetic product_id=None + display_name; the service layer is
    responsible for producing the right _ScannedItem input.
    """
    def __init__(
        self,
        *,
        product_id: UUID | None,
        display_name: str,
        qty: Decimal,
    ) -> None:
        self.product_id = product_id
        self.display_name = display_name
        self.qty = qty


def compute_discrepancy(
    *,
    invoice_id: UUID,
    supplier_name: str,
    expected_items: list[_ExpectedItem],
    scanned_items: list[_ScannedItem],
) -> DiscrepancyReport:
    """Build the DiscrepancyReport.

    Algorithm:
      1. Aggregate scanned qty by product_id (or None for miscellaneous).
      2. For each expected line, compute delta = scanned - expected.
         - delta == 0 -> 'match'
         - delta <  0 -> 'short'   (supplier owes you — the fraud signal)
         - delta >  0 -> 'extra'   (product IS on invoice but more came)
      3. For scanned products NOT in expected, emit 'unexpected' lines.
         These correspond to scans flagged pending_review in the DB.
      4. Roll up totals and overall status.

    Numeric values:
      - Quantities are Decimal (NUMERIC(12,2) in DB)
      - Prices are integer cents
      - value_delta_cents = delta * unit_price_cents (rounded, integer)
      - Unexpected lines have no expected price; value_delta is None.
    """
    # ─── 1. Aggregate scanned quantities per product-key ────────────────────
    # Key is product_id for catalog items, or the display name for
    # miscellaneous freetext items (there's no shared ID to group by).
    scanned_by_key: dict[tuple[str, UUID | str], Decimal] = defaultdict(
        lambda: Decimal(0)
    )
    for scan in scanned_items:
        if scan.product_id is not None:
            key = ("product", scan.product_id)
        else:
            key = ("misc", scan.display_name)
        scanned_by_key[key] += scan.qty

    # Track which keys we've matched against expected, so we can find
    # unexpected ones afterward.
    matched_keys: set = set()
    lines: list[DiscrepancyLine] = []
    total_expected_cents: int | None = 0
    total_scanned_value_cents: int | None = 0
    any_price_recorded = False

    # ─── 2. Process each expected item ──────────────────────────────────────
    for exp in expected_items:
        if exp.product_id is not None:
            key = ("product", exp.product_id)
        else:
            key = ("misc", exp.display_name)

        matched_keys.add(key)
        scanned_qty = scanned_by_key.get(key, Decimal(0))
        delta = scanned_qty - exp.expected_qty

        if delta == 0:
            line_status: DiscrepancyLineStatus = "match"
        elif delta < 0:
            line_status = "short"
        else:
            line_status = "extra"

        # Value math
        value_delta_cents = None
        if exp.unit_price_cents is not None:
            any_price_recorded = True
            # delta * price — round to nearest cent
            value_delta_cents = int(
                (delta * Decimal(exp.unit_price_cents)).quantize(Decimal("1"))
            )
            # Running totals (only meaningful when prices exist)
            expected_line_total = int(
                (exp.expected_qty * Decimal(exp.unit_price_cents)).quantize(
                    Decimal("1")
                )
            )
            scanned_line_value = int(
                (scanned_qty * Decimal(exp.unit_price_cents)).quantize(
                    Decimal("1")
                )
            )
            total_expected_cents += expected_line_total
            total_scanned_value_cents += scanned_line_value

        lines.append(
            DiscrepancyLine(
                product_id=exp.product_id,
                product_name=exp.display_name,
                expected_qty=exp.expected_qty,
                scanned_qty=scanned_qty,
                delta=delta,
                status=line_status,
                unit_price_cents=exp.unit_price_cents,
                value_delta_cents=value_delta_cents,
            )
        )

    # ─── 3. Unexpected scanned items (not on the invoice) ───────────────────
    for (kind, key_val), scanned_qty in scanned_by_key.items():
        if (kind, key_val) in matched_keys:
            continue
        # Figure out display name + product_id for the unexpected line
        if kind == "product":
            # Use the first scan's display_name for this product (they should
            # all be identical since they share product_id)
            display = next(
                (s.display_name for s in scanned_items if s.product_id == key_val),
                "Unknown product",
            )
            product_id = key_val
        else:
            display = key_val  # the freetext name itself
            product_id = None

        lines.append(
            DiscrepancyLine(
                product_id=product_id,
                product_name=display,
                expected_qty=Decimal(0),
                scanned_qty=scanned_qty,
                delta=scanned_qty,
                status="unexpected",
                unit_price_cents=None,
                value_delta_cents=None,
            )
        )

    # ─── 4. Roll-up totals and overall status ───────────────────────────────
    has_shortage = any(l.status == "short" for l in lines)
    has_unexpected = any(l.status == "unexpected" for l in lines)
    has_extra = any(l.status == "extra" for l in lines)

    # If NO prices were recorded anywhere, leave totals as None (not zero).
    # Zero would falsely imply "balanced accounting."
    if not any_price_recorded:
        final_expected = None
        final_scanned = None
        final_delta = None
    else:
        final_expected = total_expected_cents
        final_scanned = total_scanned_value_cents
        final_delta = total_scanned_value_cents - total_expected_cents

    overall_status: OverallDiscrepancyStatus
    if not (has_shortage or has_unexpected or has_extra):
        overall_status = "match"
    else:
        overall_status = "discrepancy"
    # 'dispute_opened' is set only by the service layer when Owner formally
    # files a dispute (post-report); the engine never emits it directly.

    return DiscrepancyReport(
        invoice_id=invoice_id,
        supplier_name=supplier_name,
        computed_at=datetime.now(timezone.utc),
        lines=lines,
        total_expected_cents=final_expected,
        total_scanned_value_cents=final_scanned,
        total_delta_cents=final_delta,
        has_shortage=has_shortage,
        has_unexpected=has_unexpected,
        overall_status=overall_status,
    )


# ─── Helpers for service-layer callers ───────────────────────────────────────

def build_expected_items_from_orm(items) -> list[_ExpectedItem]:
    """Convert ORM InvoiceItem rows -> _ExpectedItem list.

    The `items` iterable must each have product + misc fields populated.
    InvoiceRepository.get_by_id eager-loads .items via selectinload;
    the caller is responsible for also loading each item's .product
    if it wants catalog product names (otherwise we fall back to
    "product {product_id}" or the miscellaneous description).
    """
    out: list[_ExpectedItem] = []
    for it in items:
        if it.kind == "catalog_product":
            product = getattr(it, "product", None)
            name = product.name if product is not None else f"Product {it.product_id}"
            out.append(
                _ExpectedItem(
                    product_id=it.product_id,
                    display_name=name,
                    expected_qty=Decimal(it.expected_qty),
                    unit_price_cents=it.unit_price_cents,
                )
            )
        else:
            out.append(
                _ExpectedItem(
                    product_id=None,
                    display_name=it.miscellaneous_description or "Miscellaneous",
                    expected_qty=Decimal(it.expected_qty),
                    unit_price_cents=it.unit_price_cents,
                )
            )
    return out


def build_scanned_items_from_orm(scans) -> list[_ScannedItem]:
    """Convert ORM WarehouseScan rows -> _ScannedItem list.

    Only INTAKE scans should be passed in (service filters before calling).
    Each scan must have .product eager-loaded for display_name resolution.
    """
    out: list[_ScannedItem] = []
    for s in scans:
        product = getattr(s, "product", None)
        if s.product_id is not None and product is not None:
            name = product.name
        elif s.barcode_raw is not None:
            name = f"Barcode {s.barcode_raw}"
        else:
            name = "Unknown"
        out.append(
            _ScannedItem(
                product_id=s.product_id,
                display_name=name,
                qty=Decimal(s.qty),
            )
        )
    return out
