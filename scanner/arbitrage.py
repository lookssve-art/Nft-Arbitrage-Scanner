"""Arbitrage detection engine.

Compares Magic Eden NFT prices against eBay sold item averages.
Only flags opportunities where eBay average >= MIN_PROFIT_PERCENT higher.

Output includes:
- Card title
- Magic Eden price (EUR)
- eBay average sold price (EUR)
- Percentage difference
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
from scanner.matcher import find_matching_sold_items
from scanner.models import ArbitrageOpportunity, NFTListing

logger = logging.getLogger(__name__)


def calculate_profit_percent(buy_price: float, sell_price: float) -> float:
    """Calculate profit percentage: ((sell - buy) / buy) * 100."""
    if buy_price <= 0:
        return 0.0
    return ((sell_price - buy_price) / buy_price) * 100.0


def analyze_single_nft(nft: NFTListing) -> ArbitrageOpportunity | None:
    """Analyze a single NFT for arbitrage potential.

    1. Search eBay for sold items matching the exact title
    2. Apply strict matching rules
    3. Calculate average sold price from valid matches
    4. Compare against Magic Eden price
    5. Only flag if profit >= MIN_PROFIT_PERCENT

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

    # Apply strict matching
    matches = find_matching_sold_items(nft, ebay_items)

    if len(matches) < EBAY_SOLD_SAMPLE_MIN:
        logger.debug(
            "Not enough strict matches for '%s': %d < %d",
            nft.title,
            len(matches),
            EBAY_SOLD_SAMPLE_MIN,
        )
        return None

    # Calculate average sold price from matches
    prices = [m.sold_price_eur for m in matches]
    avg_price = sum(prices) / len(prices)

    # Calculate profit
    profit_pct = calculate_profit_percent(nft.price_eur, avg_price)

    # Only flag if meets minimum threshold
    if profit_pct < MIN_PROFIT_PERCENT:
        logger.debug(
            "Profit %.1f%% below threshold %.1f%% for: %s",
            profit_pct,
            MIN_PROFIT_PERCENT,
            nft.title,
        )
        return None

    ebay_url = build_ebay_search_url(nft.title)

    opportunity = ArbitrageOpportunity(
        nft=nft,
        ebay_avg_price_eur=avg_price,
        ebay_sold_count=len(matches),
        profit_percent=profit_pct,
        ebay_search_url=ebay_url,
        ebay_matches=matches,
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
        logger.info("[%d/%d] Analyzing: %s", i, len(listings), nft.title)

        result = analyze_single_nft(nft)
        if result:
            opportunities.append(result)
            logger.info(
                ">>> OPPORTUNITY #%d: +%.1f%% on '%s'",
                len(opportunities),
                result.profit_percent,
                nft.title,
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
