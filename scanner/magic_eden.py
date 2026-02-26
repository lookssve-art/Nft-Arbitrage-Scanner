"""Magic Eden API scraper for Collector Crypt Pokemon card NFTs.

Fetches listings from the Collector Crypt collection on Magic Eden (Solana).
- ALWAYS sorts by "Recently Listed" (sort=updatedAt, sort_direction=desc)
- Never defaults to "Trending" or price sort
- Paginates correctly (limit=100 per page) to collect up to MAX_NFT_COUNT Pokemon items
- Uses token.name from the API response (no separate metadata call needed)
- Filters for Pokemon cards only (via Category attribute)
- Extracts exact title, price, and currency (SOL/USDC)
- Never modifies or trims the title
- Provides direct Magic Eden links per NFT
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
    MAX_NFT_COUNT,
    REQUEST_DELAY,
)
from scanner.currency import convert_to_eur
from scanner.models import Currency, NFTListing

logger = logging.getLogger(__name__)

# USDC has 6 decimals on Solana
USDC_DECIMALS = 1_000_000


def _build_headers() -> dict[str, str]:
    """Build request headers including API key if available."""
    headers = dict(DEFAULT_HEADERS)
    if MAGIC_EDEN_API_KEY:
        headers["Authorization"] = f"Bearer {MAGIC_EDEN_API_KEY}"
    return headers


def _get_listing_url(symbol: str, offset: int, limit: int) -> str:
    """Build the API URL for fetching listings sorted by 'Recently Listed'.

    CRITICAL: Always uses sort=updatedAt&sort_direction=desc to get
    recently listed items, NOT default price sort.
    """
    return (
        f"{MAGIC_EDEN_API_BASE}/collections/{quote(symbol)}/listings"
        f"?offset={offset}&limit={limit}"
        f"&sort=updatedAt&sort_direction=desc"
    )


def _is_pokemon_card(attributes: list[dict]) -> bool:
    """Check if a card is a Pokemon card based on its Category attribute."""
    for attr in attributes:
        trait = str(attr.get("trait_type", "")).lower()
        value = str(attr.get("value", "")).lower()
        if trait == "category" and ("pokemon" in value or "pokémon" in value):
            return True
    return False


def fetch_listings(
    symbol: str = COLLECTION_SYMBOL,
    max_count: int = MAX_NFT_COUNT,
) -> list[NFTListing]:
    """Fetch up to max_count Pokemon NFT listings from Magic Eden.

    ALWAYS sorted by Recently Listed (updatedAt desc).
    Uses limit=100 per page for efficiency.
    Filters to Pokemon cards only via Category attribute.

    Returns:
        List of NFTListing objects with exact titles, prices, EUR conversions,
        and direct Magic Eden links.
    """
    headers = _build_headers()
    all_listings: list[NFTListing] = []
    offset = 0
    page_size = 100  # API supports up to 100 per page
    empty_pages = 0
    # Over-fetch since not all cards are Pokemon (~60% are Pokemon based on data)
    max_raw_pages = (max_count * 3) // page_size + 5

    logger.info(
        "Fetching up to %d Pokemon listings from '%s' (Recently Listed)...",
        max_count,
        symbol,
    )

    pages_fetched = 0
    while len(all_listings) < max_count and pages_fetched < max_raw_pages:
        url = _get_listing_url(symbol, offset, page_size)
        logger.debug("Requesting page %d: %s", pages_fetched + 1, url)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 429:
                logger.warning("Rate limited. Waiting 5 seconds...")
                time.sleep(5)
                continue
            logger.error("HTTP error fetching listings (status %d)", resp.status_code)
            break
        except Exception as e:
            logger.error("Error fetching listings: %s", e)
            break

        if not data:
            empty_pages += 1
            if empty_pages >= 3:
                logger.info("No more listings available (3 empty pages).")
                break
            offset += page_size
            pages_fetched += 1
            time.sleep(REQUEST_DELAY)
            continue

        empty_pages = 0

        for item in data:
            if len(all_listings) >= max_count:
                break

            listing = _parse_listing(item)
            if listing:
                all_listings.append(listing)
                logger.info(
                    "[%d/%d] %.4f %s (€%.2f) | %s",
                    len(all_listings), max_count,
                    listing.price, listing.currency.value,
                    listing.price_eur,
                    listing.title[:60],
                )

        offset += page_size
        pages_fetched += 1
        logger.info(
            "Page %d done. Pokemon found: %d/%d",
            pages_fetched, len(all_listings), max_count,
        )
        time.sleep(REQUEST_DELAY)

    logger.info("Total Pokemon listings fetched: %d", len(all_listings))
    return all_listings


def _parse_listing(item: dict) -> NFTListing | None:
    """Parse a single listing from the API response.

    The API returns token info directly in item['token'], including:
    - token.name: exact card title
    - token.mintAddress: for direct link
    - token.attributes: Category, Grading Company, Grade, etc.

    Only returns Pokemon cards. Non-Pokemon cards return None.
    """
    try:
        token = item.get("token", {}) or {}
        token_mint = token.get("mintAddress", "") or item.get("tokenMint", "")

        # Get the card name directly from token data
        title = token.get("name", "")
        if not title:
            return None

        # Get attributes and check if Pokemon
        attributes = token.get("attributes", []) or []
        if not _is_pokemon_card(attributes):
            return None

        # Extract price
        price_raw = item.get("price", 0)
        currency = Currency.SOL
        price = float(price_raw)

        # Check if payment is in USDC
        price_info = item.get("priceInfo", {}) or {}
        sol_price = price_info.get("solPrice", {}) or {}
        payment_address = sol_price.get("address", "")
        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        if payment_address == usdc_mint:
            currency = Currency.USDC
            if price > 1_000_000:
                price = price / USDC_DECIMALS

        # Convert to EUR using live rates
        price_eur = convert_to_eur(price, currency.value)

        # Direct Magic Eden link to this specific NFT
        me_url = f"https://magiceden.us/item-details/{token_mint}"

        # Parse card attributes from the exact title
        card_attrs = parse_card_title(title)

        return NFTListing(
            title=title,
            price=price,
            currency=currency,
            price_eur=price_eur,
            mint_address=token_mint,
            magic_eden_url=me_url,
            attributes=card_attrs,
        )
    except Exception as e:
        logger.debug("Failed to parse listing: %s", e)
        return None
