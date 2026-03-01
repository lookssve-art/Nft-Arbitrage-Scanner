"""Arbitrage detection engine with confidence scoring.

Two-stage price verification:
1. PriceCharting (primary) — fast, reliable aggregated eBay sold prices
2. eBay scraping (fallback) — direct sold-item search with multi-signal matching

Output includes:
- Card title and parsed attributes
- Magic Eden / Phygitals buy price (EUR)
- PriceCharting market price (grade-matched)
- eBay average sold price from confirmed matches (when available)
- Profit percentage
- Match confidence score and evidence
- Direct links (Magic Eden + eBay search + PriceCharting)
"""

import logging
import time

from scanner.config import (
    EBAY_REQUEST_DELAY,
    EBAY_SOLD_SAMPLE_MIN,
    MIN_PROFIT_PERCENT,
    PRICECHARTING_ENABLED,
    REQUEST_DELAY,
)
from scanner.currency import get_usd_to_eur_rate
from scanner.ebay import build_ebay_search_url, search_sold_items
from scanner.matcher import find_scored_matches
from scanner.models import (
    ArbitrageOpportunity,
    MatchDecision,
    NFTListing,
    ScoredEbayMatch,
)
from scanner.pricecharting import lookup_nft_price

logger = logging.getLogger(__name__)


def calculate_profit_percent(buy_price: float, sell_price: float) -> float:
    """Calculate profit percentage: ((sell - buy) / buy) * 100."""
    if buy_price <= 0:
        return 0.0
    return ((sell_price - buy_price) / buy_price) * 100.0


def _analyze_with_pricecharting(nft: NFTListing) -> ArbitrageOpportunity | None:
    """Try to find arbitrage using PriceCharting market prices.

    Returns an opportunity if PriceCharting has a confident match with
    a profitable grade-matched price.
    """
    pc_data = lookup_nft_price(nft)
    if not pc_data:
        return None

    matched_price_usd = pc_data["matched_price_usd"]
    if matched_price_usd <= 0:
        logger.debug("PriceCharting matched but no price for grade: %s", nft.title[:50])
        return None

    # Convert PriceCharting USD price to EUR
    usd_eur = get_usd_to_eur_rate()
    matched_price_eur = matched_price_usd * usd_eur

    # Calculate profit
    profit_pct = calculate_profit_percent(nft.price_eur, matched_price_eur)

    if profit_pct < MIN_PROFIT_PERCENT:
        logger.debug(
            "PC profit %.1f%% below threshold for: %s",
            profit_pct, nft.title[:50],
        )
        return None

    ebay_url = build_ebay_search_url(nft.title)

    opportunity = ArbitrageOpportunity(
        nft=nft,
        ebay_avg_price_eur=matched_price_eur,
        ebay_sold_count=0,  # No individual eBay matches
        profit_percent=profit_pct,
        ebay_search_url=ebay_url,
        match_confidence=pc_data["match_score"],
        pc_matched_price_usd=matched_price_usd,
        pc_product_name=pc_data["product_name"],
        pc_url=pc_data["url"],
        pc_match_score=pc_data["match_score"],
    )

    logger.info(
        "PC ARBITRAGE: +%.1f%% | %s -> %s ($%.2f)",
        profit_pct, nft.title[:40],
        pc_data["product_name"], matched_price_usd,
    )
    return opportunity


def _analyze_with_ebay(nft: NFTListing) -> ArbitrageOpportunity | None:
    """Analyze a single NFT using eBay sold items scraping.

    1. Search eBay for sold items
    2. Score each result with multi-signal matcher
    3. Only use AUTO_MATCH results (confidence >= 0.85)
    4. Calculate average sold price from confirmed matches
    5. Flag if profit >= MIN_PROFIT_PERCENT
    """
    ebay_items = search_sold_items(nft.title)

    if not ebay_items:
        logger.debug("No eBay results for: %s", nft.title)
        return None

    scored_matches = find_scored_matches(
        nft,
        ebay_items,
        min_decision=MatchDecision.AUTO_MATCH,
    )

    if not scored_matches:
        logger.debug("No confident eBay matches for: %s", nft.title)
        return None

    confirmed_items = [sm.ebay_item for sm in scored_matches]

    if len(confirmed_items) < EBAY_SOLD_SAMPLE_MIN:
        logger.debug(
            "Not enough eBay matches for '%s': %d < %d",
            nft.title[:50], len(confirmed_items), EBAY_SOLD_SAMPLE_MIN,
        )
        return None

    prices = [item.sold_price_eur for item in confirmed_items]
    avg_price = sum(prices) / len(prices)

    avg_confidence = sum(
        sm.match_result.total_score for sm in scored_matches
    ) / len(scored_matches)

    profit_pct = calculate_profit_percent(nft.price_eur, avg_price)

    if profit_pct < MIN_PROFIT_PERCENT:
        logger.debug(
            "eBay profit %.1f%% below threshold for: %s",
            profit_pct, nft.title[:50],
        )
        return None

    ebay_url = build_ebay_search_url(nft.title)

    return ArbitrageOpportunity(
        nft=nft,
        ebay_avg_price_eur=avg_price,
        ebay_sold_count=len(confirmed_items),
        profit_percent=profit_pct,
        ebay_search_url=ebay_url,
        ebay_matches=confirmed_items,
        match_confidence=avg_confidence,
        scored_matches=scored_matches,
    )


