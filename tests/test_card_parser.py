"""Tests for the card title parser."""

from scanner.card_parser import parse_card_title
from scanner.models import GradingCompany


def test_parse_psa_10():
    title = "PSA 10 Charizard 4/102 Base Set 1st Edition"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 10
    assert attrs.card_number == "4/102"
    assert attrs.set_name == "Base Set"
    assert attrs.edition == "1st Edition"


def test_parse_cgc_9_5():
    title = "CGC 9.5 Pikachu #025 Jungle Unlimited"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.CGC
    assert attrs.grade == 9.5
    assert attrs.card_number == "025"
    assert attrs.set_name == "Jungle"
    assert attrs.edition == "Unlimited"


def test_parse_bgs():
    title = "BGS 9 Blastoise 2/102 Base Set 1st Edition English"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.BGS
    assert attrs.grade == 9
    assert attrs.card_number == "2/102"
    assert attrs.edition == "1st Edition"
    assert attrs.language == "English"


def test_parse_beckett_alias():
    title = "Beckett 10 Mewtwo #150 Base Set"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.BGS
    assert attrs.grade == 10


def test_parse_japanese():
    title = "PSA 10 Charizard VMAX 308/190 Shining Fates Japanese"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 10
    assert attrs.card_number == "308/190"
    assert attrs.set_name == "Shining Fates"
    assert attrs.language == "Japanese"


def test_parse_no_grading():
    title = "Charizard Base Set 4/102"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.UNKNOWN
    assert attrs.grade is None


def test_parse_shadowless_edition():
    title = "PSA 8 Charizard 4/102 Base Set Shadowless"
    attrs = parse_card_title(title)
    assert attrs.edition == "Shadowless"
