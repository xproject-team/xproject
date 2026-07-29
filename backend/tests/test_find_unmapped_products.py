from app.scripts.find_unmapped_products import _display_name


def test_display_name_string():
    assert _display_name("Aperol Spritz") == "Aperol Spritz"


def test_display_name_none():
    assert _display_name(None) == "(no name from Slesh)"


def test_display_name_dict_prefers_italian():
    assert _display_name({"it": "Nome Italiano", "en": "English Name"}) == "Nome Italiano"


def test_display_name_dict_falls_back_to_english():
    assert _display_name({"en": "English Name"}) == "English Name"


def test_display_name_dict_falls_back_to_any_value():
    assert _display_name({"fr": "Nom Francais"}) == "Nom Francais"
