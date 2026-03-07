"""Scheduled runner for the Charizard Agent.

Runs the NFT Arbitrage Scanner daily at 08:00 UTC and sends
results to the Discord #research channel.

Usage:
    python -m scanner.scheduler              # Start the scheduler
    python -m scanner.scheduler --time 09:00 # Custom scan time
    python -m scanner.scheduler --once       # Run once immediately, then exit

Can also be triggered via cron:
    0 8 * * * cd /home/user/Nft-Arbitrage-Scanner && python -m scanner.scheduler --once
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone

import schedule

from scanner.agent_scan import run_agent_scan
from scanner.discord_notify import retry_pending, send_discord_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_SCAN_TIME = "08:00"
DEFAULT_COUNT = 250
DEFAULT_THRESHOLD = 20.0


def run_scheduled_scan(count: int = DEFAULT_COUNT, threshold: float = DEFAULT_THRESHOLD) -> None:
    """Execute a scan and send results to Discord."""
    logger.info("Starte geplanten Scan...")

    # First, retry any pending Discord messages from previous failures
    pending_sent = retry_pending()
    if pending_sent > 0:
        logger.info("%d ausstehende Discord-Nachrichten nachgesendet.", pending_sent)

    # Run the scan
    result = run_agent_scan(count=count, threshold=threshold)

    # Send to Discord
    send_discord_report(result)

    if result.get("status") == "ok":
        me_count = len(result.get("top_10_magic_eden", []))
        pg_count = len(result.get("top_10_phygitals", []))
        logger.info(
            "Scan abgeschlossen. ME: %d | PG: %d Opportunities.",
            me_count, pg_count,
        )
    else:
        logger.warning("Scan mit Fehler: %s", result.get("message", "Unbekannt"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Charizard Agent Scheduler")
    parser.add_argument(
        "--time", type=str, default=DEFAULT_SCAN_TIME,
        help=f"Tägliche Scan-Zeit in UTC (default: {DEFAULT_SCAN_TIME})",
    )
    parser.add_argument(
        "--count", "-c", type=int, default=DEFAULT_COUNT,
        help=f"Anzahl Listings pro Scan (default: {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--threshold", "-t", type=float, default=DEFAULT_THRESHOLD,
        help=f"Minimaler Profit %% (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Einmal sofort ausführen und beenden",
    )
    args = parser.parse_args()

    if args.once:
        logger.info("Einmaliger Scan-Modus.")
        run_scheduled_scan(count=args.count, threshold=args.threshold)
        return

    # Schedule daily scan
    schedule.every().day.at(args.time).do(
        run_scheduled_scan,
        count=args.count,
        threshold=args.threshold,
    )

    logger.info(
        "Charizard Agent Scheduler gestartet. Täglicher Scan um %s UTC.",
        args.time,
    )

    # Graceful shutdown
    def handle_signal(signum, frame):
        logger.info("Scheduler wird beendet...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Run the scheduler loop
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
