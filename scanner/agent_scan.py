"""Charizard Agent Scanner — standalone scan script.

Runs the NFT Arbitrage Scanner and outputs structured JSON results
ready for the Charizard Agent to report.

Usage:
    python -m scanner.agent_scan              # Default: 250 NFTs, 20% threshold
    python -m scanner.agent_scan --count 100  # Scan 100 NFTs
    python -m scanner.agent_scan --threshold 30  # Only 30%+ profit
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from scanner.arbitrage import scan_for_arbitrage
from scanner.config import COLLECTION_SYMBOL, MAX_NFT_COUNT
from scanner.currency import get_sol_price_usd, get_usd_to_eur_rate
from scanner.magic_eden import fetch_listings

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def run_agent_scan(count: int = MAX_NFT_COUNT, threshold: float = 20.0) -> dict:
    """Run the scanner and return structured results for the agent."""
    scan_time = datetime.now(timezone.utc)

    # Get rates
    sol_usd = get_sol_price_usd()
    usd_eur = get_usd_to_eur_rate()

    # Fetch listings
    listings = fetch_listings(symbol=COLLECTION_SYMBOL, max_count=count)
    if not listings:
        return {
            "status": "error",
            "message": "Keine Listings gefunden.",
            "timestamp": scan_time.isoformat(),
        }

    # Scan for arbitrage
    opportunities = scan_for_arbitrage(listings)

    # Filter by threshold
    filtered = [o for o in opportunities if o.profit_percent >= threshold]

    # Build top 10 results
    top10 = filtered[:10]

    results = []
    for i, opp in enumerate(top10, 1):
        results.append({
            "rang": i,
            "karte": opp.nft.title,
            "buy_preis_eur": round(opp.nft.price_eur, 2),
            "buy_preis_sol": round(opp.nft.price, 4),
            "sell_preis_eur": round(opp.ebay_avg_price_eur, 2),
            "profit_prozent": round(opp.profit_percent, 1),
            "versicherungswert_usd": round(opp.nft.insured_value_usd, 0),
            "match_konfidenz": round(opp.match_confidence * 100, 0),
            "ebay_verkauft": opp.ebay_sold_count,
            "buy_plattform": "Magic Eden (Collector Crypt)",
            "sell_plattform": "eBay.de",
            "magic_eden_link": opp.nft.magic_eden_url,
            "ebay_suche_link": opp.ebay_search_url,
        })

    return {
        "status": "ok",
        "timestamp": scan_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "sol_usd": round(sol_usd, 2),
        "usd_eur": round(usd_eur, 4),
        "gescannte_listings": len(listings),
        "gefundene_opportunities": len(filtered),
        "top_10": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Charizard Agent Scanner")
    parser.add_argument("--count", "-c", type=int, default=MAX_NFT_COUNT)
    parser.add_argument("--threshold", "-t", type=float, default=20.0)
    args = parser.parse_args()

    result = run_agent_scan(count=args.count, threshold=args.threshold)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
