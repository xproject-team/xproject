"""Pydantic schemas for parser output.

Stays in this module (not pushed to warehouse/schemas.py) because
the parser output is an INTERMEDIATE shape — it gets mapped onto
the existing InvoiceCreate schema by the endpoint, after the user
reviews/edits the parse preview in the UI.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ParsedInvoiceItem(BaseModel):
    """One line item from the fattura\'s product table."""
    line_num:        int           = Field(..., description="Riga line number from the PDF (10, 20, 30…)")
    code:            str           = Field(default="", description="Supplier\'s product code (e.g. \"2034T\", \"E9080\")")
    description:     str           = Field(..., description="Product description (cleaned)")
    qty:             Decimal       = Field(..., description="Quantity in the unit specified")
    unit:            str           = Field(..., description="Unit of measure: BO/KAR/FS/BM/CT/PZ/VP")
    unit_price_eur:  Decimal       = Field(..., description="Unit price before discount, in euros")
    discount_pct:    Optional[Decimal] = Field(default=None, description="Percentage discount, if applied")
    discount_eur:    Optional[Decimal] = Field(default=None, description="Flat euro discount, if applied")
    line_total_eur:  Decimal       = Field(..., description="Final line total in euros (after discount)")
    iva_pct:         int           = Field(..., description="IVA percentage (typically 22)")


class ParsedInvoiceHeader(BaseModel):
    """Invoice metadata extracted from the PDF header."""
    supplier_name:    Optional[str]     = Field(default=None)
    supplier_vat:     Optional[str]     = Field(default=None, description="P.IVA del fornitore")
    customer_name:    Optional[str]     = Field(default=None)
    customer_vat:     Optional[str]     = Field(default=None)
    invoice_number:   Optional[str]     = Field(default=None, description="Numero documento")
    invoice_date:     Optional[date]    = Field(default=None, description="Data documento")
    total_imponibile: Optional[Decimal] = Field(default=None, description="Subtotal before IVA")
    total_iva:        Optional[Decimal] = Field(default=None)
    total_document:   Optional[Decimal] = Field(default=None, description="Total amount including IVA")


class ParsedInvoice(BaseModel):
    """Full parsed invoice: header + line items + raw-text passthrough.

    The raw_text field is kept so the endpoint can persist it alongside
    the parsed structure for audit/debugging (a parser improvement
    later won\'t need the original PDF if we kept the text).
    """
    header:   ParsedInvoiceHeader
    items:    list[ParsedInvoiceItem]
    raw_text: str = Field(default="", description="Original extracted text (for audit)")

    @property
    def item_total(self) -> Decimal:
        """Sum of line totals. Should match header.total_imponibile minus any skipped lines (SPESE etc)."""
        return sum((i.line_total_eur for i in self.items), Decimal("0"))
