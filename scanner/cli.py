"""CLI interface and main orchestrator for the NFT Arbitrage Scanner.

Usage:
    python -m scanner.cli [--count N] [--threshold N] [--verbose] [--output FILE]
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from scanner.arbitrage import scan_for_arbitrage
from scanner.config import (
    COLLECTION_SYMBOL,
    MAX_NFT_COUNT,
    MIN_PROFIT_PERCENT,
    RESULTS_DIR,
    SCAN_INTERVAL_SECONDS,
)
from scanner.currency import get_sol_price_usd, get_usd_to_eur_rate
from scanner.magic_eden import fetch_listings

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner() -> None:
    banner = Text()
    banner.append("NFT Arbitrage Scanner", style="bold cyan")
    banner.append("\n")
    banner.append("Magic Eden (Collector Crypt) -> eBay Germany", style="dim")
    banner.append("\n")
    banner.append("Multi-Signal Matching | Confidence Scoring | Live Prices", style="dim")
    console.print(Panel(banner, border_style="cyan"))


def print_rates() -> None:
    """Display current exchange rates."""
    try:
        sol_usd = get_sol_price_usd()
        usd_eur = get_usd_to_eur_rate()
        sol_eur = sol_usd * usd_eur

        table = Table(title="Live Exchange Rates", show_header=False)
        table.add_row("SOL/USD", f"${sol_usd:.2f}")
        table.add_row("USD/EUR", f"\u20ac{usd_eur:.4f}")
        table.add_row("SOL/EUR", f"\u20ac{sol_eur:.2f}")
        table.add_row("USDC/EUR", f"\u20ac{usd_eur:.4f}")
        console.print(table)
    except Exception as e:
        console.print(f"[red]Error fetching rates: {e}[/red]")
        sys.exit(1)


def print_results(opportunities: list) -> None:
    """Display arbitrage opportunities in a formatted table."""
    if not opportunities:
        console.print("\n[yellow]No arbitrage opportunities found.[/yellow]")
        return

    console.print(
        f"\n[bold green]Found {len(opportunities)} arbitrage opportunities![/bold green]\n"
    )

    table = Table(title="Arbitrage Opportunities", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Card Title", style="white", max_width=50)
    table.add_column("ME Price", style="cyan", justify="right")
    table.add_column("Ins. Val", style="dim cyan", justify="right")
    table.add_column("eBay Avg", style="green", justify="right")
    table.add_column("Profit %", style="bold green", justify="right")
    table.add_column("Matches", justify="center")
    table.add_column("Confidence", justify="center")

    for i, opp in enumerate(opportunities, 1):
        profit_style = "bold green" if opp.profit_percent >= 50 else "green"
        conf_pct = opp.match_confidence * 100
        conf_style = "bold green" if conf_pct >= 90 else "yellow" if conf_pct >= 80 else "red"
        iv_str = f"${opp.nft.insured_value_usd:.0f}" if opp.nft.insured_value_usd > 0 else "-"
        table.add_row(
            str(i),
            opp.nft.title[:50],
            f"\u20ac{opp.nft.price_eur:.2f}",
            iv_str,
            f"\u20ac{opp.ebay_avg_price_eur:.2f}",
            Text(f"+{opp.profit_percent:.1f}%", style=profit_style),
            str(opp.ebay_sold_count),
            Text(f"{conf_pct:.0f}%", style=conf_style),
        )

    console.print(table)

    # Print detailed links and match evidence
    console.print("\n[bold]Detailed Links & Match Evidence:[/bold]")
    for i, opp in enumerate(opportunities, 1):
        console.print(f"\n[cyan]#{i}[/cyan] {opp.nft.title}")
        console.print(f"  Magic Eden: {opp.nft.magic_eden_url}")
        console.print(f"  eBay Search: {opp.ebay_search_url}")
        console.print(f"  Confidence: {opp.match_confidence:.0%}")

        # Show parsed NFT attributes
        attrs = opp.nft.attributes
        console.print(
            f"  NFT Parsed: pokemon={attrs.pokemon_name} variant={attrs.variant} "
            f"number={attrs.card_number} set={attrs.set_name} "
            f"grade={attrs.grading_company.value} {attrs.grade} lang={attrs.language}"
        )

        # Show top match evidence
        if opp.scored_matches:
            best = opp.scored_matches[0]
            console.print(f"  Best eBay match: '{best.ebay_item.title[:60]}'")
            for ev in best.match_result.evidence:
                score_str = f"{ev.score:.1f}"
                console.print(f"    {ev.field_name}: {score_str} | {ev.reason}")


def save_results(opportunities: list, output_path: Path | None = None) -> Path:
    """Save results to JSON file with full match evidence."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        output_path = RESULTS_DIR / f"scan_{timestamp}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "scan_time": timestamp,
        "opportunities_count": len(opportunities),
        "min_profit_threshold": MIN_PROFIT_PERCENT,
        "opportunities": [
            {
                "card_title": opp.nft.title,
                "magic_eden_price_eur": round(opp.nft.price_eur, 2),
                "magic_eden_price_original": opp.nft.price,
                "magic_eden_currency": opp.nft.currency.value,
                "insured_value_usd": opp.nft.insured_value_usd,
                "insured_value_ratio": round(opp.insured_value_ratio, 2),
                "ebay_avg_price_eur": round(opp.ebay_avg_price_eur, 2),
                "ebay_sold_count": opp.ebay_sold_count,
                "profit_percent": round(opp.profit_percent, 1),
                "match_confidence": round(opp.match_confidence, 3),
                "magic_eden_url": opp.nft.magic_eden_url,
                "ebay_search_url": opp.ebay_search_url,
                "nft_attributes": {
                    "pokemon_name": opp.nft.attributes.pokemon_name,
                    "variant": opp.nft.attributes.variant,
                    "card_number": opp.nft.attributes.card_number,
                    "set_name": opp.nft.attributes.set_name,
                    "grading_company": opp.nft.attributes.grading_company.value,
                    "grade": opp.nft.attributes.grade,
                    "language": opp.nft.attributes.language,
                    "foil_type": opp.nft.attributes.foil_type,
                    "edition": opp.nft.attributes.edition,
                },
                "match_evidence": [
                    sm.match_result.to_dict()
                    for sm in opp.scored_matches[:3]  # Top 3 matches
                ],
            }
            for opp in opportunities
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    console.print(f"\n[dim]Results saved to: {output_path}[/dim]")
    return output_path


def run_scan(count: int, threshold: float) -> list:
    """Execute a single scan cycle."""
    # Fetch listings from Magic Eden
    console.print(f"\n[bold]Fetching {count} listings from Magic Eden...[/bold]")
    listings = fetch_listings(symbol=COLLECTION_SYMBOL, max_count=count)

    if not listings:
        console.print("[red]No listings found. Check your connection or API key.[/red]")
        return []

    console.print(f"[green]Fetched {len(listings)} listings.[/green]")

    # Show sample of listings with parsed attributes
    console.print("\n[bold]Sample listings (with parsed attributes):[/bold]")
    for listing in listings[:5]:
        attrs = listing.attributes
        iv_str = f" | IV=${listing.insured_value_usd:.0f}" if listing.insured_value_usd > 0 else ""
        console.print(
            f"  - {listing.title[:60]}\n"
            f"    {listing.price} {listing.currency.value} "
            f"(\u20ac{listing.price_eur:.2f}){iv_str} | "
            f"pokemon={attrs.pokemon_name} variant={attrs.variant} "
            f"num={attrs.card_number} set={attrs.set_name}"
        )
    if len(listings) > 5:
        console.print(f"  ... and {len(listings) - 5} more")

    # Scan for arbitrage
    console.print(
        f"\n[bold]Scanning for arbitrage (threshold: {threshold}%)...[/bold]"
    )
    opportunities = scan_for_arbitrage(listings)

    return opportunities


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NFT Arbitrage Scanner - Magic Eden to eBay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scanner.cli                     # Default scan (250 items, 30% threshold)\n"
            "  python -m scanner.cli --count 50          # Scan 50 items\n"
            "  python -m scanner.cli --threshold 50      # Only show 50%+ profit\n"
            "  python -m scanner.cli --loop              # Continuous scanning\n"
            "  python -m scanner.cli --verbose            # Debug output\n"
        ),
    )
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=MAX_NFT_COUNT,
        help=f"Number of NFTs to scan (default: {MAX_NFT_COUNT})",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=MIN_PROFIT_PERCENT,
        help=f"Minimum profit percentage (default: {MIN_PROFIT_PERCENT}%%)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path for results (JSON)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously with interval between scans",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=SCAN_INTERVAL_SECONDS,
        help=f"Seconds between scans in loop mode (default: {SCAN_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)
    print_banner()
    print_rates()

    output_path = Path(args.output) if args.output else None

    if args.loop:
        console.print(
            f"\n[bold yellow]Continuous mode: scanning every {args.interval}s[/bold yellow]"
        )
        scan_num = 0
        while True:
            scan_num += 1
            console.print(f"\n{'='*60}")
            console.print(
                f"[bold]Scan #{scan_num} at "
                f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}[/bold]"
            )
            console.print(f"{'='*60}")

            opportunities = run_scan(args.count, args.threshold)
            if opportunities:
                print_results(opportunities)
                save_results(opportunities, output_path)

            console.print(
                f"\n[dim]Next scan in {args.interval} seconds...[/dim]"
            )
            time.sleep(args.interval)
    else:
        opportunities = run_scan(args.count, args.threshold)
        print_results(opportunities)
        if opportunities:
            save_results(opportunities, output_path)


if __name__ == "__main__":
    main()
