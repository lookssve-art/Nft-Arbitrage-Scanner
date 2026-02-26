"""eBay sold items scraper for Pokemon cards.

Searches eBay Germany (ebay.de) for sold items matching NFT card titles.
- Extracts key terms (Pokemon name, grading, set) from NFT title for search
- Filters by "Sold Items" (Verkaufte Artikel)
- Region: Germany + EU
- Currency: EUR
- Applies strict matching on results

Uses smart search: extracts key terms from NFT title rather than exact
title search, because Magic Eden and eBay use different title formats.

eBay HTML structure (2025+): listings use li.s-card with .text-bold titles.
Handles both old (.s-item) and new (.s-card) eBay layouts.
"""

import logging
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from scanner.card_parser import parse_card_title
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
    "LH_Complete": "1",  # Completed listings
    "LH_Sold": "1",  # Sold items only
    "LH_PrefLoc": "2",  # EU preferred location
    "_sop": "13",  # Sort by: End date: recent first
}

# Known Pokemon names for search term extraction
_POKEMON_NAMES = [
    "Charizard", "Pikachu", "Mewtwo", "Blastoise", "Venusaur", "Eevee",
    "Umbreon", "Rayquaza", "Lugia", "Ho-Oh", "Gengar", "Dragonite",
    "Snorlax", "Mew", "Jolteon", "Flareon", "Vaporeon", "Espeon",
    "Glaceon", "Leafeon", "Sylveon", "Zapdos", "Articuno", "Moltres",
    "Raichu", "Kangaskhan", "Diancie", "Swablu", "Zekrom", "Reshiram",
    "Yveltal", "Victini", "Haunter", "Tapu Koko", "Feraligatr",
    "Scizor", "Tyranitar", "Bulbasaur", "Meowth", "Gyarados",
    "Hoopa", "Gardevoir", "Ninetales", "Lucario", "Deoxys",
    "Ditto", "Shuckle", "Inteleon", "Calyrex", "Machoke",
]


def _extract_search_terms(title: str) -> str:
    """Extract optimal search terms from an NFT title for eBay search.

    Instead of searching for the exact long NFT title (which never matches
    eBay's different formatting), extract: Pokemon name + grading + "Pokemon".
    """
    # Extract grading info
    grade_match = re.search(
        r"\b(PSA|CGC|BGS|Beckett)\s+(\d{1,2}(?:\.\d)?)\b",
        title,
        re.IGNORECASE,
    )
    grading = grade_match.group(0) if grade_match else ""

    # Extract Pokemon name
    pokemon = ""
    for name in sorted(_POKEMON_NAMES, key=len, reverse=True):
        if name.lower() in title.lower():
            pokemon = name
            break

    # Build search query
    parts = [p for p in [pokemon, grading, "Pokemon"] if p]
    return " ".join(parts) if len(parts) > 1 else title[:50]


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

    Uses smart keyword extraction for the search, then parses results.
    """
    url = build_ebay_search_url(title)
    logger.info("Searching eBay: %s", url)

    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
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
            logger.error("eBay HTTP error: %s", e)
            return []
    except Exception as e:
        logger.error("eBay request error: %s", e)
        return []

    return _parse_search_results(resp.text, max_results)


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

        # Price: find EUR/€ text within the element
        price_texts = item_el.find_all(string=re.compile(r"EUR|€"))
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
    - "150,00 €"
    - "EUR 1.500,00"
    - "150.00 €"
    - "$45.99" (USD)
    """
    cleaned = price_text.replace("EUR", "").replace("€", "").replace("$", "").strip()

    # Handle "Bis" / "to" price ranges - take the first price
    if " bis " in cleaned.lower():
        cleaned = cleaned.lower().split(" bis ")[0].strip()
    elif " to " in cleaned.lower():
        cleaned = cleaned.lower().split(" to ")[0].strip()

    # German format: 1.500,00 → 1500.00
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
