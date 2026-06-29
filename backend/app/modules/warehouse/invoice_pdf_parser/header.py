"""Extract invoice header (metadata) from PDF text lines.

Header fields we care about for the upload workflow:

    supplier_name, supplier_vat
    customer_name, customer_vat
    invoice_number, invoice_date
    total_imponibile, total_iva, total_document

Every field is independent and Optional — if a regex fails to match
on a non-PARTESA layout, that single field stays None. The endpoint
UI will surface "we could not detect X — please fill in" to the user
rather than blocking the whole parse.
"""
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from .normalize import it_decimal
from .schemas import ParsedInvoiceHeader


# ─── Italian month names → numbers ───────────────────────────────────
# Used to parse "Data documento: 09 Giugno 2026" → date(2026, 6, 9).
# Lowercase keys, prefix-match so "giu" or "giugno" both work.
ITALIAN_MONTHS: dict[str, int] = {
    "gennaio":   1,  "gen": 1,
    "febbraio":  2,  "feb": 2,
    "marzo":     3,  "mar": 3,
    "aprile":    4,  "apr": 4,
    "maggio":    5,  "mag": 5,
    "giugno":    6,  "giu": 6,
    "luglio":    7,  "lug": 7,
    "agosto":    8,  "ago": 8,
    "settembre": 9,  "set": 9,  "sett": 9,
    "ottobre":  10,  "ott": 10,
    "novembre": 11,  "nov": 11,
    "dicembre": 12,  "dic": 12,
}


# ─── Patterns ────────────────────────────────────────────────────────
NUMERO_DOC  = re.compile(r"Numero\s+documento\s*:?\s*(\S+)", re.IGNORECASE)
DATA_DOC    = re.compile(
    r"Data\s+documento\s*:?\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
PIVA        = re.compile(r"P\.\s*IVA\s+(IT\d{8,14})", re.IGNORECASE)
SPETTLE     = re.compile(r"^Spett\.?le\s*$", re.IGNORECASE)
FATTURA     = re.compile(r"^FATTURA\s*$", re.IGNORECASE)
IMPONIBILE_HEADER = re.compile(
    r"Imponibile\s+Imposta\s+IVA",
    re.IGNORECASE,
)
EURO_NUM    = re.compile(r"€\s*([\d.]+,\d{2})")
TOTALE_DOC  = re.compile(
    r"Importo\s+totale\s+documento\s*€?\s*([\d.]+,\d{2})",
    re.IGNORECASE,
)


def _italian_date(day_str: str, month_str: str, year_str: str) -> Optional[date]:
    """Parse '09 Giugno 2026' → date(2026, 6, 9). Returns None if month unknown."""
    key = month_str.lower().strip()
    # Try prefix matches: 'giugno' → 'giu' both valid
    month: Optional[int] = ITALIAN_MONTHS.get(key)
    if month is None:
        # Try prefix lookup
        for name, num in ITALIAN_MONTHS.items():
            if key.startswith(name) or name.startswith(key):
                month = num
                break
    if month is None:
        return None
    try:
        return date(int(year_str), month, int(day_str))
    except (ValueError, TypeError):
        return None


def _find_first_match(lines: list[str], pat: re.Pattern) -> Optional[re.Match]:
    """Return the first regex match across all lines (None if none)."""
    for ln in lines:
        m = pat.search(ln)
        if m:
            return m
    return None


def _find_all_matches(lines: list[str], pat: re.Pattern) -> list[re.Match]:
    """All matches in document order (used for the two P.IVA values)."""
    out = []
    for ln in lines:
        for m in pat.finditer(ln):
            out.append(m)
    return out


def _name_after(lines: list[str], anchor_pat: re.Pattern) -> Optional[str]:
    """Find the first line matching anchor_pat; return the NEXT non-empty
    line as the name. Used for both supplier (after \"FATTURA\") and
    customer (after \"Spett.le\")."""
    for i, ln in enumerate(lines):
        if anchor_pat.match(ln):
            for j in range(i + 1, min(i + 4, len(lines))):
                cand = lines[j].strip()
                if cand and not cand.startswith("P.IVA"):
                    return cand
            break
    return None


def _totals_from_summary(lines: list[str]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """The last page has a summary line like:
        Imponibile Imposta IVA (%) Natura/Esigibilita Rif. Normativo
        EUR15.107,39 EUR3.323,63 22 Immediata Ven. IVA 22% IVA
    Returns (imponibile, iva) — both Decimal, or (None, None) if not found.
    """
    for i, ln in enumerate(lines):
        if IMPONIBILE_HEADER.search(ln):
            # Look at the next 3 lines for two euro amounts
            for j in range(i + 1, min(i + 4, len(lines))):
                nums = EURO_NUM.findall(lines[j])
                if len(nums) >= 2:
                    return it_decimal(nums[0]), it_decimal(nums[1])
            break
    return None, None


def extract_header(lines: list[str]) -> ParsedInvoiceHeader:
    """Build a ParsedInvoiceHeader from the extracted text lines.

    Strategy: each field uses its own pattern. Fields are independent;
    a miss on one doesn\'t block the others.
    """
    h = ParsedInvoiceHeader()

    # Invoice number + date
    if m := _find_first_match(lines, NUMERO_DOC):
        h.invoice_number = m.group(1).strip()
    if m := _find_first_match(lines, DATA_DOC):
        h.invoice_date = _italian_date(m.group(1), m.group(2), m.group(3))

    # Supplier / customer VAT (first two P.IVA matches in doc order)
    piva_matches = _find_all_matches(lines, PIVA)
    if len(piva_matches) >= 1:
        h.supplier_vat = piva_matches[0].group(1)
    if len(piva_matches) >= 2:
        h.customer_vat = piva_matches[1].group(1)

    # Supplier name = first non-empty line after "FATTURA"
    h.supplier_name = _name_after(lines, FATTURA)
    # Customer name = first non-empty line after "Spett.le"
    h.customer_name = _name_after(lines, SPETTLE)

    # Totals: imponibile + IVA from the summary section
    imp, iva = _totals_from_summary(lines)
    h.total_imponibile = imp
    h.total_iva        = iva

    # Document total: "Importo totale documento € 18.431,02"
    # Try same-line first; PARTESA layout splits it across two lines,
    # so fall back to "label line + euro on next non-empty line".
    if m := _find_first_match(lines, TOTALE_DOC):
        h.total_document = it_decimal(m.group(1))
    else:
        for i, ln in enumerate(lines):
            if "Importo totale documento" in ln:
                for j in range(i + 1, min(i + 4, len(lines))):
                    eu = EURO_NUM.search(lines[j])
                    if eu:
                        h.total_document = it_decimal(eu.group(1))
                        break
                break

    return h
