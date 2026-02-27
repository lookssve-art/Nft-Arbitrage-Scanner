"""eBay sold items scraper for Pokemon cards.

Searches eBay Germany (ebay.de) for sold items matching NFT card titles.
- Builds targeted search queries using pokemon name + variant + card number + grading
- Filters out lots/bundles
- Supports both old (.s-item) and new (.s-card) eBay HTML layouts
- Parses prices in EUR (German format)
"""

import logging
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from scanner.card_parser import POKEMON_NAMES, parse_card_title
from scanner.config import (
    DEFAULT_HEADERS,
    EBAY_REQUEST_DELAY,
    EBAY_SEARCH_URL,
    EBAY_SOLD_SAMPLE_MAX,
)
from scanner.models import EbaySoldItem

logger = logging.getLogger(__name__)

# eBay search parameters for sold items in Germany
_EBAY_SOLD_PARAMS = {
    "LH_Complete": "1",     # Completed listings
    "LH_Sold": "1",         # Sold items only
    "LH_PrefLoc": "2",      # EU preferred location
    "_sop": "13",            # Sort by: End date: recent first
}


def _extract_search_terms(title: str) -> str:
    """Extract targeted search terms from an NFT title.

    Builds a much more specific query than before:
    pokemon_name + variant + card_number + grading + "Pokemon"

    Example:
      Input:  "2021 #170 Full Art/Galarian Articuno V PSA 10 Sword & Shield Chilling Reign Pokemon"
      Output: "Galarian Articuno V PSA 10 170 Chilling Reign Pokemon"
    """
    # Parse the title to get structured attributes
    attrs = parse_card_title(title)

    parts: list[str] = []

    # 1. Pokemon name (most important)
    if attrs.pokemon_name:
        parts.append(attrs.pokemon_name)
    else:
        # Fallback: try to find any pokemon name in the title
        title_lower = title.lower()
        for name in POKEMON_NAMES:
            if name.lower() in title_lower:
                parts.append(name)
                break

    # 2. Variant (V, Vmax, GX, EX, etc.)
    if attrs.variant:
        parts.append(attrs.variant)

    # 3. Grading (PSA 10, CGC 9.5, etc.)
    grade_match = re.search(
        r"\b(PSA|CGC|BGS|SGC|Beckett)\s+(\d{1,2}(?:\.\d)?)\b",
        title,
        re.IGNORECASE,
    )
    if grade_match:
        parts.append(grade_match.group(0))

    # 4. Card number (stripped of # prefix)
    if attrs.card_number:
        num = attrs.card_number.replace("#", "").strip()
        # Only add if it's informative (not just a single digit)
        if len(num) >= 2 or "/" in num:
            parts.append(num)

    # 5. Set name (if known and not too generic)
    if attrs.set_name and len(attrs.set_name) > 3:
        # Use the specific set, not the series
        # e.g., "Chilling Reign" not "Sword & Shield"
        set_name = attrs.set_name
        # Remove series prefix if present
        series_prefixes = [
            "Sword & Shield", "Sun & Moon", "Scarlet & Violet",
            "Black & White", "Diamond & Pearl", "XY",
        ]
        for prefix in series_prefixes:
            if set_name.startswith(prefix) and len(set_name) > len(prefix) + 2:
                remainder = set_name[len(prefix):].strip()
                if remainder:
                    set_name = remainder
                    break
        parts.append(set_name)

    # 6. Always include "Pokemon" for relevance
    parts.append("Pokemon")

    # 7. Language for Japanese cards (important filter)
    if attrs.language and attrs.language.lower() == "japanese":
        parts.append("Japanese")

    # Build query - deduplicate
    seen = set()
    unique_parts = []
    for p in parts:
        p_lower = p.lower()
        if p_lower not in seen:
            seen.add(p_lower)
            unique_parts.append(p)

    query = " ".join(unique_parts)

    # Sanity check: must have at least 2 meaningful parts
    if len(unique_parts) < 3:
        # Fallback: use first 60 chars of title
        query = title[:60].strip()

    logger.debug("Search terms for '%s': '%s'", title[:60], query)
    return query


def build_ebay_search_url(title: str) -> str:
    """Build eBay.de search URL for sold items matching the card."""
    search_terms = _extract_search_terms(title)
    params = {
        "_nkw": search_terms,
        **_EBAY_SOLD_PARAMS,
    }
    return f"{EBAY_SEARCH_URL}?{urlencode(params)}"


