"""Charizard Agent Scanner — standalone scan script.

Runs the NFT Arbitrage Scanner and outputs structured JSON results
with separate Top-10 lists per platform (Magic Eden / Phygitals),
ready for the Charizard Agent to format and post to Discord.

Usage:
    python -m scanner.agent_scan              # Default: 250 NFTs, 20% threshold
    python -m scanner.agent_scan --count 100  # Scan 100 NFTs
    python -m scanner.agent_scan --threshold 30  # Only 30%+ profit
    python -m scanner.agent_scan --discord     # Also send to Discord
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from scanner.arbitrage import scan_for_arbitrage
from scanner.config import COLLECTION_SYMBOL, MAX_NFT_COUNT
from scanner.currency import get_sol_price_usd, get_usd_to_eur_rate
from scanner.discord_notify import send_discord_report
from scanner.magic_eden import fetch_listings
from scanner.phygitals import fetch_phygitals_listings
from scanner.self_heal import SelfHealer

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def _build_entry(rank: int, opp) -> dict:
    """Build a single opportunity entry for JSON output."""
    entry = {
        "rang": rank,
        "karte": opp.nft.title,
        "buy_preis_eur": round(opp.nft.price_eur, 2),
        "buy_preis_sol": round(opp.nft.price, 4),
        "sell_preis_eur": round(opp.ebay_avg_price_eur, 2),
        "profit_prozent": round(opp.profit_percent, 1),
        "versicherungswert_usd": round(opp.nft.insured_value_usd, 0),
        "match_konfidenz": round(opp.match_confidence * 100, 0),
        "ebay_verkauft": opp.ebay_sold_count,
        "buy_plattform": opp.nft.source,
        "sell_plattform": "eBay.de / PriceCharting",
        "magic_eden_link": opp.nft.magic_eden_url,
        "ebay_suche_link": opp.ebay_search_url,
    }
    if opp.pc_matched_price_usd > 0:
        entry["pricecharting_preis_usd"] = round(opp.pc_matched_price_usd, 2)
        entry["pricecharting_produkt"] = opp.pc_product_name
        entry["pricecharting_link"] = opp.pc_url
    return entry


def run_agent_scan(count: int = MAX_NFT_COUNT, threshold: float = 20.0) -> dict:
    """Run the scanner and return structured results with per-platform Top 10."""
    scan_time = datetime.now(timezone.utc)
    healer = SelfHealer()

    # Get rates
    sol_usd = healer.retry(get_sol_price_usd, description="SOL/USD Kurs")
    usd_eur = healer.retry(get_usd_to_eur_rate, description="USD/EUR Kurs")

    if sol_usd is None or usd_eur is None:
        msg = "Wechselkurse nicht abrufbar."
        healer.log_event("rates_failed", msg)
        return {
            "status": "error",
            "message": msg,
            "timestamp": scan_time.isoformat(),
        }

    # Fetch listings from both sources (with self-healing)
    cc_listings = healer.retry(
        lambda: fetch_listings(symbol=COLLECTION_SYMBOL, max_count=count),
        description="Magic Eden Listings",
    )
    pg_listings = healer.retry(
        lambda: fetch_phygitals_listings(max_count=count),
        description="Phygitals Listings",
    )

    cc_available = bool(cc_listings)
    pg_available = bool(pg_listings)
    cc_listings = cc_listings or []
    pg_listings = pg_listings or []

    all_listings = cc_listings + pg_listings

    if not all_listings:
        msg = "Keine Listings gefunden (beide Plattformen nicht erreichbar)."
        healer.log_event("no_listings", msg)
        return {
            "status": "error",
            "message": msg,
            "timestamp": scan_time.isoformat(),
            "magic_eden_erreichbar": cc_available,
            "phygitals_erreichbar": pg_available,
        }

    # Scan for arbitrage
    opportunities = scan_for_arbitrage(all_listings)

    # Filter by threshold
    filtered = [o for o in opportunities if o.profit_percent >= threshold]

    # Split by platform
    me_opps = [o for o in filtered if o.nft.source == "collector_crypt"]
    pg_opps = [o for o in filtered if o.nft.source != "collector_crypt"]

    # Build Top 10 per platform
    me_top10 = [_build_entry(i, o) for i, o in enumerate(me_opps[:10], 1)]
    pg_top10 = [_build_entry(i, o) for i, o in enumerate(pg_opps[:10], 1)]

    # Warnings for partial results
    warnungen = []
    if not cc_available:
        warnungen.append("Magic Eden nicht erreichbar — nur Phygitals-Ergebnisse")
    if not pg_available:
        warnungen.append("Phygitals nicht erreichbar — nur Magic Eden-Ergebnisse")

    return {
        "status": "ok",
        "timestamp": scan_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "sol_usd": round(sol_usd, 2),
        "usd_eur": round(usd_eur, 4),
        "gescannte_listings": len(all_listings),
        "magic_eden_listings": len(cc_listings),
        "phygitals_listings": len(pg_listings),
        "gefundene_opportunities": len(filtered),
        "warnungen": warnungen,
        "top_10_magic_eden": me_top10,
        "top_10_phygitals": pg_top10,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Charizard Agent Scanner")
    parser.add_argument("--count", "-c", type=int, default=MAX_NFT_COUNT)
    parser.add_argument("--threshold", "-t", type=float, default=20.0)
    parser.add_argument(
        "--discord", "-d", action="store_true",
        help="Send results to Discord #research channel",
    )
    args = parser.parse_args()

    result = run_agent_scan(count=args.count, threshold=args.threshold)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.discord and result.get("status") == "ok":
        send_discord_report(result)
    elif args.discord and result.get("status") == "error":
        send_discord_report(result)


if __name__ == "__main__":
    main()
