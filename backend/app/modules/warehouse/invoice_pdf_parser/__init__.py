"""Italian fattura PDF parser.

Reads PDF invoices (Italian fatture) and returns a structured
ParsedInvoice with header (supplier/customer/invoice#/date/totals)
and line items (description, qty, unit, prices, IVA, discounts).

The parser is regex-based on pdfplumber-extracted text and is tuned
for the PARTESA S.R.L. layout, which is the most common drinks
supplier for Sundance events. Other suppliers may need additional
regex variants; the design supports adding them incrementally.

Public API:
  from app.modules.warehouse.invoice_pdf_parser import parse_invoice_pdf
  
  parsed: ParsedInvoice = parse_invoice_pdf(pdf_bytes)
"""
from .parser import parse_invoice_pdf
from .schemas import ParsedInvoice, ParsedInvoiceItem

__all__ = ["parse_invoice_pdf", "ParsedInvoice", "ParsedInvoiceItem"]
