"""Tests for the multi-signal scoring matcher."""

from scanner.matcher import (
    is_strict_match,
    score_match,
    find_scored_matches,
    THRESHOLD_AUTO_MATCH,
    THRESHOLD_NEEDS_REVIEW,
)
from scanner.models import (
    CardAttributes,
    Currency,
    EbaySoldItem,
    GradingCompany,
    MatchDecision,
    NFTListing,
)


# ---------------------------------------------------------------------------
# Gate tests (disqualification)
# ---------------------------------------------------------------------------

def test_gate_unknown_grading():
    a = CardAttributes(grading_company=GradingCompany.UNKNOWN, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    result = score_match(a, b)
    assert result.disqualified is True
    assert result.decision == MatchDecision.NO_MATCH
    assert "no grading company" in result.disqualification_reason.lower()


def test_gate_grading_mismatch():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.CGC, grade=10)
    result = score_match(a, b)
    assert result.disqualified is True
    assert result.decision == MatchDecision.NO_MATCH


def test_gate_grade_mismatch():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=9)
    result = score_match(a, b)
    assert result.disqualified is True
    assert "grade mismatch" in result.disqualification_reason.lower()


def test_gate_missing_grade():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=None)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    result = score_match(a, b)
    assert result.disqualified is True


def test_gate_lot_detection():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10, is_lot=True)
    result = score_match(a, b)
    assert result.disqualified is True
    assert "lot" in result.disqualification_reason.lower()


# ---------------------------------------------------------------------------
# Scoring tests - exact matches should score high
# ---------------------------------------------------------------------------

def test_perfect_match_scores_high():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="4/102",
        set_name="Base Set",
        language="English",
        edition="1st Edition",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="4/102",
        set_name="Base Set",
        language="English",
        edition="1st Edition",
    )
    result = score_match(a, b)
    assert result.total_score >= THRESHOLD_AUTO_MATCH
    assert result.decision == MatchDecision.AUTO_MATCH
    assert not result.disqualified


def test_pokemon_name_mismatch_scores_low():
    """Different pokemon name should result in low score."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="4/102",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Blastoise",
        variant="V",
        card_number="4/102",
    )
    result = score_match(a, b)
    assert result.total_score < THRESHOLD_AUTO_MATCH


def test_variant_mismatch_scores_low():
    """V vs Vmax should score low."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="100",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="Vmax",
        card_number="100",
    )
    result = score_match(a, b)
    assert result.total_score < THRESHOLD_AUTO_MATCH


def test_card_number_mismatch_scores_low():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        card_number="4/102",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        card_number="5/102",
    )
    result = score_match(a, b)
    assert result.total_score < THRESHOLD_AUTO_MATCH


def test_set_name_mismatch_reduces_score():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Pikachu",
        variant="V",
        card_number="100",
        set_name="Chilling Reign",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Pikachu",
        variant="V",
        card_number="100",
        set_name="Evolving Skies",
    )
    result = score_match(a, b)
    assert result.total_score < THRESHOLD_AUTO_MATCH


def test_partial_set_name_match():
    """'Chilling Reign' contained in 'Sword & Shield Chilling Reign' should score 0.7."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Pikachu",
        card_number="100",
        set_name="Chilling Reign",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Pikachu",
        card_number="100",
        set_name="Sword & Shield Chilling Reign",
    )
    result = score_match(a, b)
    # Should still be a decent score since set partially matches
    set_evidence = [e for e in result.evidence if e.field_name == "set_name"][0]
    assert set_evidence.score == 0.7


def test_partial_pokemon_name_match():
    """'Galarian Articuno' contains 'Articuno' should score 0.7."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Galarian Articuno",
        card_number="170",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Articuno",
        card_number="170",
    )
    result = score_match(a, b)
    name_evidence = [e for e in result.evidence if e.field_name == "pokemon_name"][0]
    assert name_evidence.score == 0.7


# ---------------------------------------------------------------------------
# Missing fields behavior
# ---------------------------------------------------------------------------

def test_both_missing_pokemon_name():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        card_number="100",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        card_number="100",
    )
    result = score_match(a, b)
    name_evidence = [e for e in result.evidence if e.field_name == "pokemon_name"][0]
    assert name_evidence.score == 0.5  # Neutral when both unknown


