"""Strict deterministic matching engine for NFT-to-eBay comparison.

Matching rules (ALL must be true for a valid match):
1. Same grading company (PSA, CGC, BGS/Beckett)
2. Same grade (e.g., PSA 10, PSA 9)
3. Same card number
4. Same set
5. Same edition (1st Edition, Unlimited, etc.)
6. Same language if mentioned

If ANY field differs → discard the result.
NO fuzzy matching. NO AI-based semantic matching.
Strict deterministic parsing + comparison only.
"""

import logging

from scanner.models import CardAttributes, EbaySoldItem, GradingCompany, NFTListing

logger = logging.getLogger(__name__)


def is_strict_match(nft_attrs: CardAttributes, ebay_attrs: CardAttributes) -> bool:
    """Check if two CardAttributes match strictly according to the rules.

    Both items must have at minimum a grading company and grade to be comparable.
    If a field is present in both items, it must match exactly.
    If a field is missing in one item, it cannot be verified → discard.

    Returns:
        True only if all present fields match 1:1.
    """
    # Must have grading company identified in both
    if nft_attrs.grading_company == GradingCompany.UNKNOWN:
        logger.debug("NFT has no grading company → skip")
        return False
    if ebay_attrs.grading_company == GradingCompany.UNKNOWN:
        logger.debug("eBay item has no grading company → skip")
        return False

    # Rule 1: Same grading company
    if nft_attrs.grading_company != ebay_attrs.grading_company:
        logger.debug(
            "Grading company mismatch: %s vs %s",
            nft_attrs.grading_company.value,
            ebay_attrs.grading_company.value,
        )
        return False

    # Rule 2: Same grade (must be present in both)
    if nft_attrs.grade is None or ebay_attrs.grade is None:
        logger.debug("Grade missing in one item → skip")
        return False
    if nft_attrs.grade != ebay_attrs.grade:
        logger.debug("Grade mismatch: %s vs %s", nft_attrs.grade, ebay_attrs.grade)
        return False

    # Rule 3: Same card number (if both present)
    if nft_attrs.card_number and ebay_attrs.card_number:
        nft_num = CardAttributes._normalize_card_number(nft_attrs.card_number)
        ebay_num = CardAttributes._normalize_card_number(ebay_attrs.card_number)
        if nft_num != ebay_num:
            logger.debug("Card number mismatch: %s vs %s", nft_num, ebay_num)
            return False
    elif nft_attrs.card_number and not ebay_attrs.card_number:
        # NFT has a card number but eBay doesn't → can't verify → discard
        logger.debug("Card number missing in eBay item → skip")
        return False

    # Rule 4: Same set (if both present)
    if nft_attrs.set_name and ebay_attrs.set_name:
        nft_set = CardAttributes._normalize(nft_attrs.set_name)
        ebay_set = CardAttributes._normalize(ebay_attrs.set_name)
        if nft_set != ebay_set:
            logger.debug("Set mismatch: %s vs %s", nft_set, ebay_set)
            return False
    elif nft_attrs.set_name and not ebay_attrs.set_name:
        logger.debug("Set name missing in eBay item → skip")
        return False

    # Rule 5: Same edition (if both present)
    if nft_attrs.edition and ebay_attrs.edition:
        nft_ed = CardAttributes._normalize(nft_attrs.edition)
        ebay_ed = CardAttributes._normalize(ebay_attrs.edition)
        if nft_ed != ebay_ed:
            logger.debug("Edition mismatch: %s vs %s", nft_ed, ebay_ed)
            return False
    elif nft_attrs.edition and not ebay_attrs.edition:
        logger.debug("Edition missing in eBay item → skip")
        return False

    # Rule 6: Same language (if both present)
    if nft_attrs.language and ebay_attrs.language:
        nft_lang = CardAttributes._normalize(nft_attrs.language)
        ebay_lang = CardAttributes._normalize(ebay_attrs.language)
        if nft_lang != ebay_lang:
            logger.debug("Language mismatch: %s vs %s", nft_lang, ebay_lang)
            return False
    elif nft_attrs.language and not ebay_attrs.language:
        logger.debug("Language missing in eBay item → skip")
        return False

    logger.debug("MATCH found!")
    return True


def find_matching_sold_items(
    nft: NFTListing,
    ebay_items: list[EbaySoldItem],
) -> list[EbaySoldItem]:
    """Filter eBay sold items to only those that strictly match the NFT.

    Args:
        nft: The NFT listing with parsed card attributes.
        ebay_items: List of eBay sold items to check against.

    Returns:
        List of strictly matching EbaySoldItem instances.
    """
    matches = []
    for ebay_item in ebay_items:
        if is_strict_match(nft.attributes, ebay_item.attributes):
            matches.append(ebay_item)
            logger.info(
                "Strict match: '%s' ↔ '%s' (€%.2f)",
                nft.title,
                ebay_item.title,
                ebay_item.sold_price_eur,
            )
    return matches
