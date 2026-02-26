"""Tests for the strict matching engine."""

from scanner.matcher import is_strict_match
from scanner.models import CardAttributes, GradingCompany


def test_exact_match():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        card_number="4/102",
        set_name="Base Set",
        edition="1st Edition",
        language="English",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        card_number="4/102",
        set_name="Base Set",
        edition="1st Edition",
        language="English",
    )
    assert is_strict_match(a, b) is True


def test_different_grading_company():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.CGC, grade=10)
    assert is_strict_match(a, b) is False


def test_different_grade():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=9)
    assert is_strict_match(a, b) is False


def test_different_card_number():
    a = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, card_number="4/102"
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, card_number="5/102"
    )
    assert is_strict_match(a, b) is False


def test_different_edition():
    a = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, edition="1st Edition"
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, edition="Unlimited"
    )
    assert is_strict_match(a, b) is False


def test_different_set():
    a = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, set_name="Base Set"
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, set_name="Jungle"
    )
    assert is_strict_match(a, b) is False


def test_different_language():
    a = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, language="English"
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, language="Japanese"
    )
    assert is_strict_match(a, b) is False


def test_unknown_grading_rejected():
    a = CardAttributes(grading_company=GradingCompany.UNKNOWN, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    assert is_strict_match(a, b) is False


def test_missing_grade_rejected():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=None)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    assert is_strict_match(a, b) is False


def test_nft_has_card_number_ebay_missing():
    """If NFT has card number but eBay doesn't → discard."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA, grade=10, card_number="4/102"
    )
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10, card_number="")
    assert is_strict_match(a, b) is False


def test_match_without_optional_fields():
    """If neither has optional fields, match on required fields only."""
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    assert is_strict_match(a, b) is True
