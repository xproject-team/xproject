"""Unit tests for the fuzzy product matcher.

These are pure-function tests — no DB, no async, no FastAPI. They use
SimpleNamespace as a Product stand-in because the matcher only reads
two attributes: id (any hashable) and name (str).

What we\'re validating:
  1. Real PARTESA invoice strings produce the matches we\'d expect against
     a tiny mock catalog. Establishes that the algorithm choice works
     for Italian product names with noise words (BIRRA, BO, KAR, etc).
  2. Thresholds work — sub-threshold matches dropped.
  3. top_k caps results.
  4. Edge cases (empty inputs, blank queries) don\'t crash.
"""
from types import SimpleNamespace
from uuid import uuid4

from app.modules.products.matcher import (
    DEFAULT_THRESHOLD,
    MatchCandidate,
    fuzzy_match_products,
)


def _p(name: str):
    """Build a mock product (only id + name needed by the matcher)."""
    return SimpleNamespace(id=uuid4(), name=name)


# ─── Real-world fattura → catalog mapping ────────────────────────────

def test_matches_heineken_against_short_catalog_name():
    """Invoice has \"BIRRA HEINEKEN 30 LT FS\" — Catalog has \"HEINEKEN\".
    Both share the distinctive token; token_set_ratio should rank this
    high enough to suggest as a match."""
    catalog = [_p("HEINEKEN"), _p("Coca Cola"), _p("Spritz")]
    matches = fuzzy_match_products("BIRRA HEINEKEN 30 LT FS", catalog)
    assert len(matches) >= 1
    assert matches[0].product.name == "HEINEKEN"
    assert matches[0].score >= 70


def test_no_match_for_unrelated_invoice_item():
    """\"BEEFEATER LONDON DRY 1LT GIN\" has no overlap with the catalog
    here — should return empty list (or only very-low matches below
    threshold), NOT spuriously match WYBOROWA or anything else."""
    catalog = [_p("WYBOROWA"), _p("ACQUA"), _p("Spritz")]
    matches = fuzzy_match_products("BEEFEATER LONDON DRY 1LT GIN", catalog)
    # We don\'t assert empty (some token leaks happen), but the top
    # score should be well below the auto-suggest threshold (85).
    if matches:
        assert matches[0].score < 85, (
            f"unexpected high-confidence match: {matches[0].product.name} "
            f"@ {matches[0].score} — token_set_ratio is too permissive"
        )


def test_matches_are_ordered_by_score_desc():
    """When multiple candidates score above threshold, best comes first.

    Note on token_set_ratio: it gives 100 to any subset match, so a
    short product name fully contained in the query scores as high as
    a longer one with the same tokens. We don\'t test \"HEINEKEN\" vs
    \"BIRRA HEINEKEN\" here for that reason — both legitimately score
    100. Instead we use a strong/weak pair that produces a clear
    score gap, which is the real ordering contract."""
    catalog = [
        _p("HEINEKEN"),                       # strong: exact token from query
        _p("Coca Cola Zero"),                 # weak: no token overlap
        _p("Pringles Original"),              # weak: no token overlap
    ]
    matches = fuzzy_match_products("BIRRA HEINEKEN 30 LT FS", catalog, threshold=0)
    assert len(matches) >= 1
    # HEINEKEN must be the top match; the unrelated items must score lower
    assert matches[0].product.name == "HEINEKEN"
    for later in matches[1:]:
        assert later.score <= matches[0].score


def test_top_k_caps_results():
    """With many similar candidates, only `top_k` returned."""
    catalog = [_p(f"HEINEKEN {x}") for x in ["330ML", "500ML", "1L", "20LT", "30LT"]]
    matches = fuzzy_match_products("HEINEKEN", catalog, top_k=2)
    assert len(matches) == 2


def test_threshold_filters_weak_matches():
    """Raising the threshold drops borderline matches."""
    catalog = [_p("HEINEKEN")]
    # \"PIRELLI\" shares only one letter group with HEINEKEN
    low = fuzzy_match_products("PIRELLI", catalog, threshold=10)
    high = fuzzy_match_products("PIRELLI", catalog, threshold=90)
    # At low threshold we might get a result; at high threshold we shouldn\'t
    assert len(high) == 0
    if low:
        assert low[0].score < 90


# ─── Edge cases ──────────────────────────────────────────────────────

def test_empty_query_returns_empty():
    catalog = [_p("HEINEKEN"), _p("Spritz")]
    assert fuzzy_match_products("", catalog) == []
    assert fuzzy_match_products("   ", catalog) == []


def test_empty_catalog_returns_empty():
    assert fuzzy_match_products("BIRRA HEINEKEN", []) == []


def test_returns_match_candidate_dataclass():
    """Return type is list[MatchCandidate] with .product + .score."""
    catalog = [_p("HEINEKEN")]
    result = fuzzy_match_products("HEINEKEN", catalog)
    assert isinstance(result, list)
    assert isinstance(result[0], MatchCandidate)
    assert result[0].product.name == "HEINEKEN"
    assert isinstance(result[0].score, int)
    assert 0 <= result[0].score <= 100
