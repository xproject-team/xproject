"""Fuzzy product matching service.

Used by the invoice-upload workflow to suggest existing Catalog products
for each invoice line item, so Omar doesn\'t end up with 31 duplicates
every time he uploads a fattura.

Design choice: pure function. Takes a query string + a list of Product
ORM objects, returns ranked match candidates. The endpoint pulls the
products from DB once and reuses the list for every query in the batch.
The matcher itself does no I/O — easy to unit-test, easy to reuse from
other places (warehouse scan UI, manual product entry, etc).

Algorithm: rapidfuzz token_set_ratio.
  Splits both strings on whitespace, compares the resulting sets.
  Robust to word order, noise words, and length mismatch — which all
  show up in fatture (\"BIRRA HEINEKEN 30 LT FS\" vs \"HEINEKEN\").

Thresholds (tuned for Italian product names, may need adjustment after
real Catalog data lands):
  >= 85   high confidence — auto-suggest
  70-84   medium — show as suggestion
  < 70    low — won\'t be returned as a candidate (will be a new product)
"""
from dataclasses import dataclass
from typing import Sequence

from rapidfuzz import fuzz, process

from app.modules.products.models import Product


# Tuning constants — exposed so tests can vary them
DEFAULT_THRESHOLD: int  = 70
DEFAULT_TOP_K:     int  = 3


@dataclass(frozen=True)
class MatchCandidate:
    """One fuzzy match result — a Product + similarity score 0..100."""
    product:  Product
    score:    int        # rapidfuzz returns float; we round to int for stability


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace. token_set_ratio is already case-
    insensitive but doing it here is explicit + cheap."""
    return " ".join(s.lower().split())


def fuzzy_match_products(
    query: str,
    products: Sequence[Product],
    *,
    threshold: int = DEFAULT_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> list[MatchCandidate]:
    """Return up to `top_k` Product matches for `query`, ranked by score.

    Args:
        query:     raw invoice description, e.g. \"BIRRA HEINEKEN 30 LT FS\".
        products:  candidate pool — typically the tenant\'s active products.
        threshold: minimum score (0..100) to include a candidate.
        top_k:     max candidates returned.

    Returns:
        Sorted list (best match first), empty if no candidate clears
        the threshold.
    """
    if not query.strip() or not products:
        return []
    query_norm = _normalize(query)
    # process.extract returns (choice, score, index) tuples ranked desc.
    # We feed it normalized product names; the index lets us map back to
    # the original Product object.
    choices = [_normalize(p.name) for p in products]
    raw = process.extract(
        query_norm,
        choices,
        scorer=fuzz.token_set_ratio,
        limit=top_k,
        score_cutoff=threshold,
    )
    out: list[MatchCandidate] = []
    for _choice, score, idx in raw:
        out.append(MatchCandidate(product=products[idx], score=int(round(score))))
    return out
