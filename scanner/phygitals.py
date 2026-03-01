"""Phygitals marketplace API client for Pokemon card NFTs.

Fetches listings from the Phygitals aggregator marketplace.
Phygitals shows cards from multiple vaults (Collector Crypt, Fanatics,
PSA, ALT) across Solana marketplaces (Magic Eden, Tensor).

API base: https://api.phygitals.com/api
Key endpoint: /marketplace/marketplace-listings

Prices are in USDC (6 decimals raw). FMV from Alt.xyz included.
"""

import logging
import time

import requests

from scanner.card_parser import extract_from_me_attributes, parse_card_title
from scanner.config import DEFAULT_HEADERS, REQUEST_DELAY
from scanner.currency import get_usd_to_eur_rate
from scanner.models import CardAttributes, Currency, GradingCompany, NFTListing

logger = logging.getLogger(__name__)

PHYGITALS_API_BASE = "https://api.phygitals.com/api"
USDC_RAW_DIVISOR = 1_000_000  # USDC has 6 decimals


def fetch_phygitals_listings(
    max_count: int = 250,
    sort_by: str = "recently_listed",
) -> list[NFTListing]:
    """Fetch listed Pokemon cards from the Phygitals marketplace.

    Args:
        max_count: Maximum number of listings to fetch.
        sort_by: Sort order (price_desc, price_asc, recently_listed, fmv_desc).

    Returns:
        List of NFTListing objects.
    """
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
        marketplace = item.get("marketplace", "")

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


def _convert_metadata_to_me_format(metadata: list[dict]) -> list[dict]:
    """Convert Phygitals metadata to Magic Eden attribute format.

    Phygitals: [{"key": "Name", "value": "Pikachu"}, ...]
    ME format: [{"trait_type": "Name", "value": "Pikachu"}, ...]
    """
    return [
        {"trait_type": entry.get("key", ""), "value": entry.get("value", "")}
        for entry in metadata
        if entry.get("key") and entry.get("value")
    ]
