"""Configuration for the NFT Arbitrage Scanner."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# --- Magic Eden ---
MAGIC_EDEN_API_BASE = "https://api-mainnet.magiceden.dev/v2"
MAGIC_EDEN_API_KEY = os.getenv("MAGIC_EDEN_API_KEY", "")
# Collector Crypt collection on Magic Eden (Solana)
COLLECTION_SYMBOL = "collector_crypt"
# Magic Eden marketplace URL for direct links
MAGIC_EDEN_MARKETPLACE_URL = "https://magiceden.us/marketplace/{symbol}"

# --- Scraping ---
MAX_NFT_COUNT = int(os.getenv("MAX_NFT_COUNT", "250"))
# Magic Eden API returns max 20 per page
MAGIC_EDEN_PAGE_SIZE = 20

# --- eBay ---
EBAY_SEARCH_URL = "https://www.ebay.de/sch/i.html"
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID", "")
# Minimum confirmed matches needed for a reliable price average
EBAY_SOLD_SAMPLE_MIN = 2
# Maximum eBay results to fetch per search
EBAY_SOLD_SAMPLE_MAX = 10

# --- Currency ---
EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY", "")
# CoinGecko free API for SOL price
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
# ExchangeRate-API for USD->EUR
EXCHANGERATE_API_URL = "https://open.er-api.com/v6/latest/USD"

# --- PriceCharting ---
PRICECHARTING_ENABLED = os.getenv("PRICECHARTING_ENABLED", "1") == "1"
PRICECHARTING_MIN_MATCH_SCORE = float(os.getenv("PRICECHARTING_MIN_MATCH_SCORE", "0.35"))

# --- Arbitrage ---
MIN_PROFIT_PERCENT = float(os.getenv("MIN_PROFIT_PERCENT", "30"))
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

# --- Request headers ---
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Rate limiting: pause between requests (seconds)
REQUEST_DELAY = 1.0
EBAY_REQUEST_DELAY = 2.0
