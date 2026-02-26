"""Live currency conversion: SOL→EUR, USDC→EUR.

All conversions use real-time data. Nothing is hardcoded.
- SOL price via CoinGecko free API
- USD→EUR rate via ExchangeRate-API (open/free tier)
"""

import logging
import time

import requests

from scanner.config import (
    COINGECKO_API_URL,
    DEFAULT_HEADERS,
    EXCHANGERATE_API_URL,
)

logger = logging.getLogger(__name__)

# Simple in-memory cache with TTL (seconds)
_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 120  # 2 minutes


def _get_cached(key: str) -> float | None:
    if key in _cache:
        value, ts = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return value
    return None


def _set_cached(key: str, value: float) -> None:
    _cache[key] = (value, time.time())


def get_sol_price_usd() -> float:
    """Fetch current SOL price in USD from CoinGecko."""
    cached = _get_cached("sol_usd")
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            COINGECKO_API_URL,
            params={"ids": "solana", "vs_currencies": "usd"},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["solana"]["usd"])
        _set_cached("sol_usd", price)
        logger.info("SOL price: $%.2f", price)
        return price
    except Exception as e:
        logger.error("Failed to fetch SOL price: %s", e)
        raise RuntimeError(f"Cannot fetch SOL price: {e}") from e


def get_usd_to_eur_rate() -> float:
    """Fetch current USD→EUR exchange rate."""
    cached = _get_cached("usd_eur")
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            EXCHANGERATE_API_URL,
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["rates"]["EUR"])
        _set_cached("usd_eur", rate)
        logger.info("USD→EUR rate: %.4f", rate)
        return rate
    except Exception as e:
        logger.error("Failed to fetch USD→EUR rate: %s", e)
        raise RuntimeError(f"Cannot fetch USD→EUR rate: {e}") from e


def sol_to_eur(sol_amount: float) -> float:
    """Convert SOL amount to EUR using live rates."""
    sol_usd = get_sol_price_usd()
    usd_eur = get_usd_to_eur_rate()
    return sol_amount * sol_usd * usd_eur


def usdc_to_eur(usdc_amount: float) -> float:
    """Convert USDC amount to EUR. USDC = 1 USD."""
    usd_eur = get_usd_to_eur_rate()
    return usdc_amount * usd_eur


def convert_to_eur(amount: float, currency_str: str) -> float:
    """Convert any supported currency to EUR."""
    currency_upper = currency_str.upper().strip()
    if currency_upper == "SOL":
        return sol_to_eur(amount)
    elif currency_upper in ("USDC", "USD"):
        return usdc_to_eur(amount)
    else:
        raise ValueError(f"Unsupported currency: {currency_str}")
