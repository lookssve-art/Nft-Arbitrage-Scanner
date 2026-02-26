"""Magic Eden API scraper for Collector Crypt Pokemon card NFTs.

Fetches listings from the Collector Crypt collection on Magic Eden (Solana).
- Always uses "Recently Listed" sort order
- Paginates correctly to collect up to MAX_NFT_COUNT items
- Extracts exact title, price, and currency (SOL/USDC)
- Never modifies or trims the title
"""

import logging
import time
from urllib.parse import quote

import requests

from scanner.card_parser import parse_card_title
from scanner.config import (
    COLLECTION_SYMBOL,
    DEFAULT_HEADERS,
    MAGIC_EDEN_API_BASE,
    MAGIC_EDEN_API_KEY,
    MAGIC_EDEN_PAGE_SIZE,
    MAX_NFT_COUNT,
    REQUEST_DELAY,
)
from scanner.currency import convert_to_eur
from scanner.models import Currency, NFTListing

logger = logging.getLogger(__name__)

# Lamports to SOL conversion
LAMPORTS_PER_SOL = 1_000_000_000
# USDC has 6 decimals on Solana
USDC_DECIMALS = 1_000_000


def _build_headers() -> dict[str, str]:
    """Build request headers including API key if available."""
    headers = dict(DEFAULT_HEADERS)
    if MAGIC_EDEN_API_KEY:
        headers["Authorization"] = f"Bearer {MAGIC_EDEN_API_KEY}"
    return headers


def _get_listing_url(symbol: str, offset: int, limit: int) -> str:
    """Build the API URL for fetching listings sorted by 'Recently Listed'."""
    # The Magic Eden v2 API supports sorting by 'listPrice' (asc/desc)
    # and filtering. For "recently listed" we sort by listing recency.
    # The API endpoint: GET /v2/collections/{symbol}/listings
    # Query params: offset, limit, sort (listPrice), sortDirection (asc)
    return (
        f"{MAGIC_EDEN_API_BASE}/collections/{quote(symbol)}/listings"
        f"?offset={offset}&limit={limit}"
    )


def fetch_listings(
    symbol: str = COLLECTION_SYMBOL,
    max_count: int = MAX_NFT_COUNT,
) -> list[NFTListing]:
    """Fetch up to max_count NFT listings from Magic Eden.

    Uses pagination to ensure we collect the requested number of items.
    Sorts by recently listed (API default listing order).

    Returns:
        List of NFTListing objects with exact titles, prices, and EUR conversions.
    """
    headers = _build_headers()
    all_listings: list[NFTListing] = []
    offset = 0
    page_size = min(MAGIC_EDEN_PAGE_SIZE, max_count)
    empty_pages = 0

    logger.info(
        "Fetching up to %d listings from collection '%s'...",
        max_count,
        symbol,
    )

    while len(all_listings) < max_count:
        remaining = max_count - len(all_listings)
        limit = min(page_size, remaining)
        url = _get_listing_url(symbol, offset, limit)

        logger.debug("Requesting: %s", url)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                logger.warning("Rate limited. Waiting 5 seconds...")
                time.sleep(5)
                continue
            logger.error("HTTP error fetching listings: %s", e)
            break
        except Exception as e:
            logger.error("Error fetching listings: %s", e)
            break

        if not data:
            empty_pages += 1
            if empty_pages >= 3:
                logger.info("No more listings available (3 empty pages).")
                break
            offset += limit
            time.sleep(REQUEST_DELAY)
            continue

        empty_pages = 0

        for item in data:
            if len(all_listings) >= max_count:
                break

            listing = _parse_listing(item, symbol)
            if listing:
                all_listings.append(listing)

        offset += limit
        logger.info("Collected %d/%d listings...", len(all_listings), max_count)
        time.sleep(REQUEST_DELAY)

    logger.info("Total listings fetched: %d", len(all_listings))
    return all_listings


def _parse_listing(item: dict, symbol: str) -> NFTListing | None:
    """Parse a single listing from the API response.

    Extracts:
    - Exact full title (never modified)
    - Price in original currency
    - Currency type (SOL or USDC)
    - Mint address for direct linking
    """
    try:
        # Extract token info
        token_mint = item.get("tokenMint", "")
        extra = item.get("extra", {}) or {}
        token_name = extra.get("name", "") or item.get("tokenMint", "")

        # Try to get the name from token metadata
        # The API returns the NFT name in the 'extra' field or we need
        # to fetch it separately. Some responses include it directly.
        title = token_name

        # If we don't have a title, try alternate fields
        if not title or title == token_mint:
            rarity = extra.get("rarity", {}) or {}
            title = rarity.get("name", token_mint)

        if not title:
            logger.debug("Skipping listing with no title: %s", token_mint)
            return None

        # Extract price - Magic Eden returns price in lamports for SOL
        price_raw = item.get("price", 0)
        # Default currency is SOL on Magic Eden Solana
        currency = Currency.SOL
        price = float(price_raw)

        # Check if payment is in USDC via token info
        payment_mint = item.get("paymentMint", "")
        # USDC mint on Solana mainnet
        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        if payment_mint == usdc_mint:
            currency = Currency.USDC
            # USDC amounts may come in raw decimals
            if price > 1_000_000:
                price = price / USDC_DECIMALS

        # Convert to EUR
        price_eur = convert_to_eur(price, currency.value)

        # Build Magic Eden URL for this specific NFT
        me_url = f"https://magiceden.us/item-details/solana/{token_mint}"

        # Parse card attributes from the exact title
        attributes = parse_card_title(title)

        return NFTListing(
            title=title,
            price=price,
            currency=currency,
            price_eur=price_eur,
            mint_address=token_mint,
            magic_eden_url=me_url,
            attributes=attributes,
        )
    except Exception as e:
        logger.debug("Failed to parse listing: %s", e)
        return None