def analyze_single_nft(nft: NFTListing) -> ArbitrageOpportunity | None:
    """Analyze a single NFT for arbitrage potential.

    Strategy:
    1. Try PriceCharting first (fast, reliable)
    2. If PriceCharting finds an opportunity, also try eBay to enrich
    3. If PriceCharting fails/no match, fall back to eBay scraping
    """
    if nft.price_eur <= 0:
        logger.debug("Skipping NFT with zero EUR price: %s", nft.title)
        return None

    pc_result = None
    ebay_result = None

    # Stage 1: PriceCharting lookup
    if PRICECHARTING_ENABLED:
        pc_result = _analyze_with_pricecharting(nft)
        time.sleep(REQUEST_DELAY)

    # Stage 2: eBay scraping
    # Run eBay if: no PC result, or PC found opportunity (enrich with eBay data)
    if pc_result is None:
        ebay_result = _analyze_with_ebay(nft)
        if ebay_result and pc_result is None:
            return ebay_result
    else:
        # PC found opportunity — try eBay to add match evidence
        ebay_result = _analyze_with_ebay(nft)
        if ebay_result:
            # Merge: use eBay sold data + PC price data
            ebay_result.pc_matched_price_usd = pc_result.pc_matched_price_usd
            ebay_result.pc_product_name = pc_result.pc_product_name
            ebay_result.pc_url = pc_result.pc_url
            ebay_result.pc_match_score = pc_result.pc_match_score
            return ebay_result
        else:
            # No eBay data — use PC-only result
            return pc_result

    return ebay_result


def _insured_value_ratio(nft: NFTListing) -> float:
    """Calculate ratio of insured value to ME listing price (in USD).

    A ratio > 1.2 signals the card may be underpriced on ME.
    """
    if nft.insured_value_usd <= 0:
        return 0.0
    # Approximate ME price in USD from SOL
    me_price_usd = nft.price * 81.0  # Rough SOL/USD for sorting only
    if me_price_usd <= 0:
        return 0.0
    return nft.insured_value_usd / me_price_usd


def scan_for_arbitrage(listings: list[NFTListing]) -> list[ArbitrageOpportunity]:
    """Scan all NFT listings for arbitrage opportunities.

    Uses PriceCharting as primary price source with eBay as fallback.
    Prioritizes listings where insured_value / ME_price ratio is highest.

    Args:
        listings: List of NFT listings from Magic Eden / Phygitals.

    Returns:
        List of ArbitrageOpportunity, sorted by profit percentage (descending).
    """
    opportunities: list[ArbitrageOpportunity] = []

    # Sort by insured value ratio descending to check most promising first
    sorted_listings = sorted(
        listings,
        key=lambda nft: _insured_value_ratio(nft),
        reverse=True,
    )

    price_source = "PriceCharting + eBay" if PRICECHARTING_ENABLED else "eBay only"
    logger.info(
        "Scanning %d listings for arbitrage (%s, sorted by IV ratio)...",
        len(sorted_listings), price_source,
    )

    for i, nft in enumerate(sorted_listings, 1):
        ratio = _insured_value_ratio(nft)
        logger.info(
            "[%d/%d] IV ratio=%.2f | Analyzing: %s",
            i, len(sorted_listings), ratio, nft.title[:60],
        )

        result = analyze_single_nft(nft)
        if result:
            result.insured_value_ratio = ratio
            opportunities.append(result)
            pc_info = ""
            if result.pc_matched_price_usd > 0:
                pc_info = f" PC=${result.pc_matched_price_usd:.0f}"
            logger.info(
                ">>> OPPORTUNITY #%d: +%.1f%% (confidence: %.0f%%, IV: %.2f%s) on '%s'",
                len(opportunities),
                result.profit_percent,
                result.match_confidence * 100,
                ratio,
                pc_info,
                nft.title[:50],
            )

        # Rate limiting for eBay
        time.sleep(EBAY_REQUEST_DELAY)

    # Sort by profit percentage descending
    opportunities.sort(key=lambda x: x.profit_percent, reverse=True)

    logger.info(
        "Scan complete. Found %d arbitrage opportunities.",
        len(opportunities),
    )
    return opportunities
