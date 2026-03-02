"""Phygitals marketplace API client for Pokemon card NFTs.

Fetches listings from the Phygitals aggregator marketplace.
Phygitals shows cards from multiple vaults (Collector Crypt, Fanatics,
PSA, ALT) across Solana marketplaces (Magic Eden, Tensor).

Primary endpoint: /marketplace/marketplace-listings
Fallback: Magic Eden collection API + Phygitals /single-nft for metadata/FMV

API base: https://api.phygitals.com/api
Prices are in USDC (6 decimals raw). FMV from Alt.xyz included.
"""

import logging
import time

import requests

from scanner.card_parser import extract_from_me_attributes, parse_card_title
from scanner.config import DEFAULT_HEADERS, MAGIC_EDEN_API_BASE, REQUEST_DELAY
from scanner.currency import get_usd_to_eur_rate
from scanner.models import CardAttributes, Currency, GradingCompany, NFTListing

logger = logging.getLogger(__name__)

PHYGITALS_API_BASE = "https://api.phygitals.com/api"
USDC_RAW_DIVISOR = 1_000_000  # USDC has 6 decimals
PHYGITALS_ME_COLLECTION = "phygitals"  # Magic Eden collection symbol


def fetch_phygitals_listings(
    max_count: int = 250,
    sort_by: str = "recently_listed",
) -> list[NFTListing]:
    """Fetch listed Pokemon cards from the Phygitals marketplace.

    Tries the primary marketplace-listings endpoint first.
    Falls back to Magic Eden collection API + single-nft enrichment
    if the primary endpoint is unavailable (500 errors).

    Args:
        max_count: Maximum number of listings to fetch.
        sort_by: Sort order (price_desc, price_asc, recently_listed, fmv_desc).

    Returns:
        List of NFTListing objects.
    """
    # Try primary endpoint first
    listings = _fetch_via_listings_endpoint(max_count, sort_by)
    if listings:
        return listings

    # Fallback: Magic Eden collection + Phygitals single-nft for enrichment
    logger.warning(
        "Phygitals listings endpoint unavailable. "
        "Falling back to Magic Eden collection + single-nft enrichment."
    )
    return _fetch_via_magic_eden_fallback(max_count)


