from app.modules.predictions.demand.categorize import classify_historical_product


def test_spritz_beats_generic_cocktail():
    assert classify_historical_product("Sprtiz") == "spritz"


def test_deposit():
    assert classify_historical_product("Bicchiere") == "deposit"


def test_premium_beats_generic_cocktail():
    assert classify_historical_product("Cocktail Premium") == "premium"
    assert classify_historical_product("Cocktail Super premium") == "premium"
    assert classify_historical_product("Cocktail signature") == "premium"
    assert classify_historical_product("No.3 TONIC") == "premium"


def test_generic_cocktail():
    assert classify_historical_product("Cocktail") == "cocktail"
    assert classify_historical_product("Gin Tonic") == "cocktail"


def test_beer():
    assert classify_historical_product("Birra") == "beer"
    assert classify_historical_product("Nastro Azzurro") == "beer"


def test_wine():
    assert classify_historical_product("Vino e bolle") == "wine"
    assert classify_historical_product("Bottiglia Vino") == "wine"


def test_food():
    assert classify_historical_product("Burger") == "food"
    assert classify_historical_product("Patatina Media") == "food"
    assert classify_historical_product("Smash Burger") == "food"


def test_other():
    assert classify_historical_product("Acqua") == "other"
    assert classify_historical_product("Soft Drink") == "other"


def test_unclassified_not_silently_bucketed():
    """An unseen label must be flagged, not silently absorbed into
    'other' — 'Bottiglia' alone (no 'Vino') is genuinely ambiguous."""
    assert classify_historical_product("Bottiglia") == "unclassified"
    assert classify_historical_product("Some Totally New Item") == "unclassified"


def test_empty_and_none():
    assert classify_historical_product("") == "unclassified"
    assert classify_historical_product(None) == "unclassified"


def test_case_and_whitespace_insensitive():
    assert classify_historical_product("  SPRTIZ  ") == "spritz"
    assert classify_historical_product("birra") == "beer"
