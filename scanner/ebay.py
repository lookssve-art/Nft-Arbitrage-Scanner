"""eBay sold items scraper for Pokemon cards.

Searches eBay Germany (ebay.de) for sold items matching exact NFT titles.
- Uses exact title in quotes for search
- Filters by "Sold Items" (Verkaufte Artikel)
- Region: Germany + EU
- Currency: EUR
- Extracts sold prices and listing data

NO fuzzy matching. Uses exact quoted title search.
"""

import logging
import re
import time
from urllib.parse import quote_plus, urlencode

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


def build_ebay_search_url(title: str) -> str:
    """Build eBay.de search URL for exact title match in sold items."""
    # Wrap title in quotes for exact match
    quoted_title = f'"{title}"'
    params = {
        "_nkw": quoted_title,
        **_EBAY_SOLD_PARAMS,
    }
    return f"{EBAY_SEARCH_URL}?{urlencode(params)}"


def search_sold_items(title: str, max_results: int = EBAY_SOLD_SAMPLE_MAX) -> list[EbaySoldItem]:
    """Search eBay.de for sold items matching the exact title.

    Args:
        title: The exact NFT title to search for (will be quoted).
        max_results: Maximum number of results to return.

    Returns:
        List of EbaySoldItem with parsed prices and attributes.
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
    """Parse eBay search results HTML to extract sold items."""
    soup = BeautifulSoup(html, "lxml")
    items: list[EbaySoldItem] = []

    # eBay uses s-item class for search results
    result_items = soup.select(".s-item")

    for item_el in result_items:
        if len(items) >= max_results:
            break

        sold_item = _parse_single_result(item_el)
        if sold_item:
            items.append(sold_item)

    logger.info("Found %d sold items on eBay", len(items))
    return items


def _parse_single_result(item_el) -> EbaySoldItem | None:
    """Parse a single eBay search result element."""
    try:
        # Extract title
        title_el = item_el.select_one(".s-item__title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        # Skip eBay's "Shop on eBay" / "Ergebnisse" header items
        if not title or title.lower().startswith("shop on ebay") or title.lower().startswith("ergebnisse"):
            return None

        # Extract sold price
        price_el = item_el.select_one(".s-item__price")
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True)
        price_eur = _parse_eur_price(price_text)
        if price_eur is None or price_eur <= 0:
            return None

        # Extract sold date if available
        sold_date = ""
        date_el = item_el.select_one(".s-item__ended-date, .s-item__endedDate, .POSITIVE")
        if date_el:
            sold_date = date_el.get_text(strip=True)

        # Extract URL
        url = ""
        link_el = item_el.select_one("a.s-item__link")
        if link_el:
            url = link_el.get("href", "")

        # Parse card attributes from the eBay title
        attributes = parse_card_title(title)

        return EbaySoldItem(
            title=title,
            sold_price_eur=price_eur,
            sold_date=sold_date,
            url=url,
            attributes=attributes,
        )
    except Exception as e:
        logger.debug("Failed to parse eBay result: %s", e)
        return None


def _parse_eur_price(price_text: str) -> float | None:
    """Parse EUR price from eBay price string.

    Handles formats like:
    - "EUR 150,00"
    - "150,00 €"
    - "EUR 1.500,00"
    - "150.00 €"
    """
    # Remove currency symbols and whitespace
    cleaned = price_text.replace("EUR", "").replace("€", "").strip()

    # Handle "Bis" / "to" price ranges - take the first price
    if " bis " in cleaned.lower():
        cleaned = cleaned.lower().split(" bis ")[0].strip()
    elif " to " in cleaned.lower():
        cleaned = cleaned.lower().split(" to ")[0].strip()

    # German format: 1.500,00 → 1500.00
    # First check if it uses German format (comma as decimal separator)
    if "," in cleaned:
        # Remove thousands separators (dots in German format)
        cleaned = cleaned.replace(".", "")
        # Replace decimal comma with dot
        cleaned = cleaned.replace(",", ".")

    # Extract the numeric value
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None