def _fetch_via_listings_endpoint(
    max_count: int,
    sort_by: str,
) -> list[NFTListing]:
    """Fetch from the primary Phygitals marketplace-listings endpoint."""
    all_listings: list[NFTListing] = []
    page = 1
    items_per_page = 100
    empty_pages = 0

    logger.info(
        "Fetching up to %d Pokemon listings from Phygitals (%s)...",
        max_count,
        sort_by,
    )

    while len(all_listings) < max_count:
        url = f"{PHYGITALS_API_BASE}/marketplace/marketplace-listings"
        params = {
            "searchTerm": "",
            "sortBy": sort_by,
            "itemsPerPage": items_per_page,
            "page": page,
            "metadataConditions": '{"category":["Pokemon"]}',
            "priceRange": "{}",
            "fmvRange": "{}",
            "listedStatus": "listed",
            "collectionAddresses": "[]",
        }

        try:
            resp = requests.get(
                url,
                params=params,
                headers=DEFAULT_HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 429:
                logger.warning("Rate limited. Waiting 5 seconds...")
                time.sleep(5)
                continue
            if resp.status_code >= 500:
                logger.warning(
                    "Phygitals server error %d — endpoint may be down.",
                    resp.status_code,
                )
                return []  # Trigger fallback
            logger.error("HTTP error %d from Phygitals", resp.status_code)
            break
        except Exception as e:
            logger.error("Error fetching Phygitals listings: %s", e)
            break

        listings = data.get("listings", [])
        if not listings:
            empty_pages += 1
            if empty_pages >= 2:
                logger.info("No more Phygitals listings (2 empty pages).")
                break
            page += 1
            time.sleep(REQUEST_DELAY)
            continue

        empty_pages = 0

        for item in listings:
            if len(all_listings) >= max_count:
                break

            parsed = _parse_phygitals_listing(item)
            if parsed:
                all_listings.append(parsed)

        page += 1
        logger.info(
            "Phygitals page %d done. Found: %d/%d",
            page - 1,
            len(all_listings),
            max_count,
        )
        time.sleep(REQUEST_DELAY)

    logger.info("Total Phygitals listings fetched: %d", len(all_listings))
    return all_listings


def _fetch_via_magic_eden_fallback(max_count: int) -> list[NFTListing]:
    """Fetch Phygitals listings via Magic Eden collection API + single-nft enrichment.

    1. Get listings from ME collection API (sorted by price ascending)
    2. For each listing, call Phygitals single-nft to get FMV and metadata
    3. Filter to Pokemon cards only
    """
    all_listings: list[NFTListing] = []
    offset = 0
    page_size = 20  # ME returns max 20 per page for collection listings
    empty_pages = 0

    logger.info(
        "Fetching Phygitals listings via Magic Eden fallback (up to %d)...",
        max_count,
    )

    while len(all_listings) < max_count:
        url = (
            f"{MAGIC_EDEN_API_BASE}/collections/{PHYGITALS_ME_COLLECTION}/listings"
            f"?offset={offset}&limit={page_size}"
        )

        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 429:
                logger.warning("ME rate limited. Waiting 5 seconds...")
                time.sleep(5)
                continue
            logger.error("ME HTTP error %d for Phygitals collection", resp.status_code)
            break
        except Exception as e:
            logger.error("Error fetching ME Phygitals listings: %s", e)
            break

        if not data:
            empty_pages += 1
            if empty_pages >= 3:
                logger.info("No more ME listings (3 empty pages).")
                break
            offset += page_size
            time.sleep(REQUEST_DELAY)
            continue

        empty_pages = 0

        for item in data:
            if len(all_listings) >= max_count:
                break

            token_mint = item.get("tokenMint", "")
            if not token_mint:
                continue

            sol_price = float(item.get("price", 0))
            if sol_price <= 0:
                continue

            # Enrich with Phygitals single-nft data (FMV, name, metadata)
            nft_data = _fetch_single_nft(token_mint)
            if not nft_data:
                continue

            # Filter Pokemon cards only
            if not _is_pokemon_card_from_metadata(
                nft_data.get("metadata", []), nft_data.get("name", "")
            ):
                continue

            parsed = _parse_me_listing_with_phygitals(item, nft_data)
            if parsed:
                all_listings.append(parsed)

            time.sleep(0.3)  # Rate limit for single-nft calls

        offset += page_size
        logger.info(
            "ME fallback page done. Pokemon found: %d/%d",
            len(all_listings),
            max_count,
        )
        time.sleep(REQUEST_DELAY)

    logger.info(
        "Total Phygitals listings via ME fallback: %d", len(all_listings)
    )
    return all_listings


def _fetch_single_nft(address: str) -> dict | None:
    """Fetch NFT details from Phygitals single-nft endpoint."""
    url = f"{PHYGITALS_API_BASE}/marketplace/single-nft"
    try:
        resp = requests.get(
            url,
            params={"address": address},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("Failed to fetch single-nft %s: %s", address[:20], e)
        return None


def _is_pokemon_card_from_metadata(metadata: list, name: str = "") -> bool:
    """Check if NFT is a Pokemon card based on Phygitals metadata or name."""
    if isinstance(metadata, list):
        for entry in metadata:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", "")).lower()
            value = str(entry.get("value", "")).lower()
            if key == "category" and ("pokemon" in value or "pokémon" in value):
                return True
    # Fallback: check the card name for Pokemon-related keywords
    name_lower = name.lower()
    pokemon_keywords = ("pokemon", "pokémon", "pikachu", "charizard")
    return any(kw in name_lower for kw in pokemon_keywords)


def _parse_me_listing_with_phygitals(
    me_item: dict, nft_data: dict
) -> NFTListing | None:
    """Parse a Magic Eden listing enriched with Phygitals single-nft data."""
    try:
        title = nft_data.get("name", "")
        if not title:
            return None

        # Skip burned items
        if nft_data.get("burned", False):
            return None

        # Price from ME listing (SOL)
        sol_price = float(me_item.get("price", 0))
        currency = Currency.SOL

        # Check if payment is in USDC
        price_info = me_item.get("priceInfo", {}) or {}
        sol_price_info = price_info.get("solPrice", {}) or {}
        payment_address = sol_price_info.get("address", "")
        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        if payment_address == usdc_mint:
            currency = Currency.USDC
            if sol_price > 1_000_000:
                sol_price = sol_price / USDC_RAW_DIVISOR

        # Check if also listed on Phygitals marketplace with USDC price
        phyg_price_raw = nft_data.get("price")
        if nft_data.get("listed") and phyg_price_raw:
            # Prefer Phygitals USDC price if available (more direct)
            phyg_price_usd = int(phyg_price_raw) / USDC_RAW_DIVISOR
            if phyg_price_usd > 0:
                sol_price = phyg_price_usd
                currency = Currency.USDC

        if sol_price <= 0:
            return None

        # Convert to EUR
        from scanner.currency import convert_to_eur
        price_eur = convert_to_eur(sol_price, currency.value)

        # Build card URL
        slug = nft_data.get("slug", "")
        token_mint = me_item.get("tokenMint", "")
        card_url = f"https://www.phygitals.com/card/{slug}" if slug else ""

        # FMV from Phygitals
        fmv_raw = nft_data.get("altFmv") or "0"
        fmv_usd = float(fmv_raw) if fmv_raw else 0.0

        # Parse card attributes from title
        card_attrs = parse_card_title(title)

        # Enrich with Phygitals metadata
        metadata = nft_data.get("metadata", [])
        me_attrs = _convert_metadata_to_me_format(metadata)
        card_attrs = extract_from_me_attributes(me_attrs, card_attrs)

        vault = nft_data.get("vault") or "phygitals"
        marketplace = nft_data.get("marketplace", "")

        return NFTListing(
            title=title,
            price=sol_price,
            currency=currency,
            price_eur=price_eur,
            mint_address=token_mint,
            magic_eden_url=card_url,
            attributes=card_attrs,
            raw_me_attributes=me_attrs,
            insured_value_usd=fmv_usd,
            source=f"phygitals/{vault}",
        )
    except Exception as e:
        logger.debug("Failed to parse ME+Phygitals listing: %s", e)
        return None


def _parse_phygitals_listing(item: dict) -> NFTListing | None:
    """Parse a single Phygitals listing into an NFTListing.

    Phygitals data format:
    - price: raw USDC (6 decimals), e.g. "45000000" = $45.00
    - altFmv: Fair Market Value from Alt.xyz (USD string)
    - slug: URL slug for phygitals.com/card/{slug}
    - metadata: [{key, value}, ...] with card attributes
    - vault: "cc", "alt", "fanatics", "psa", or null
    """
    try:
        title = item.get("name", "")
        if not title:
            return None

        # Skip non-listed or burned
        if not item.get("listed", False) or item.get("burned", False):
            return None

        # Parse price (USDC raw -> USD)
        price_raw = item.get("price", "0") or "0"
        price_usd = int(price_raw) / USDC_RAW_DIVISOR
        if price_usd <= 0:
            return None

        # Convert to EUR
        usd_eur = get_usd_to_eur_rate()
        price_eur = price_usd * usd_eur

        # Build Phygitals card URL
        slug = item.get("slug", "")
        card_url = f"https://www.phygitals.com/card/{slug}" if slug else ""

        address = item.get("address", "")

        # Extract FMV (Fair Market Value)
        fmv_raw = item.get("altFmv") or "0"
        fmv_usd = float(fmv_raw) if fmv_raw else 0.0

        # Parse card attributes from title
        card_attrs = parse_card_title(title)

        # Enrich with Phygitals metadata
        metadata = item.get("metadata", [])
        me_attrs = _convert_metadata_to_me_format(metadata)
        card_attrs = extract_from_me_attributes(me_attrs, card_attrs)

        # Build source info
        vault = item.get("vault") or "phygitals"

        return NFTListing(
            title=title,
            price=price_usd,
            currency=Currency.USDC,
            price_eur=price_eur,
            mint_address=address,
            magic_eden_url=card_url,
            attributes=card_attrs,
            raw_me_attributes=me_attrs,
            insured_value_usd=fmv_usd,
            source=f"phygitals/{vault}",
        )
    except Exception as e:
        logger.debug("Failed to parse Phygitals listing: %s", e)
        return None


def _convert_metadata_to_me_format(metadata: list) -> list[dict]:
    """Convert Phygitals metadata to Magic Eden attribute format.

    Phygitals: [{"key": "Name", "value": "Pikachu"}, ...]
    ME format: [{"trait_type": "Name", "value": "Pikachu"}, ...]
    """
    if not isinstance(metadata, list):
        return []
    return [
        {"trait_type": entry.get("key", ""), "value": entry.get("value", "")}
        for entry in metadata
        if isinstance(entry, dict) and entry.get("key") and entry.get("value")
    ]
