"""Tests for the Italian fattura PDF parser.

The PARTESA sample is the only real fattura we have today. As more
suppliers come in, add their PDFs under tests/fixtures/fatture/ and
write a similar test per supplier — they\'ll all flow through the
same parse_invoice_pdf entry point.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.warehouse.invoice_pdf_parser import (
    ParsedInvoice,
    ParsedInvoiceItem,
    parse_invoice_pdf,
)


FATTURE_DIR = Path(__file__).parent / "fixtures" / "fatture"
PARTESA_PDF = FATTURE_DIR / "partesa_sample.pdf"


@pytest.fixture(scope="module")
def parsed_partesa() -> ParsedInvoice:
    """Parse the PARTESA sample once for the whole test module."""
    pdf_bytes = PARTESA_PDF.read_bytes()
    return parse_invoice_pdf(pdf_bytes)


# ─── Item count & totals ─────────────────────────────────────────────

def test_partesa_extracts_31_line_items(parsed_partesa: ParsedInvoice) -> None:
    """The PARTESA fattura has 31 product line items + 1 SPESE VARIE
    shipping fee. The parser correctly extracts 31 (skips the fee)."""
    assert len(parsed_partesa.items) == 31


def test_partesa_item_total_matches_pdf(parsed_partesa: ParsedInvoice) -> None:
    """Sum of line totals should be €15,105.89.

    The PDF\'s declared Imponibile is €15,107.39. The €1.50 delta is
    exactly the SPESE VARIE shipping fee, which we intentionally skip
    because it isn\'t a real bottle/case/keg.
    """
    expected = Decimal("15105.89")
    assert parsed_partesa.item_total == expected, (
        f"got {parsed_partesa.item_total}, expected {expected} "
        "(PDF Imponibile €15,107.39 minus €1.50 SPESE)"
    )


# ─── Specific items: regression tests for known edge cases ───────────

def _item(parsed: ParsedInvoice, line_num: int) -> ParsedInvoiceItem:
    """Helper: find an item by its PDF line number (10, 20, 30, …)."""
    return next(i for i in parsed.items if i.line_num == line_num)


def test_partesa_item_10_basic(parsed_partesa: ParsedInvoice) -> None:
    """Item #10 — the simplest layout: description on the line above
    the data row. Smoke test that the happy path works."""
    it = _item(parsed_partesa, 10)
    assert it.description == "WYBOROWA 1LT VODKA"
    assert it.qty == Decimal("30.00")
    assert it.unit == "BO"
    assert it.unit_price_eur == Decimal("19.10")
    assert it.discount_pct == Decimal("31.93")
    assert it.line_total_eur == Decimal("390.04")
    assert it.iva_pct == 22


def test_partesa_item_110_euro_discount(parsed_partesa: ParsedInvoice) -> None:
    """Item #110 — discount expressed as a flat euro amount (-€22,85),
    not a percentage. The regex must handle both forms."""
    it = _item(parsed_partesa, 110)
    assert it.description == "BIRRA ICHNUSA NON FILTRATA 20 LT"
    assert it.unit == "FS"                          # keg
    assert it.discount_pct is None
    assert it.discount_eur == Decimal("22.85")
    assert it.line_total_eur == Decimal("1275.00")


def test_partesa_item_150_inline_description(parsed_partesa: ParsedInvoice) -> None:
    """Item #150 — the description sits on the SAME line as the data
    (after \"E9080 (COD.\"). The regex\'s inline_desc group captures it.
    Without this branch the description would be empty."""
    it = _item(parsed_partesa, 150)
    assert it.code == "E9080"
    assert "VERMOUTH" in it.description.upper()


def test_partesa_item_210_strips_zero_filler(parsed_partesa: ParsedInvoice) -> None:
    """Item #210 — has a long \"000000000000\" product code that wraps
    onto the description line. clean_description() must strip the
    leading zeros so the desc reads \"BIB COCA COLA ZERO 1,5LT PET\"
    not \"000000000000 BIB COCA COLA ZERO 1,5LT PET\".

    Regression for the cosmetic bleed found during the spike."""
    it = _item(parsed_partesa, 210)
    assert it.code == "009022"
    assert it.description == "BIB COCA COLA ZERO 1,5LT PET"
    assert not it.description.startswith("0")     # no leading zero filler


def test_partesa_items_260_270_wrap_reassembly(parsed_partesa: ParsedInvoice) -> None:
    """Items #260 and #270 — descriptions split across multiple lines
    by the long-code wrap. The walker must SKIP the zero-filler line
    (not break) so the description gets joined properly."""
    item_260 = _item(parsed_partesa, 260)
    assert item_260.code == "001355"
    assert item_260.description == "SUC DERBY BLUE ARANCIA 100% 1 LT PET"

    item_270 = _item(parsed_partesa, 270)
    assert item_270.code == "001382"
    assert item_270.description == "SUC DERBY BLUE ANANAS 100% 1 LTx6 PET"


def test_partesa_skips_spese_varie(parsed_partesa: ParsedInvoice) -> None:
    """The SPESE VARIE shipping fee (€1,50) is not a product and must
    not appear in items. There should be no item with line_num=320."""
    line_nums = [i.line_num for i in parsed_partesa.items]
    assert 320 not in line_nums


# ─── Unit & decimal handling ─────────────────────────────────────────

def test_partesa_all_um_codes_recognized(parsed_partesa: ParsedInvoice) -> None:
    """The PARTESA fattura uses 4 UM codes: BO (bottle), KAR (case),
    FS (keg), BM (CO2 cylinder). All must round-trip into the parsed
    item without falling back to a literal \"\" or null."""
    units = {i.unit for i in parsed_partesa.items}
    assert units >= {"BO", "KAR", "FS", "BM"}


def test_partesa_quantities_are_decimal_not_float(parsed_partesa: ParsedInvoice) -> None:
    """Quantities and totals must be Decimal — Italian locale uses
    \",\" as decimal separator and \".\" as thousands, so naive float()
    parsing of \"1.275,00\" would silently parse as 1.275."""
    for it in parsed_partesa.items:
        assert isinstance(it.qty, Decimal)
        assert isinstance(it.unit_price_eur, Decimal)
        assert isinstance(it.line_total_eur, Decimal)


def test_partesa_large_quantity_thousands_separator(parsed_partesa: ParsedInvoice) -> None:
    """Item #30 (BEEFEATER GIN) has line total €3.833,16 — the dot is a
    thousands separator, comma is decimal. Wrong locale handling would
    produce €3.83 instead. This guards against that regression."""
    it = _item(parsed_partesa, 30)
    assert it.line_total_eur == Decimal("3833.16")


# ─── Header extraction ───────────────────────────────────────────────

def test_partesa_supplier_extracted(parsed_partesa: ParsedInvoice) -> None:
    """Supplier name + VAT come from the top of the first page,
    immediately after the \"FATTURA\" anchor."""
    h = parsed_partesa.header
    assert h.supplier_name == "PARTESA S.R.L."
    assert h.supplier_vat == "IT09806270154"


def test_partesa_customer_extracted(parsed_partesa: ParsedInvoice) -> None:
    """Customer name + VAT come from the \"Spett.le\" block on the
    first page. SUNDANCE SRLS is Omar\'s legal entity."""
    h = parsed_partesa.header
    assert h.customer_name == "SUNDANCE SRLS"
    assert h.customer_vat == "IT17156041000"


def test_partesa_invoice_number_and_date(parsed_partesa: ParsedInvoice) -> None:
    """Numero documento + Data documento. The date parser must handle
    Italian month names — \"09 Giugno 2026\" -> date(2026, 6, 9)."""
    from datetime import date
    h = parsed_partesa.header
    assert h.invoice_number == "5812120214"
    assert h.invoice_date == date(2026, 6, 9)


def test_partesa_summary_totals(parsed_partesa: ParsedInvoice) -> None:
    """Imponibile + IVA from the summary section on the last page."""
    h = parsed_partesa.header
    assert h.total_imponibile == Decimal("15107.39")
    assert h.total_iva == Decimal("3323.63")


def test_partesa_document_total_split_lines(parsed_partesa: ParsedInvoice) -> None:
    """\"Importo totale documento\" and its euro amount are on SEPARATE
    lines in the PARTESA layout. Regression: the extractor must fall
    back to a two-line lookahead when the single-line regex misses.
    Without that fallback, total_document came back as None."""
    h = parsed_partesa.header
    assert h.total_document == Decimal("18431.02")
