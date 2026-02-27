"""Arbitrage detection engine with confidence scoring.

Compares Magic Eden NFT prices against eBay sold item averages.
Uses the multi-signal matching engine for reliable 1:1 card identification.

Output includes:
- Card title and parsed attributes
- Magic Eden price (EUR)
- eBay average sold price from confirmed matches
- Profit percentage
- Match confidence score and evidence
- Direct links (Magic Eden + eBay search)
"""

import logging
import time

from scanner.config import (
    EBAY_REQUEST_DELAY,
    EBAY_SOLD_SAMPLE_MIN,
    MIN_PROFIT_PERCENT,
)
from scanner.ebay import build_ebay_search_url, search_sold_items
from scanner.matcher import find_scored_matches
from scanner.models import (
    ArbitrageOpportunity,
    MatchDecision,
    NFTListing,
    ScoredEbayMatch,
)

logger = logging.getLogger(__name__)


def calculate_profit_percent(buy_price: float, sell_price: float) -> float:
    """Calculate profit percentage: ((sell - buy) / buy) * 100."""
    if buy_price <= 0:
        return 0.0
    return ((sell_price - buy_price) / buy_price) * 100.0


def analyze_single_nft(nft: NFTListing) -> ArbitrageOpportunity | None:
    """Analyze a single NFT for arbitrage potential.

    1. Search eBay for sold items
    2. Score each result with multi-signal matcher
    3. Only use AUTO_MATCH results (confidence >= 0.85)
    4. Calculate average sold price from confirmed matches
    5. Flag if profit >= MIN_PROFIT_PERCENT

    Returns:
        ArbitrageOpportunity if found, None otherwise.
    """
    if nft.price_eur <= 0:
        logger.debug("Skipping NFT with zero EUR price: %s", nft.title)
        return None

    # Search eBay for sold items
    ebay_items = search_sold_items(nft.title)

    if not ebay_items:
        logger.debug("No eBay results for: %s", nft.title)
        return None

    # Score all eBay items with the multi-signal matcher
    scored_matches = find_scored_matches(
        nft,
        ebay_items,
        min_decision=MatchDecision.AUTO_MATCH,
    )

    if not scored_matches:
        logger.debug("No confident matches for: %s", nft.title)
        return None

    # Extract the confirmed matches
    confirmed_items = [sm.ebay_item for sm in scored_matches]

    if len(confirmed_items) < EBAY_SOLD_SAMPLE_MIN:
        logger.debug(
            "Not enough confident matches for '%s': %d < %d",
            nft.title[:50],
            len(confirmed_items),
            EBAY_SOLD_SAMPLE_MIN,
        )
        return None

    # Calculate average sold price from confirmed matches
    prices = [item.sold_price_eur for item in confirmed_items]
    avg_price = sum(prices) / len(prices)

    # Calculate average confidence
    avg_confidence = sum(
        sm.match_result.total_score for sm in scored_matches
    ) / len(scored_matches)

    # Calculate profit
    profit_pct = calculate_profit_percent(nft.price_eur, avg_price)

    if profit_pct < MIN_PROFIT_PERCENT:
        logger.debug(
            "Profit %.1f%% below threshold %.1f%% for: %s",
            profit_pct,
            MIN_PROFIT_PERCENT,
            nft.title[:50],
        )
        return None

    ebay_url = build_ebay_search_url(nft.title)

    opportunity = ArbitrageOpportunity(
        nft=nft,
        ebay_avg_price_eur=avg_price,
        ebay_sold_count=len(confirmed_items),
        profit_percent=profit_pct,
        ebay_search_url=ebay_url,
        ebay_matches=confirmed_items,
        match_confidence=avg_confidence,
        scored_matches=scored_matches,
    )

    logger.info("ARBITRAGE FOUND: %s", opportunity)
    return opportunity


def scan_for_arbitrage(listings: list[NFTListing]) -> list[ArbitrageOpportunity]:
    """Scan all NFT listings for arbitrage opportunities.

    Args:
        listings: List of NFT listings from Magic Eden.

    Returns:
        List of ArbitrageOpportunity, sorted by profit percentage (descending).
    """
    opportunities: list[ArbitrageOpportunity] = []

    logger.info("Scanning %d listings for arbitrage...", len(listings))

    for i, nft in enumerate(listings, 1):
        logger.info("[%d/%d] Analyzing: %s", i, len(listings), nft.title[:60])

        result = analyze_single_nft(nft)
        if result:
            opportunities.append(result)
            logger.info(
                ">>> OPPORTUNITY #%d: +%.1f%% (confidence: %.0f%%) on '%s'",
                len(opportunities),
                result.profit_percent,
                result.match_confidence * 100,
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
