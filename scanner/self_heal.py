"""Self-healing module for the Charizard Agent.

Handles retries, fallbacks, and error logging when APIs or
external services are unavailable. Never modifies scanner code —
only manages execution-level recovery.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scanner.config import RESULTS_DIR

logger = logging.getLogger(__name__)

SELF_HEAL_LOG = RESULTS_DIR / "self_heal_log.txt"
ERROR_LOG = RESULTS_DIR / "error_log.txt"

# Retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAYS = [60, 120, 300]  # seconds: 1min, 2min, 5min


class SelfHealer:
    """Manages retries and fallback strategies for external API calls."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delays: list[int] | None = None,
    ):
        self.max_retries = max_retries
        self.retry_delays = retry_delays or DEFAULT_RETRY_DELAYS

    def retry(
        self,
        func: Callable[[], Any],
        description: str = "API call",
        max_retries: int | None = None,
    ) -> Any:
        """Execute a function with automatic retries on failure.

        Args:
            func: The function to execute (no arguments).
            description: Human-readable description for logging.
            max_retries: Override default max retries.

        Returns:
            The function's return value, or None if all retries failed.
        """
        retries = max_retries or self.max_retries

        for attempt in range(retries + 1):
            try:
                result = func()
                if attempt > 0:
                    self.log_event(
                        "retry_success",
                        f"{description}: Erfolgreich nach {attempt} Versuchen",
                    )
                return result
            except Exception as e:
                if attempt < retries:
                    delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                    self.log_event(
                        "retry",
                        f"{description}: Fehler '{e}' — "
                        f"Warte {delay}s (Versuch {attempt + 1}/{retries})",
                    )
                    time.sleep(delay)
                else:
                    self.log_event(
                        "failed",
                        f"{description}: Endgültig fehlgeschlagen nach "
                        f"{retries} Versuchen. Fehler: {e}",
                    )
                    self.log_error(description, e)
                    return None

    def log_event(self, event_type: str, message: str) -> None:
        """Log a self-healing event to the log file."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_line = f"[{timestamp}] [{event_type.upper()}] {message}\n"

        logger.info("[SelfHeal] %s: %s", event_type, message)

        SELF_HEAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SELF_HEAL_LOG, "a", encoding="utf-8") as f:
            f.write(log_line)

    def log_error(self, context: str, error: Exception) -> None:
        """Log an error to the error log file."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_entry = {
            "timestamp": timestamp,
            "context": context,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    @staticmethod
    def get_last_known_rates() -> dict | None:
        """Try to recover exchange rates from the most recent scan result.

        Used as fallback when CoinGecko or ExchangeRate-API are down.
        """
        results_dir = RESULTS_DIR
        scan_files = sorted(results_dir.glob("scan_*.json"), reverse=True)

        for path in scan_files[:5]:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if "sol_usd" in data and "usd_eur" in data:
                    return {
                        "sol_usd": data["sol_usd"],
                        "usd_eur": data["usd_eur"],
                        "source": str(path.name),
                    }
            except (json.JSONDecodeError, KeyError):
                continue

        return None
