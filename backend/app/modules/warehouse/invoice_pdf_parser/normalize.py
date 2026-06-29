"""Normalization helpers used across the parser."""
import re
from decimal import Decimal


# ─── UM (unit of measure) map ────────────────────────────────────────
# Italian wholesale codes → internal english labels.
# Used by the endpoint when creating InvoiceItem rows (which want a
# human-readable unit string). The parser itself just records the
# original UM code; translation happens at the boundary.
UM_LABELS: dict[str, str] = {
    "BO":  "bottle",      # bottiglia
    "KAR": "case",        # cartone
    "FS":  "keg",         # fusto
    "BM":  "cylinder",    # bombola (e.g. CO2)
    "CT":  "case",        # cartone (variant)
    "PZ":  "piece",       # pezzo
    "VP":  "vacuum-pack", # vaso pacchetto
}


def it_decimal(s: str) -> Decimal:
    """Italian-formatted number string → Decimal.

    \"1.275,00\" -> Decimal(\"1275.00\")
    \"19,10\"    -> Decimal(\"19.10\")
    \"3.833,16\" -> Decimal(\"3833.16\")

    Italian convention: \".\" is the thousands separator, \",\" is decimal.
    """
    cleaned = s.strip().replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def clean_description(raw: str) -> str:
    """Strip artefacts from collected description text.

    Removes:
      - Leading "000000000000" code-wrap fillers that bled into desc
        (e.g. #210 in the PARTESA sample)
      - Multiple spaces
      - Leading/trailing whitespace
    """
    s = raw.strip()
    # Strip leading bare-zeros code wrap (any run of 6+ zeros at start)
    s = re.sub(r"^0{6,}\s*", "", s)
    # Collapse runs of whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()
