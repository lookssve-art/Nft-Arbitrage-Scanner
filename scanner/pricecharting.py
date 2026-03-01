"""PriceCharting.com price lookup for Pokemon cards.

Uses PriceCharting's free JSON search API to get market prices based on
actual eBay sold data. Returns grade-specific prices (Ungraded, PSA 9, PSA 10).

Search endpoint: /search-products?q=QUERY&type=prices&format=json
No authentication required. Rate limit: 1 request per second.

Price field mapping (from search JSON):
- price1 = Ungraded market price (USD)
- price2 = PSA 10 market price (USD)
- price3 = Grade 9 market price (USD)
"""

import logging
import re
import time

import requests

from scanner.card_parser import parse_card_title
from scanner.config import DEFAULT_HEADERS, REQUEST_DELAY
from scanner.models import CardAttributes, GradingCompany, NFTListing

logger = logging.getLogger(__name__)

PRICECHARTING_SEARCH_URL = "https://www.pricecharting.com/search-products"


def _parse_usd_price(price_str: str) -> float:
    """Parse a USD price string like '$5.01' or '$1,250.00' into float."""
    if not price_str:
        return 0.0
    cleaned = price_str.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _build_search_query(nft: NFTListing) -> str:
    """Build a PriceCharting search query from NFT attributes.

    PriceCharting search works best with: pokemon_name + variant + card_number + set_name
    Grading is NOT included because PriceCharting products are card-level
    (prices for each grade are shown on the product page).
    """
    attrs = nft.attributes
    parts: list[str] = []

    # Pokemon name
    if attrs.pokemon_name:
        parts.append(attrs.pokemon_name)

    # Variant (V, Vmax, GX, EX, etc.)
    if attrs.variant:
        parts.append(attrs.variant)

    # Card number (important for disambiguation)
    if attrs.card_number:
        num = attrs.card_number.replace("#", "").strip()
        if num:
            parts.append(num)

    # Set name
    if attrs.set_name and len(attrs.set_name) > 3:
        parts.append(attrs.set_name)

    # Language for Japanese cards
    if attrs.language and attrs.language.lower() == "japanese":
        parts.append("Japanese")

    # Deduplicate (case-insensitive)
    seen: set[str] = set()
    unique_parts: list[str] = []
    for p in parts:
        p_lower = p.lower()
        if p_lower not in seen:
            seen.add(p_lower)
            unique_parts.append(p)

    query = " ".join(unique_parts)

    # Fallback: use cleaned title
    if len(unique_parts) < 2:
        # Strip grading info and year from title for a cleaner search
        fallback = re.sub(
            r"\b(PSA|CGC|BGS|SGC)\s+\d{1,2}(?:\.\d)?\b", "", nft.title, flags=re.IGNORECASE
        )
        fallback = re.sub(r"\b(19|20)\d{2}\b", "", fallback)
        fallback = fallback.strip()[:80]
        query = fallback

    logger.debug("PriceCharting query for '%s': '%s'", nft.title[:50], query)
    return query