def test_both_missing_variant_old_cards():
    """Old cards without variant should still match."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        card_number="4/102",
        set_name="Base Set",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        card_number="4/102",
        set_name="Base Set",
    )
    result = score_match(a, b)
    # Should be high enough for auto-match
    assert result.decision == MatchDecision.AUTO_MATCH


# ---------------------------------------------------------------------------
# Evidence and logging
# ---------------------------------------------------------------------------

def test_evidence_fields_present():
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
    )
    result = score_match(a, b, nft_title="NFT Title", ebay_title="eBay Title")
    assert result.nft_title == "NFT Title"
    assert result.ebay_title == "eBay Title"
    assert len(result.evidence) == 6  # 6 weighted fields
    field_names = {e.field_name for e in result.evidence}
    assert field_names == {"pokemon_name", "card_number", "variant", "set_name", "language", "edition"}


def test_evidence_to_dict():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    result = score_match(a, b)
    d = result.to_dict()
    assert "total_score" in d
    assert "decision" in d
    assert "evidence" in d
    assert isinstance(d["evidence"], list)


# ---------------------------------------------------------------------------
# Decision thresholds
# ---------------------------------------------------------------------------

def test_auto_match_threshold():
    """Full match on all fields should be AUTO_MATCH."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="100",
        set_name="Base Set",
        language="Japanese",
        edition="1st Edition",
    )
    result = score_match(a, a)
    assert result.decision == MatchDecision.AUTO_MATCH
    assert result.total_score >= 0.85


def test_no_match_threshold():
    """Only grading matches, everything else differs -> NO_MATCH."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="Vmax",
        card_number="100",
        set_name="Base Set",
    )
    b = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Blastoise",
        variant="V",
        card_number="200",
        set_name="Jungle",
    )
    result = score_match(a, b)
    assert result.decision == MatchDecision.NO_MATCH
    assert result.total_score < THRESHOLD_NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_is_strict_match_backward_compat():
    """is_strict_match should return True for AUTO_MATCH level."""
    a = CardAttributes(
        grading_company=GradingCompany.PSA,
        grade=10,
        pokemon_name="Charizard",
        variant="V",
        card_number="100",
        set_name="Base Set",
        language="English",
        edition="1st Edition",
    )
    assert is_strict_match(a, a) is True


def test_is_strict_match_rejects_mismatch():
    a = CardAttributes(grading_company=GradingCompany.PSA, grade=10)
    b = CardAttributes(grading_company=GradingCompany.CGC, grade=10)
    assert is_strict_match(a, b) is False


# ---------------------------------------------------------------------------
# find_scored_matches integration
# ---------------------------------------------------------------------------

def test_find_scored_matches_filters_correctly():
    nft = NFTListing(
        title="PSA 10 Charizard V #100 Base Set",
        price=1.0,
        currency=Currency.SOL,
        attributes=CardAttributes(
            grading_company=GradingCompany.PSA,
            grade=10,
            pokemon_name="Charizard",
            variant="V",
            card_number="100",
            set_name="Base Set",
        ),
    )

    # Good match
    good_ebay = EbaySoldItem(
        title="Pokemon PSA 10 Charizard V 100/264 Base Set",
        sold_price_eur=50.0,
        attributes=CardAttributes(
            grading_company=GradingCompany.PSA,
            grade=10,
            pokemon_name="Charizard",
            variant="V",
            card_number="100",
            set_name="Base Set",
        ),
    )

    # Bad match - wrong pokemon
    bad_ebay = EbaySoldItem(
        title="Pokemon PSA 10 Blastoise V 100/264 Base Set",
        sold_price_eur=30.0,
        attributes=CardAttributes(
            grading_company=GradingCompany.PSA,
            grade=10,
            pokemon_name="Blastoise",
            variant="V",
            card_number="100",
            set_name="Base Set",
        ),
    )

    # Lot - should be disqualified
    lot_ebay = EbaySoldItem(
        title="Lot of 5 PSA 10 Pokemon Cards",
        sold_price_eur=200.0,
        attributes=CardAttributes(
            grading_company=GradingCompany.PSA,
            grade=10,
            is_lot=True,
        ),
    )

    results = find_scored_matches(
        nft, [good_ebay, bad_ebay, lot_ebay],
        min_decision=MatchDecision.AUTO_MATCH,
    )

    # Should only return the good match
    assert len(results) == 1
    assert results[0].ebay_item.title == good_ebay.title
    assert results[0].match_result.decision == MatchDecision.AUTO_MATCH
