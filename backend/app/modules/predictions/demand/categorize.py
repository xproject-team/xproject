"""Category classification for the historical (2024/2025) Sundance
export vocabulary — a DIFFERENT, coarser methodology than
app.scripts.build_customer_features.bucket_category, by necessity.

The current-year (2026) classifier joins on products.category via an
exact product_id FK — ground truth. The historical exports have no such
catalog: `product_names` is a free-text, comma-joined string per order
(e.g. "Sprtiz, Cocktail, Bicchiere"), captured directly from Slesh's
own on-screen button labels at the time. This is a keyword classifier
over that fixed, already-observed 76-term vocabulary (see the
2026-07-29 exploration: every distinct fragment across all 9 historical
events was enumerated and classified by hand into the buckets below) —
not a general-purpose NLP classifier, and not expected to generalize to
label text it hasn't seen.

Buckets match build_customer_features.py's scheme exactly: beer |
cocktail | spritz | wine | premium | other | food | deposit — so a
downstream consumer can treat historical and current-year rows
identically once classified.
"""
from __future__ import annotations

# Checked in order; first match wins. Deposit and spritz are checked
# before the generic "cocktail" bucket for the same reason as the
# current-year classifier — spritz and deposit items have no dedicated
# label in Slesh's own taxonomy and would otherwise be swallowed by a
# broader keyword.
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deposit", ("bicchiere",)),
    ("spritz", ("sprtiz", "spritz")),
    ("premium", ("premium", "no.3", "n3 ", "signature")),
    ("beer", ("birra", "nastro azzurro", "raffo")),
    ("wine", ("vino", "bolle", "prosecco")),
    ("cocktail", ("cocktail", "gin tonic", "shot")),
    ("other", ("acqua", "soft drink", "analcolico", "caffè", "caffe", "frutta")),
    ("food", (
        "patatin", "tacos", "mortadella", "veg", "bun ", "burger", "prosciutto",
        "porchetta", "gyoza", "poke", "takoyaki", "polpette", "ciabatta",
        "arancine", "calamari", "gelato", "arrosticini", "cartoccio",
        "pulled", "bu pork", "bu chicken", "wrap", "gamberi", "classicone",
        "salmon", "nachos", "box medio", "box grande", "polletti",
        "smash", "pollo", "frittura", "cannolo", "crispy",
    )),
)


def classify_historical_product(name: str) -> str:
    """Classify one exploded product-name fragment from the historical
    export vocabulary. Returns 'unclassified' (not 'other') for anything
    not in the observed 76-term vocabulary this was built against — a
    silent 'other' would hide a genuinely new label; 'unclassified' is
    meant to be reported and reviewed, not routed into training data.
    """
    lowered = (name or "").strip().lower()
    if not lowered:
        return "unclassified"
    for bucket, keywords in _KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return bucket
    return "unclassified"
