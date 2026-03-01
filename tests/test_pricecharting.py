"""Tests for PriceCharting module."""

import pytest

from scanner.models import CardAttributes, Currency, GradingCompany, NFTListing
from scanner.pricecharting import (
    _build_search_query,
    _card_numbers_match,
    _extract_pc_number,
    _grade_price_usd,
    _match_score,
    _normalize_for_match,
    _parse_usd_price,
)


# --- _parse_usd_price ---


def test_parse_usd_price_simple():
    assert _parse_usd_price("$5.01") == 5.01


def test_parse_usd_price_large():
    assert _parse_usd_price("$1,250.00") == 1250.00


def test_parse_usd_price_no_dollar():
    assert _parse_usd_price("75.33") == 75.33


def test_parse_usd_price_empty():
    assert _parse_usd_price("") == 0.0


def test_parse_usd_price_none():
    assert _parse_usd_price(None) == 0.0


# --- _normalize_for_match ---


def test_normalize_strips_special():
    assert _normalize_for_match("Charizard V #125") == "charizardv125"


def test_normalize_lowercase():
    assert _normalize_for_match("PSA 10") == "psa10"


# --- _extract_pc_number ---


def test_extract_pc_number_standard():
    assert _extract_pc_number("Charizard ex #125") == "125"


def test_extract_pc_number_prefixed():
    assert _extract_pc_number("Blastoise EX #XY122") == "XY122"


def test_extract_pc_number_leading_zeros():
    assert _extract_pc_number("Mew ex #003") == "3"


def test_extract_pc_number_no_number():
    assert _extract_pc_number("Charizard ex") == ""


# --- _card_numbers_match ---


def test_card_numbers_match_exact():
    assert _card_numbers_match("125", "125") is True


def test_card_numbers_match_hash():
    assert _card_numbers_match("#125", "125") is True


def test_card_numbers_match_leading_zeros():
    assert _card_numbers_match("003", "3") is True


def test_card_numbers_match_slash():
    assert _card_numbers_match("170/198", "170") is True


def test_card_numbers_mismatch():
    assert _card_numbers_match("060", "161") is False


def test_card_numbers_mismatch_different():
    assert _card_numbers_match("041", "156") is False


def test_card_numbers_empty():
    assert _card_numbers_match("", "125") is False


# --- _build_search_query ---


def _make_nft(pokemon="Charizard", variant="V", number="125", set_name="Obsidian Flames",
              grade=10.0, company=GradingCompany.PSA, language="", title=None) -> NFTListing:
    attrs = CardAttributes(
        pokemon_name=pokemon,
        variant=variant,
        card_number=number,
        set_name=set_name,
        grading_company=company,
        grade=grade,
        language=language,
    )
    t = title or f"{pokemon} {variant} #{number} PSA {grade} {set_name}"
    return NFTListing(
        title=t,
        price=1.0,
        currency=Currency.SOL,
        price_eur=100.0,
        attributes=attrs,
    )


def test_build_query_includes_pokemon():
    nft = _make_nft()
    q = _build_search_query(nft)
    assert "Charizard" in q


def test_build_query_includes_variant():
    nft = _make_nft()
    q = _build_search_query(nft)
    assert "V" in q


def test_build_query_includes_number():
    nft = _make_nft()
    q = _build_search_query(nft)
    assert "125" in q


def test_build_query_includes_set():
    nft = _make_nft()
    q = _build_search_query(nft)
    assert "Obsidian Flames" in q


def test_build_query_excludes_grading():
    """PriceCharting queries should NOT include grading (PSA 10 etc)."""
    nft = _make_nft()
    q = _build_search_query(nft)
    assert "PSA" not in q
    assert "10" not in q or "10" in "125"  # 10 might be in the number


def test_build_query_japanese():
    nft = _make_nft(language="Japanese")
    q = _build_search_query(nft)
    assert "Japanese" in q


def test_build_query_deduplicates():
    """Exact duplicate parts (case-insensitive) are removed."""
    nft = _make_nft(pokemon="Charizard", variant="V", number="V", set_name="Obsidian Flames")
    q = _build_search_query(nft)
    # "V" appears as both variant and number, should be deduped
    parts = q.lower().split()
    assert parts.count("v") == 1


# --- _match_score ---


def test_match_score_perfect():
    nft = _make_nft(pokemon="Charizard", variant="ex", number="125", set_name="Obsidian Flames")
    product = {
        "productName": "Charizard ex #125",
        "consoleName": "Pokemon Obsidian Flames",
    }
    score = _match_score(nft, product)
    assert score >= 0.9


