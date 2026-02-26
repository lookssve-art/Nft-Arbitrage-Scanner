"""Magic Eden API scraper for Collector Crypt Pokemon card NFTs.

Fetches listings from the Collector Crypt collection on Magic Eden (Solana).
- Always uses "Recently Listed" sort order
- Paginates correctly to collect up to MAX_NFT_COUNT Pokemon items
- Fetches token metadata to get exact card names
- Filters for Pokemon cards only (via category attribute)
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

# Keywords that identify a Pokemon card in the title or attributes
_POKEMON_KEYWORDS = {"pokemon", "pokémon", "pikachu", "charizard", "mewtwo", "blastoise",
                     "venusaur", "eevee", "snorlax", "gengar", "dragonite", "mew",
                     "lugia", "ho-oh", "rayquaza", "umbreon", "espeon"}


def _build_headers() -> dict[str, str]:
    """Build request headers including API key if available."""
    headers = dict(DEFAULT_HEADERS)
    if MAGIC_EDEN_API_KEY:
        headers["Authorization"] = f"Bearer {MAGIC_EDEN_API_KEY}"
    return headers


def _get_listing_url(symbol: str, offset: int, limit: int) -> str:
    """Build the API URL for fetching listings sorted by 'Recently Listed'."""
    return (
        f"{MAGIC_EDEN_API_BASE}/collections/{quote(symbol)}/listings"
        f"?offset={offset}&limit={limit}"
    )


def _fetch_token_metadata(token_mint: str, headers: dict) -> dict | None:
    """Fetch token metadata from Magic Eden to get the card name and attributes."""
    url = f"{MAGIC_EDEN_API_BASE}/tokens/{token_mint}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 429:
            logger.warning("Rate limited on metadata. Waiting 5 seconds...")
            time.sleep(5)
            resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("Failed to fetch metadata for %s: %s", token_mint, e)
        return None


def _is_pokemon_card(name: str, attributes: list[dict]) -> bool:
    """Check if a card is a Pokemon card based on name and attributes."""
    name_lower = name.lower()
    # Check category attribute
    for attr in attributes:
        trait = str(attr.get("trait_type", "")).lower()
        value = str(attr.get("value", "")).lower()
        if trait in ("category", "sport", "type"):
            if "pokemon" in value or "pokémon" in value:
                return True
    # Check name for Pokemon keywords
    for kw in _POKEMON_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def fetch_listings(
    symbol: str = COLLECTION_SYMBOL,
    max_count: int = MAX_NFT_COUNT,
) -> list[NFTListing]:
    """Fetch up to max_count Pokemon NFT listings from Magic Eden.

    Fetches listings with pagination, then retrieves metadata for each token
    to get the actual card name. Filters to Pokemon cards only.

    Returns:
        List of NFTListing objects with exact titles, prices, and EUR conversions.
    """
    headers = _build_headers()
    all_listings: list[NFTListing] = []
    offset = 0
    page_size = MAGIC_EDEN_PAGE_SIZE
    empty_pages = 0
    # We need to over-fetch since not all cards are Pokemon
    # Collector Crypt has ~20% Pokemon cards, so fetch ~5x more raw listings
    max_raw_pages = (max_count * 5) // page_size + 10

    logger.info(
        "Fetching up to %d Pokemon listings from collection '%s'...",
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

            listing = _parse_listing_with_metadata(item, headers)
            if listing:
                all_listings.append(listing)
                logger.info(
                    "[%d/%d] %s | %.4f %s (€%.2f)",
                    len(all_listings), max_count,
                    listing.title[:60],
                    listing.price, listing.currency.value,
                    listing.price_eur,
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


def _parse_listing_with_metadata(item: dict, headers: dict) -> NFTListing | None:
    """Parse a single listing, fetching token metadata for the card name.

    Only returns Pokemon cards. Non-Pokemon cards return None.
    """
    try:
        token_mint = item.get("tokenMint", "")
        if not token_mint:
            return None

        # Fetch token metadata to get the real card name
        metadata = _fetch_token_metadata(token_mint, headers)
        if not metadata:
            return None

        title = metadata.get("name", "")
        if not title:
            return None

        # Check if it's a Pokemon card
        attributes = metadata.get("attributes", []) or []
        if not _is_pokemon_card(title, attributes):
            logger.debug("Skipping non-Pokemon card: %s", title)
            return None

        # Extract price
        price_raw = item.get("price", 0)
        currency = Currency.SOL
        price = float(price_raw)

        # Check if payment is in USDC
        payment_mint = item.get("paymentMint", "")
        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        if payment_mint == usdc_mint:
            currency = Currency.USDC
            if price > 1_000_000:
                price = price / USDC_DECIMALS

        # Convert to EUR
        price_eur = convert_to_eur(price, currency.value)

        # Build Magic Eden URL
        me_url = f"https://magiceden.us/item-details/solana/{token_mint}"

        # Parse card attributes from the exact title
        card_attrs = parse_card_title(title)

        # Brief pause for rate limiting on metadata calls
        time.sleep(0.3)

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