def search_sold_items(title: str, max_results: int = EBAY_SOLD_SAMPLE_MAX) -> list[EbaySoldItem]:
    """Search eBay.de for sold items matching the card title.

    Uses targeted keyword extraction, then parses and filters results.
    Filters out lots/bundles from results.
    """
    url = build_ebay_search_url(title)
    logger.info("Searching eBay: %s", url)

    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        if resp.status_code == 429:
            logger.warning("eBay rate limited. Waiting 10 seconds...")
            time.sleep(10)
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
            except Exception:
                logger.error("eBay retry failed for: %s", title)
                return []
        else:
            logger.error("eBay HTTP error for: %s", title)
            return []
    except Exception as e:
        logger.error("eBay request error: %s", e)
        return []

    items = _parse_search_results(resp.text, max_results * 2)  # Over-fetch to allow filtering

    # Post-filter: remove lots/bundles
    filtered = [item for item in items if not item.attributes.is_lot]
    if len(filtered) < len(items):
        logger.debug(
            "Filtered %d lots/bundles from %d results",
            len(items) - len(filtered),
            len(items),
        )

    return filtered[:max_results]


def _parse_search_results(html: str, max_results: int) -> list[EbaySoldItem]:
    """Parse eBay search results HTML to extract sold items.

    Supports both old (.s-item) and new (li.s-card) eBay layouts.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[EbaySoldItem] = []

    # Try new layout first (2025+): li.s-card within ul.srp-results
    result_items = soup.select("ul.srp-results > li.s-card")

    if result_items:
        for item_el in result_items:
            if len(items) >= max_results:
                break
            sold_item = _parse_new_layout_result(item_el)
            if sold_item:
                items.append(sold_item)
    else:
        # Fallback to old layout: .s-item
        result_items = soup.select(".s-item")
        for item_el in result_items:
            if len(items) >= max_results:
                break
            sold_item = _parse_old_layout_result(item_el)
            if sold_item:
                items.append(sold_item)

    logger.info("Found %d sold items on eBay", len(items))
    return items


def _parse_new_layout_result(item_el) -> EbaySoldItem | None:
    """Parse a single eBay result in the new s-card layout (2025+)."""
    try:
        # Title: .text-bold or span[role="heading"]
        title_el = (
            item_el.select_one("a .text-bold")
            or item_el.select_one("a span[role='heading']")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        # Price: find EUR/$ text within the element
        price_texts = item_el.find_all(string=re.compile(r"EUR|€|\$"))
        if not price_texts:
            return None
        price_eur = _parse_eur_price(price_texts[0].strip())
        if price_eur is None or price_eur <= 0:
            return None

        # URL
        url = ""
        link_el = item_el.select_one('a[href*="itm/"]')
        if link_el:
            url = link_el.get("href", "")

        attributes = parse_card_title(title)

        return EbaySoldItem(
            title=title,
            sold_price_eur=price_eur,
            sold_date="",
            url=url,
            attributes=attributes,
        )
    except Exception as e:
        logger.debug("Failed to parse eBay new-layout result: %s", e)
        return None


def _parse_old_layout_result(item_el) -> EbaySoldItem | None:
    """Parse a single eBay result in the old s-item layout."""
    try:
        title_el = item_el.select_one(".s-item__title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        if not title or title.lower().startswith("shop on ebay") or title.lower().startswith("ergebnisse"):
            return None

        price_el = item_el.select_one(".s-item__price")
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True)
        price_eur = _parse_eur_price(price_text)
        if price_eur is None or price_eur <= 0:
            return None

        sold_date = ""
        date_el = item_el.select_one(".s-item__ended-date, .s-item__endedDate, .POSITIVE")
        if date_el:
            sold_date = date_el.get_text(strip=True)

        url = ""
        link_el = item_el.select_one("a.s-item__link")
        if link_el:
            url = link_el.get("href", "")

        attributes = parse_card_title(title)

        return EbaySoldItem(
            title=title,
            sold_price_eur=price_eur,
            sold_date=sold_date,
            url=url,
            attributes=attributes,
        )
    except Exception as e:
        logger.debug("Failed to parse eBay old-layout result: %s", e)
        return None


def _parse_eur_price(price_text: str) -> float | None:
    """Parse EUR price from eBay price string.

    Handles formats like:
    - "EUR 150,00"
    - "150,00 EUR"
    - "EUR 1.500,00"
    - "150.00 EUR"
    - "$45.99"
    """
    cleaned = price_text.replace("EUR", "").replace("€", "").replace("$", "").strip()

    # Handle "Bis" / "to" price ranges - take the first price
    if " bis " in cleaned.lower():
        cleaned = cleaned.lower().split(" bis ")[0].strip()
    elif " to " in cleaned.lower():
        cleaned = cleaned.lower().split(" to ")[0].strip()

    # German format: 1.500,00 -> 1500.00
    if "," in cleaned:
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", ".")

    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None