def test_match_score_number_mismatch_rejects():
    """CRITICAL: Different card numbers MUST reject the match (score=0)."""
    nft = _make_nft(pokemon="Umbreon", variant="EX", number="060", set_name="Prismatic Evolutions")
    product = {
        "productName": "Umbreon ex #161",  # Alternate art — different card!
        "consoleName": "Pokemon Prismatic Evolutions",
    }
    score = _match_score(nft, product)
    assert score == 0.0


def test_match_score_number_mismatch_rejects_sylveon():
    """Sylveon #041 must NOT match Sylveon #156."""
    nft = _make_nft(pokemon="Sylveon", variant="EX", number="041", set_name="Prismatic Evolutions")
    product = {
        "productName": "Sylveon ex #156",
        "consoleName": "Pokemon Prismatic Evolutions",
    }
    score = _match_score(nft, product)
    assert score == 0.0


def test_match_score_number_match_scores_high():
    """Same card number should score highly."""
    nft = _make_nft(pokemon="Umbreon", variant="EX", number="060", set_name="Prismatic Evolutions")
    product = {
        "productName": "Umbreon ex #60",
        "consoleName": "Pokemon Prismatic Evolutions",
    }
    score = _match_score(nft, product)
    assert score >= 0.8


def test_match_score_partial_match_no_pc_number():
    """Pokemon matches but PC product has no number → low score."""
    nft = _make_nft(pokemon="Charizard", variant="V", number="999", set_name="Other Set")
    product = {
        "productName": "Charizard VMAX",
        "consoleName": "Pokemon Different Set",
    }
    score = _match_score(nft, product)
    # Can't verify number → reduced score
    assert 0.2 <= score <= 0.6


def test_match_score_no_match():
    nft = _make_nft(pokemon="Pikachu", variant="V", number="25", set_name="Base Set")
    product = {
        "productName": "Charizard ex #125",
        "consoleName": "Pokemon Obsidian Flames",
    }
    score = _match_score(nft, product)
    assert score == 0.0  # Number mismatch → rejected


def test_match_score_few_attrs():
    """Low confidence when few attributes to check."""
    nft = _make_nft(pokemon="Charizard", variant="", number="", set_name="")
    product = {
        "productName": "Charizard #4",
        "consoleName": "Pokemon Base Set",
    }
    score = _match_score(nft, product)
    # Should be reduced due to few attributes
    assert score < 0.5


def test_match_score_variant_v_not_in_vmax():
    """Short variant 'V' should NOT match inside 'VMAX' (word-boundary check)."""
    nft = _make_nft(pokemon="Charizard", variant="V", number="25", set_name="Some Set")
    product = {
        "productName": "Charizard VMAX #25",
        "consoleName": "Pokemon Some Set",
    }
    score = _match_score(nft, product)
    # Number matches, pokemon matches, but variant V ≠ VMAX
    # Score should be decent but not perfect (missing variant match)
    assert 0.5 <= score <= 0.85


# --- _grade_price_usd ---


def _product_with_prices(p1="$5.00", p2="$75.00", p3="$25.00"):
    return {"price1": p1, "price2": p2, "price3": p3}


def test_grade_price_psa10():
    p = _product_with_prices()
    assert _grade_price_usd(p, 10.0, GradingCompany.PSA) == 75.0


def test_grade_price_cgc10():
    p = _product_with_prices()
    assert _grade_price_usd(p, 10.0, GradingCompany.CGC) == 75.0


def test_grade_price_grade9():
    p = _product_with_prices()
    assert _grade_price_usd(p, 9.0, GradingCompany.PSA) == 25.0


def test_grade_price_grade95():
    """CGC 9.5 should average PSA 10 and Grade 9."""
    p = _product_with_prices()
    assert _grade_price_usd(p, 9.5, GradingCompany.CGC) == 50.0  # (75+25)/2


def test_grade_price_grade8():
    """Grade 8 should be between ungraded and grade 9."""
    p = _product_with_prices()
    assert _grade_price_usd(p, 8.0, GradingCompany.PSA) == 15.0  # (5+25)/2


def test_grade_price_ungraded():
    p = _product_with_prices()
    assert _grade_price_usd(p, None, GradingCompany.UNKNOWN) == 5.0


def test_grade_price_low_grade():
    """Grade 7 or below returns ungraded price."""
    p = _product_with_prices()
    assert _grade_price_usd(p, 7.0, GradingCompany.PSA) == 5.0


def test_grade_price_fallback_no_psa10():
    """If PSA 10 price is 0, fallback to grade 9."""
    p = _product_with_prices(p2="$0.00")
    assert _grade_price_usd(p, 10.0, GradingCompany.PSA) == 25.0