def search_pricecharting(query: str) -> list[dict]:
    """Search PriceCharting for Pokemon cards matching the query.

    Returns list of product dicts with keys:
    - productName, consoleName (set), id
    - price1 (ungraded USD), price2 (PSA 10 USD), price3 (Grade 9 USD)
    """
    params = {
        "q": query,
        "type": "prices",
        "format": "json",
    }

    try:
        resp = requests.get(
            PRICECHARTING_SEARCH_URL,
            params=params,
            headers={
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Accept": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError:
        if resp.status_code == 429:
            logger.warning("PriceCharting rate limited. Waiting 3 seconds...")
            time.sleep(3)
            try:
                resp = requests.get(
                    PRICECHARTING_SEARCH_URL,
                    params=params,
                    headers={
                        "User-Agent": DEFAULT_HEADERS["User-Agent"],
                        "Accept": "application/json",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.error("PriceCharting retry failed for query: %s", query)
                return []
        else:
            logger.error("PriceCharting HTTP %d for query: %s", resp.status_code, query)
            return []
    except Exception as e:
        logger.error("PriceCharting request error: %s", e)
        return []

    products = data.get("products", [])
    # Filter to Pokemon cards only
    products = [p for p in products if p.get("category") == "pokemon-cards"]

    logger.debug("PriceCharting returned %d Pokemon products for '%s'", len(products), query)
    return products


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_score(nft: NFTListing, product: dict) -> float:
    """Score how well a PriceCharting product matches an NFT.

    Returns 0.0–1.0 based on matching pokemon name, card number, variant, set.
    """
    attrs = nft.attributes
    product_name = product.get("productName", "")
    set_name = product.get("consoleName", "")
    product_name_norm = _normalize_for_match(product_name)
    set_name_norm = _normalize_for_match(set_name)

    score = 0.0
    checks = 0

    # Pokemon name match (weight: 0.35)
    if attrs.pokemon_name:
        pokemon_norm = _normalize_for_match(attrs.pokemon_name)
        if pokemon_norm in product_name_norm:
            score += 0.35
        checks += 1

    # Card number match (weight: 0.25)
    if attrs.card_number:
        num = attrs.card_number.replace("#", "").strip()
        num_norm = _normalize_for_match(num)
        # Check if the number appears in the product name (e.g., "#125" in "Charizard ex #125")
        if num_norm and num_norm in product_name_norm:
            score += 0.25
        checks += 1

    # Variant match (weight: 0.20)
    if attrs.variant:
        variant_norm = _normalize_for_match(attrs.variant)
        if variant_norm in product_name_norm:
            score += 0.20
        checks += 1

    # Set name match (weight: 0.20)
    if attrs.set_name:
        set_norm = _normalize_for_match(attrs.set_name)
        if set_norm in set_name_norm or set_norm in product_name_norm:
            score += 0.20
        checks += 1

    # If we had very few attributes to match on, reduce confidence
    if checks <= 1:
        score *= 0.5

    return score


def _grade_price_usd(product: dict, grade: float | None, company: GradingCompany) -> float:
    """Get the appropriate price for the NFT's grade from a PriceCharting product.

    Mapping:
    - PSA 10, CGC 10: price2 (PSA 10 market price)
    - PSA 9, CGC 9, BGS 9, Grade 9–9.5: price3 (Grade 9 market price)
    - CGC 9.5: average of price2 and price3
    - Ungraded or unknown: price1 (ungraded market price)
    """
    p1 = _parse_usd_price(product.get("price1", ""))  # Ungraded
    p2 = _parse_usd_price(product.get("price2", ""))  # PSA 10
    p3 = _parse_usd_price(product.get("price3", ""))  # Grade 9

    if grade is None or company == GradingCompany.UNKNOWN:
        return p1  # Ungraded

    if grade >= 10:
        return p2 if p2 > 0 else p3  # PSA 10 / CGC 10
    elif grade >= 9.5:
        # CGC 9.5 / BGS 9.5: between PSA 10 and Grade 9
        if p2 > 0 and p3 > 0:
            return (p2 + p3) / 2
        return p2 if p2 > 0 else p3
    elif grade >= 9:
        return p3 if p3 > 0 else 0.0  # Grade 9
    elif grade >= 8:
        # Grade 8: roughly between ungraded and grade 9
        if p1 > 0 and p3 > 0:
            return (p1 + p3) / 2
        return p3 if p3 > 0 else p1
    else:
        # Grade 7 or below: close to ungraded
        return p1


def lookup_nft_price(nft: NFTListing) -> dict | None:
    """Look up PriceCharting market price for an NFT.

    Searches PriceCharting, finds the best matching product, and returns
    grade-appropriate pricing.

    Returns dict with:
    - product_name: Matched product name
    - set_name: Set/console name
    - product_id: PriceCharting product ID
    - url: Product page URL
    - ungraded_usd: Ungraded market price
    - psa10_usd: PSA 10 market price
    - grade9_usd: Grade 9 market price
    - matched_price_usd: Price for this NFT's specific grade
    - match_score: How well the product matched (0–1)
    """
    query = _build_search_query(nft)
    if not query.strip():
        return None

    products = search_pricecharting(query)
    if not products:
        return None

    # Score each product and pick the best match
    best_product = None
    best_score = 0.0

    for product in products[:10]:  # Check top 10 results
        score = _match_score(nft, product)
        if score > best_score:
            best_score = score
            best_product = product

    if best_product is None or best_score < 0.30:
        logger.debug(
            "No confident PriceCharting match for '%s' (best score: %.2f)",
            nft.title[:50], best_score,
        )
        return None

    # Get grade-specific price
    matched_price = _grade_price_usd(
        best_product, nft.attributes.grade, nft.attributes.grading_company
    )

    p1 = _parse_usd_price(best_product.get("price1", ""))
    p2 = _parse_usd_price(best_product.get("price2", ""))
    p3 = _parse_usd_price(best_product.get("price3", ""))

    # Build product URL
    set_slug = best_product.get("consoleName", "").lower().replace(" ", "-")
    name_slug = best_product.get("productName", "").lower()
    name_slug = re.sub(r"[^a-z0-9\s#-]", "", name_slug)
    name_slug = name_slug.replace("#", "").replace(" ", "-").strip("-")
    product_url = f"https://www.pricecharting.com/game/{set_slug}/{name_slug}"

    result = {
        "product_name": best_product.get("productName", ""),
        "set_name": best_product.get("consoleName", ""),
        "product_id": best_product.get("id", ""),
        "url": product_url,
        "ungraded_usd": round(p1, 2),
        "psa10_usd": round(p2, 2),
        "grade9_usd": round(p3, 2),
        "matched_price_usd": round(matched_price, 2),
        "match_score": round(best_score, 3),
    }

    logger.info(
        "PriceCharting match: '%s' -> '%s' (%s) score=%.2f grade_price=$%.2f",
        nft.title[:40],
        result["product_name"],
        result["set_name"],
        best_score,
        matched_price,
    )

    return result


def batch_lookup_prices(
    nfts: list[NFTListing],
    delay: float = REQUEST_DELAY,
) -> dict[str, dict]:
    """Look up PriceCharting prices for a batch of NFTs.

    Args:
        nfts: List of NFT listings.
        delay: Delay between requests (default 1.0s for rate limiting).

    Returns:
        Dict mapping mint_address (or title hash) to price result dict.
    """
    results: dict[str, dict] = {}

    for i, nft in enumerate(nfts):
        key = nft.mint_address or str(hash(nft.title))
        result = lookup_nft_price(nft)
        if result:
            results[key] = result

        if i < len(nfts) - 1:
            time.sleep(delay)

    logger.info(
        "PriceCharting batch: %d/%d NFTs matched",
        len(results), len(nfts),
    )
    return results
