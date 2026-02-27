"""Multi-signal scoring engine for NFT-to-eBay matching.

Pipeline:
1. GATE checks (must pass, else disqualified):
   - Grading company must match
   - Grade must match
   - Not a lot/bundle
2. WEIGHTED field scoring:
   - pokemon_name  (0.30) - most critical for identity
   - card_number   (0.25) - very strong identifier
   - variant       (0.20) - V vs Vmax is completely different
   - set_name      (0.15) - narrows down further
   - language      (0.05) - minor but important
   - edition       (0.05) - minor but important
3. DECISION thresholds:
   - >= 0.85: AUTO_MATCH (high confidence 1:1 match)
   - 0.60-0.84: NEEDS_REVIEW (possible match, not certain)
   - < 0.60: NO_MATCH

Every match produces a MatchResult with per-field evidence for debugging.
"""

import logging

from scanner.models import (
    CardAttributes,
    EbaySoldItem,
    GradingCompany,
    MatchDecision,
    MatchEvidence,
    MatchResult,
    NFTListing,
    ScoredEbayMatch,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_POKEMON_NAME = 0.30
WEIGHT_CARD_NUMBER = 0.25
WEIGHT_VARIANT = 0.20
WEIGHT_SET_NAME = 0.15
WEIGHT_LANGUAGE = 0.05
WEIGHT_EDITION = 0.05

# Decision thresholds
THRESHOLD_AUTO_MATCH = 0.85
THRESHOLD_NEEDS_REVIEW = 0.60


def _compare_normalized(a: str, b: str) -> bool:
    """Case-insensitive, whitespace-normalized comparison."""
    return CardAttributes._normalize(a) == CardAttributes._normalize(b)


def _score_pokemon_name(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score pokemon name match.

    Returns (score, reason).
    1.0 = exact match
    0.7 = one name contains the other (e.g. "Galarian Articuno" contains "Articuno")
    0.0 = no match or one/both missing
    """
    nft_name = nft.pokemon_name.strip().lower()
    ebay_name = ebay.pokemon_name.strip().lower()

    if not nft_name and not ebay_name:
        # Both unknown - can't score, neutral
        return 0.5, "Both pokemon names unknown"
    if not nft_name or not ebay_name:
        return 0.0, f"Pokemon name missing: NFT='{nft.pokemon_name}' eBay='{ebay.pokemon_name}'"

    if nft_name == ebay_name:
        return 1.0, f"Exact pokemon match: '{nft.pokemon_name}'"

    # Check if one contains the other (handles "Galarian Articuno" vs "Articuno")
    if nft_name in ebay_name or ebay_name in nft_name:
        return 0.7, f"Partial pokemon match: '{nft.pokemon_name}' ~ '{ebay.pokemon_name}'"

    return 0.0, f"Pokemon mismatch: '{nft.pokemon_name}' vs '{ebay.pokemon_name}'"


def _score_card_number(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score card number match.

    Returns (score, reason).
    1.0 = normalized numbers match exactly
    0.0 = mismatch or one/both missing
    """
    if not nft.card_number and not ebay.card_number:
        return 0.5, "Both card numbers missing"
    if not nft.card_number or not ebay.card_number:
        return 0.0, f"Card number missing: NFT='{nft.card_number}' eBay='{ebay.card_number}'"

    nft_num = CardAttributes._normalize_card_number(nft.card_number)
    ebay_num = CardAttributes._normalize_card_number(ebay.card_number)

    if nft_num == ebay_num:
        return 1.0, f"Card number match: '{nft_num}'"

    return 0.0, f"Card number mismatch: '{nft_num}' vs '{ebay_num}'"


def _score_variant(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score variant match (V, Vmax, GX, EX, etc.).

    Returns (score, reason).
    1.0 = exact match
    0.5 = both empty (acceptable, older cards don't have variants)
    0.0 = mismatch or one has variant but not the other
    """
    nft_var = nft.variant.strip().lower()
    ebay_var = ebay.variant.strip().lower()

    if not nft_var and not ebay_var:
        return 0.5, "Both variants empty (pre-V era cards)"

    if not nft_var or not ebay_var:
        # One has variant, the other doesn't - suspicious
        return 0.0, f"Variant mismatch: NFT='{nft.variant}' eBay='{ebay.variant}'"

    if nft_var == ebay_var:
        return 1.0, f"Variant match: '{nft.variant}'"

    return 0.0, f"Variant mismatch: '{nft.variant}' vs '{ebay.variant}'"


def _score_set_name(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score set name match.

    Returns (score, reason).
    1.0 = exact match (normalized)
    0.7 = one set name is contained in the other
    0.3 = both have set names but they don't match (still possible same card)
    0.5 = one or both missing
    """
    nft_set = CardAttributes._normalize(nft.set_name)
    ebay_set = CardAttributes._normalize(ebay.set_name)

    if not nft_set and not ebay_set:
        return 0.5, "Both set names missing"
    if not nft_set or not ebay_set:
        return 0.3, f"Set name missing: NFT='{nft.set_name}' eBay='{ebay.set_name}'"

    if nft_set == ebay_set:
        return 1.0, f"Set match: '{nft.set_name}'"

    # Check containment (e.g. "Sword & Shield Chilling Reign" contains "Chilling Reign")
    if nft_set in ebay_set or ebay_set in nft_set:
        return 0.7, f"Partial set match: '{nft.set_name}' ~ '{ebay.set_name}'"

    return 0.0, f"Set mismatch: '{nft.set_name}' vs '{ebay.set_name}'"


def _score_language(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score language match."""
    nft_lang = CardAttributes._normalize(nft.language)
    ebay_lang = CardAttributes._normalize(ebay.language)

    if not nft_lang and not ebay_lang:
        return 0.5, "Both languages unknown"
    if not nft_lang or not ebay_lang:
        return 0.3, f"Language missing: NFT='{nft.language}' eBay='{ebay.language}'"

    if nft_lang == ebay_lang:
        return 1.0, f"Language match: '{nft.language}'"

    return 0.0, f"Language mismatch: '{nft.language}' vs '{ebay.language}'"


def _score_edition(nft: CardAttributes, ebay: CardAttributes) -> tuple[float, str]:
    """Score edition match."""
    nft_ed = CardAttributes._normalize(nft.edition)
    ebay_ed = CardAttributes._normalize(ebay.edition)

    if not nft_ed and not ebay_ed:
        return 0.5, "Both editions unknown"
    if not nft_ed or not ebay_ed:
        return 0.3, f"Edition missing: NFT='{nft.edition}' eBay='{ebay.edition}'"

    if nft_ed == ebay_ed:
        return 1.0, f"Edition match: '{nft.edition}'"

    return 0.0, f"Edition mismatch: '{nft.edition}' vs '{ebay.edition}'"


def score_match(nft_attrs: CardAttributes, ebay_attrs: CardAttributes,
                nft_title: str = "", ebay_title: str = "") -> MatchResult:
    """Score how well an NFT matches an eBay listing.

    Returns a MatchResult with total score, decision, and per-field evidence.
    """
    evidence: list[MatchEvidence] = []

    # -----------------------------------------------------------------------
    # GATE 1: Grading company must match
    # -----------------------------------------------------------------------
    if nft_attrs.grading_company == GradingCompany.UNKNOWN:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason="NFT has no grading company",
        )

    if ebay_attrs.grading_company == GradingCompany.UNKNOWN:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason="eBay item has no grading company",
        )

    if nft_attrs.grading_company != ebay_attrs.grading_company:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason=(
                f"Grading company mismatch: "
                f"{nft_attrs.grading_company.value} vs {ebay_attrs.grading_company.value}"
            ),
        )

    # -----------------------------------------------------------------------
    # GATE 2: Grade must match
    # -----------------------------------------------------------------------
    if nft_attrs.grade is None or ebay_attrs.grade is None:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason="Grade missing in one or both items",
        )

    if nft_attrs.grade != ebay_attrs.grade:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason=(
                f"Grade mismatch: {nft_attrs.grade} vs {ebay_attrs.grade}"
            ),
        )

    # -----------------------------------------------------------------------
    # GATE 3: Lot/bundle detection
    # -----------------------------------------------------------------------
    if ebay_attrs.is_lot:
        return MatchResult(
            nft_title=nft_title,
            ebay_title=ebay_title,
            total_score=0.0,
            decision=MatchDecision.NO_MATCH,
            disqualified=True,
            disqualification_reason="eBay listing is a lot/bundle",
        )

    # -----------------------------------------------------------------------
    # WEIGHTED SCORING
    # -----------------------------------------------------------------------
    total_score = 0.0

    # Pokemon name
    score, reason = _score_pokemon_name(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "pokemon_name", nft_attrs.pokemon_name, ebay_attrs.pokemon_name,
        score, WEIGHT_POKEMON_NAME, reason,
    ))
    total_score += score * WEIGHT_POKEMON_NAME

    # Card number
    score, reason = _score_card_number(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "card_number", nft_attrs.card_number, ebay_attrs.card_number,
        score, WEIGHT_CARD_NUMBER, reason,
    ))
    total_score += score * WEIGHT_CARD_NUMBER

    # Variant
    score, reason = _score_variant(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "variant", nft_attrs.variant, ebay_attrs.variant,
        score, WEIGHT_VARIANT, reason,
    ))
    total_score += score * WEIGHT_VARIANT

    # Set name
    score, reason = _score_set_name(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "set_name", nft_attrs.set_name, ebay_attrs.set_name,
        score, WEIGHT_SET_NAME, reason,
    ))
    total_score += score * WEIGHT_SET_NAME

    # Language
    score, reason = _score_language(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "language", nft_attrs.language, ebay_attrs.language,
        score, WEIGHT_LANGUAGE, reason,
    ))
    total_score += score * WEIGHT_LANGUAGE

    # Edition
    score, reason = _score_edition(nft_attrs, ebay_attrs)
    evidence.append(MatchEvidence(
        "edition", nft_attrs.edition, ebay_attrs.edition,
        score, WEIGHT_EDITION, reason,
    ))
    total_score += score * WEIGHT_EDITION

    # -----------------------------------------------------------------------
    # DECISION
    # -----------------------------------------------------------------------
    if total_score >= THRESHOLD_AUTO_MATCH:
        decision = MatchDecision.AUTO_MATCH
    elif total_score >= THRESHOLD_NEEDS_REVIEW:
        decision = MatchDecision.NEEDS_REVIEW
    else:
        decision = MatchDecision.NO_MATCH

    result = MatchResult(
        nft_title=nft_title,
        ebay_title=ebay_title,
        total_score=total_score,
        decision=decision,
        evidence=evidence,
    )

    logger.debug(
        "Match score %.3f (%s): '%s' vs '%s'",
        total_score, decision.value, nft_title[:50], ebay_title[:50],
    )
    for e in evidence:
        logger.debug(
            "  %s: %.2f * %.2f = %.3f | %s",
            e.field_name, e.score, e.weight, e.score * e.weight, e.reason,
        )

    return result


# ---------------------------------------------------------------------------
# Backward-compatible interface + new scored interface
# ---------------------------------------------------------------------------

def is_strict_match(nft_attrs: CardAttributes, ebay_attrs: CardAttributes) -> bool:
    """Check if two CardAttributes match strictly (backward compatible).

    Uses the scoring engine with AUTO_MATCH threshold.
    """
    result = score_match(nft_attrs, ebay_attrs)
    return result.decision == MatchDecision.AUTO_MATCH


def find_matching_sold_items(
    nft: NFTListing,
    ebay_items: list[EbaySoldItem],
) -> list[EbaySoldItem]:
    """Filter eBay items to strict matches only (backward compatible)."""
    matches = []
    for ebay_item in ebay_items:
        if is_strict_match(nft.attributes, ebay_item.attributes):
            matches.append(ebay_item)
            logger.info(
                "Strict match: '%s' <-> '%s' (EUR%.2f)",
                nft.title[:50],
                ebay_item.title[:50],
                ebay_item.sold_price_eur,
            )
    return matches


def find_scored_matches(
    nft: NFTListing,
    ebay_items: list[EbaySoldItem],
    min_decision: MatchDecision = MatchDecision.AUTO_MATCH,
) -> list[ScoredEbayMatch]:
    """Score all eBay items and return those meeting the minimum decision level.

    Args:
        nft: The NFT listing.
        ebay_items: eBay sold items to score against.
        min_decision: Minimum match quality to include:
            - AUTO_MATCH: only high-confidence matches (default)
            - NEEDS_REVIEW: include uncertain matches too
            - NO_MATCH: include everything (for debugging)

    Returns:
        List of ScoredEbayMatch, sorted by score descending.
    """
    decision_rank = {
        MatchDecision.AUTO_MATCH: 2,
        MatchDecision.NEEDS_REVIEW: 1,
        MatchDecision.NO_MATCH: 0,
    }
    min_rank = decision_rank[min_decision]

    scored: list[ScoredEbayMatch] = []
    for ebay_item in ebay_items:
        result = score_match(
            nft.attributes,
            ebay_item.attributes,
            nft_title=nft.title,
            ebay_title=ebay_item.title,
        )

        if decision_rank[result.decision] >= min_rank:
            scored.append(ScoredEbayMatch(
                ebay_item=ebay_item,
                match_result=result,
            ))
            logger.info(
                "Scored match [%.3f %s]: '%s' <-> '%s' (EUR%.2f)",
                result.total_score,
                result.decision.value,
                nft.title[:50],
                ebay_item.title[:50],
                ebay_item.sold_price_eur,
            )

    # Sort by score descending
    scored.sort(key=lambda s: s.match_result.total_score, reverse=True)
    return scored
