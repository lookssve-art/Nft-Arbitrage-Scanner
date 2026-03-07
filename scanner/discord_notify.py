"""Discord webhook integration for the Charizard Agent.

Sends formatted scan results to the #research Discord channel
via webhook URL configured in DISCORD_WEBHOOK_URL env variable.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from scanner.config import RESULTS_DIR

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
MAX_DISCORD_MESSAGE_LENGTH = 2000


def _format_opportunity(entry: dict) -> str:
    """Format a single opportunity for Discord."""
    sell_info = f"\u20ac{entry['sell_preis_eur']:.2f}"
    if entry.get("pricecharting_preis_usd"):
        sell_info += f" (PC: ${entry['pricecharting_preis_usd']:.2f})"

    return (
        f"**#{entry['rang']}** — {entry['karte']}\n"
        f"   Buy: \u20ac{entry['buy_preis_eur']:.2f} ({entry['buy_preis_sol']} SOL)\n"
        f"   Sell: {sell_info}\n"
        f"   Profit: **+{entry['profit_prozent']}%** | "
        f"Konfidenz: {entry['match_konfidenz']:.0f}%\n"
        f"   \U0001f517 {entry['magic_eden_link']}\n"
    )


def _build_discord_message(result: dict) -> str:
    """Build the full Discord message from scan results."""
    if result.get("status") == "error":
        return (
            f"\U0001f525 **CHARIZARD SCAN** — {result.get('timestamp', 'N/A')}\n"
            f"\u26a0\ufe0f {result.get('message', 'Scan fehlgeschlagen')}\n"
        )

    lines = [
        f"\U0001f525 **CHARIZARD SCAN** — {result['timestamp']}\n",
        f"\U0001f4b0 SOL: ${result['sol_usd']} | EUR/USD: {result['usd_eur']}",
        f"Gescannt: {result['gescannte_listings']} Listings gesamt "
        f"(ME: {result['magic_eden_listings']} | PG: {result['phygitals_listings']})\n",
    ]

    # Warnings
    for w in result.get("warnungen", []):
        lines.append(f"\u26a0\ufe0f {w}")

    # Magic Eden Top 10
    lines.append("\u2501" * 35)
    lines.append("\U0001f4cc **TOP 10 — MAGIC EDEN (Collector Crypt)**")
    lines.append("\u2501" * 35 + "\n")

    me_top = result.get("top_10_magic_eden", [])
    if me_top:
        for entry in me_top:
            lines.append(_format_opportunity(entry))
    else:
        lines.append("Keine profitablen M\u00f6glichkeiten gefunden.\n")

    # Phygitals Top 10
    lines.append("\u2501" * 35)
    lines.append("\U0001f4cc **TOP 10 — PHYGITALS**")
    lines.append("\u2501" * 35 + "\n")

    pg_top = result.get("top_10_phygitals", [])
    if pg_top:
        for entry in pg_top:
            lines.append(_format_opportunity(entry))
    else:
        lines.append("Keine profitablen M\u00f6glichkeiten gefunden.\n")

    return "\n".join(lines)


def _split_message(message: str) -> list[str]:
    """Split a long message into chunks that fit Discord's limit."""
    if len(message) <= MAX_DISCORD_MESSAGE_LENGTH:
        return [message]

    chunks = []
    current = ""
    for line in message.split("\n"):
        if len(current) + len(line) + 1 > MAX_DISCORD_MESSAGE_LENGTH:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


def send_discord_report(result: dict) -> bool:
    """Send scan results to Discord #research channel via webhook.

    Returns True if sent successfully, False otherwise.
    If webhook URL is not configured, saves result to file for later retry.
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning(
            "DISCORD_WEBHOOK_URL nicht gesetzt. "
            "Ergebnisse werden in results/ gespeichert."
        )
        _save_pending(result)
        return False

    message = _build_discord_message(result)
    chunks = _split_message(message)

    try:
        for chunk in chunks:
            response = requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": chunk},
                timeout=10,
            )
            response.raise_for_status()

        logger.info("Discord-Nachricht erfolgreich gesendet.")
        return True

    except requests.RequestException as e:
        logger.error("Discord-Webhook fehlgeschlagen: %s", e)
        _save_pending(result)
        return False


def _save_pending(result: dict) -> None:
    """Save result for later retry when Discord is unavailable."""
    pending_dir = RESULTS_DIR / "pending_discord"
    pending_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = pending_dir / f"pending_{timestamp}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info("Ergebnis gespeichert f\u00fcr sp\u00e4teren Versand: %s", path)


def retry_pending() -> int:
    """Retry sending any pending Discord messages.

    Returns number of successfully sent messages.
    """
    pending_dir = RESULTS_DIR / "pending_discord"
    if not pending_dir.exists():
        return 0

    sent = 0
    for path in sorted(pending_dir.glob("pending_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                result = json.load(f)
            if send_discord_report(result):
                path.unlink()
                sent += 1
        except Exception as e:
            logger.error("Fehler beim erneuten Senden von %s: %s", path, e)

    return sent
