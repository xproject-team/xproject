"""Italian fattura line-item parser.

Strategy:
  1. Use pdfplumber to extract clean text per page
  2. Locate the product table header ("# Cod. articolo Descrizione ...")
  3. Walk lines: each DATA LINE matches a regex with line# + qty + UM
     + price + (optional discount) + total + IVA%
  4. For each data line, walk BACK through preceding lines to find the
     description, skipping known filler lines (DEST.MERCE, ART), (COD.,
     bare zero-fillers) and STOPPING at the previous item\'s data line.

Edge cases the regex + walker handle (all verified against the PARTESA
sample which has 31 line items + 1 SPESE fee):

  - Discount can be percentage (-31,93%) OR euro amount (-€22,85) OR absent
  - Some items have the product code BEFORE the qty on the data line
    (e.g. "210 009022 (COD. 3,00 KAR € 24,30 € 72,90 22")
  - Some items have the description INLINE within the data line
    (e.g. "150 E9080 (COD. LIQ.ID VERMOUTH DI TORINO 1 LT 5,00 KAR ...")
  - Long product codes wrap onto their own line as "000000000000"
    fillers, splitting a description across multiple text lines
  - SPESE VARIE (shipping fees) have no qty/UM and are explicitly
    skipped — not real bottles

The PARTESA result (the only fattura tested so far):
  - 31 / 31 line items extracted
  - All quantities, prices, totals match the PDF exactly
  - Sum: €15,105.89 vs PDF Imponibile €15,107.39 (delta = €1.50 SPESE)
  - 31 / 31 descriptions clean after clean_description()

Other suppliers will likely have different quirks. The design supports
adding regex variants in DATA_LINE_PATTERNS without changing the walker.
"""
import io
import re
from typing import Optional

import pdfplumber

from .normalize import clean_description, it_decimal
from .schemas import ParsedInvoice, ParsedInvoiceHeader, ParsedInvoiceItem


# ─── The data-line regex ─────────────────────────────────────────────
# Matches a single line that contains all the numeric fields for one
# invoice item. Tuned for PARTESA layout but the structure (line# qty
# UM €price [discount] €total iva) is common across Italian fatture.
DATA_LINE = re.compile(
    r"""^
    (?P<num>\d+)                                  # 10, 20, 30, …
    \s+
    (?:                                           # OPTIONAL "CODE (COD." prefix on same line
        (?P<code>\S+)\s*\(COD\.\s*
        (?:(?P<inline_desc>[A-Z].*?)\s+)?         # rare inline description (#150)
    )?
    (?P<qty>[\d.]+,\d{2})                        # 30,00 / 1.500,00
    \s+
    (?P<um>BO|KAR|FS|BM|CT|PZ|VP)
    \s+€\s*
    (?P<price>[\d.]+,\d{2})
    (?:                                           # OPTIONAL discount
       \s+(?:
            -(?P<disc_pct>[\d.]+,\d{2})\%
            | -€\s*(?P<disc_eur>[\d.]+,\d{2})
       )
    )?
    \s+€\s*
    (?P<total>[\d.]+,\d{2})
    \s+
    (?P<iva>\d+)
    \s*$
    """,
    re.VERBOSE,
)

# Lines to ignore entirely (section headers + non-product rows)
SKIP_LINE = re.compile(
    r"^(SPESE\s+VARIE|Dati\s+Ordine|Dati\s+DDT|Imponibile|Importo)",
    re.IGNORECASE,
)

# Lines that are filler around the data row — skip but keep walking
CODE_WRAP = re.compile(r"^\s*(0{6,}|0{6,}\s+\S+|\S+\s+\(COD\.\s*)$")


def _is_filler(ln: str) -> bool:
    """A line that should be passed over when walking back for a description."""
    if "DEST.MERCE" in ln: return True
    if ln == "ART)": return True
    if "(COD." in ln: return True
    if CODE_WRAP.match(ln): return True
    if SKIP_LINE.match(ln): return True
    if re.fullmatch(r"0{6,}", ln.strip()): return True
    return False


def _is_terminator(ln: str) -> bool:
    """A line that ENDS the backward walk — namely, the previous item\'s data line."""
    return bool(DATA_LINE.match(ln))


def _find_description(
    lines: list[str], i: int, start: int, inline_desc: Optional[str],
) -> str:
    """Resolve the description for the data line at index `i`.

    Walks back from `i`, collecting non-filler non-terminator text lines.
    If the regex captured an inline_desc (rare layout variant where the
    description sits on the data line itself), that wins.
    """
    if inline_desc:
        return clean_description(inline_desc)
    parts: list[str] = []
    j = i - 1
    while j > start:
        prev = lines[j]
        if _is_terminator(prev):
            break
        if _is_filler(prev):
            j -= 1
            continue
        parts.insert(0, prev.strip())
        j -= 1
    return clean_description(" ".join(parts))


def _extract_lines(pdf_bytes: bytes) -> list[str]:
    """Read PDF bytes → ordered list of non-empty text lines (all pages)."""
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln in text.splitlines():
                ln = ln.rstrip()
                if ln:
                    out.append(ln)
    return out


def _parse_items(lines: list[str]) -> list[ParsedInvoiceItem]:
    """Walk the line list, emit one ParsedInvoiceItem per matched data line."""
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("# Cod. articolo"))
    except StopIteration:
        # No product table header found — empty result rather than crash
        return []

    items: list[ParsedInvoiceItem] = []
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if SKIP_LINE.match(ln):
            i += 1
            continue
        m = DATA_LINE.match(ln)
        if m:
            items.append(ParsedInvoiceItem(
                line_num       = int(m["num"]),
                code           = m["code"] or "",
                description    = _find_description(lines, i, start, m["inline_desc"]),
                qty            = it_decimal(m["qty"]),
                unit           = m["um"],
                unit_price_eur = it_decimal(m["price"]),
                discount_pct   = it_decimal(m["disc_pct"]) if m["disc_pct"] else None,
                discount_eur   = it_decimal(m["disc_eur"]) if m["disc_eur"] else None,
                line_total_eur = it_decimal(m["total"]),
                iva_pct        = int(m["iva"]),
            ))
        i += 1
    return items


def parse_invoice_pdf(pdf_bytes: bytes) -> ParsedInvoice:
    """Top-level entry point. Parse a fattura PDF into ParsedInvoice.

    Header extraction (supplier/customer/invoice#/date/totals) is wired
    by the A3 commit; this version returns an empty ParsedInvoiceHeader.
    Items are the main payload and they\'re fully populated.

    Args:
        pdf_bytes: raw PDF file bytes.

    Returns:
        ParsedInvoice with .items populated and .header empty (for now).
        Items respect their order in the PDF (by line_num).
    """
    lines = _extract_lines(pdf_bytes)
    items = _parse_items(lines)
    return ParsedInvoice(
        header   = ParsedInvoiceHeader(),  # filled by A3
        items    = items,
        raw_text = "\n".join(lines),
    )
