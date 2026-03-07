# CLAUDE.md

## Project Overview

NFT Arbitrage Scanner — a Python application that identifies price arbitrage opportunities for Pokemon graded card NFTs. It compares prices from Magic Eden's "Collector Crypt" collection (Solana) and the Phygitals marketplace against eBay Germany sold items and PriceCharting data to find profitable opportunities (default: 30% minimum profit threshold).

## Quick Reference

```bash
# Install
pip install -e ".[dev]"

# Run scanner
python -m scanner.cli                     # Default: 250 NFTs, 30% threshold
python -m scanner.cli --count 50          # Quick test run
python -m scanner.cli --threshold 50      # Higher profit threshold
python -m scanner.cli --loop              # Continuous scanning
python -m scanner.cli --verbose           # Debug output

# Run agent mode (JSON output for Charizard Agent)
python -m scanner.agent_scan

# Run tests
pytest tests/ -v

# Format & lint
black scanner/ tests/
ruff check scanner/ tests/
```

## Tech Stack

- **Python 3.10+** (tested on 3.11)
- **Build**: setuptools via `pyproject.toml`
- **Dependencies**: requests, beautifulsoup4, lxml, pydantic, rich, python-dotenv, aiohttp
- **Dev tools**: pytest, pytest-asyncio, black, ruff

## Project Structure

```
scanner/                    # Main application package
├── __main__.py            # Entry point (python -m scanner)
├── cli.py                 # CLI interface & main orchestrator
├── config.py              # Environment & API configuration
├── models.py              # Pydantic/dataclass models (NFTListing, CardAttributes, etc.)
├── card_parser.py         # Regex-based card attribute extraction (710 lines)
├── magic_eden.py          # Magic Eden API client
├── phygitals.py           # Phygitals marketplace API client
├── ebay.py                # eBay Germany sold-items scraper
├── pricecharting.py       # PriceCharting.com price lookup
├── matcher.py             # Multi-signal weighted matching engine
├── arbitrage.py           # Arbitrage detection & profit calculation
├── currency.py            # Live currency conversion (SOL→USD→EUR)
└── agent_scan.py          # Charizard Agent integration (German-language)

tests/                     # Test suite
├── test_card_parser.py    # Card parsing tests (60+ cases)
├── test_matcher.py        # Matching algorithm tests (60+ cases)
├── test_currency.py       # Currency conversion tests
└── test_pricecharting.py  # PriceCharting integration tests

results/                   # Scan output (JSON files, gitignored)
```

## Architecture

### Pipeline (3 stages)

1. **Data Acquisition** — Fetch NFT listings from Magic Eden + Phygitals APIs
2. **Price Verification** — Query PriceCharting (primary) or scrape eBay Germany (fallback)
3. **Opportunity Detection** — Multi-signal matching + profit calculation

### Key Design Decisions

- **Deterministic matching only** — No fuzzy matching, no AI-based semantic matching. All comparisons use normalized text + exact numeric matches with regex-based parsing.
- **Weighted scoring** — 6 fields with fixed weights: pokemon_name (0.30), card_number (0.25), variant (0.20), set_name (0.15), language (0.05), edition (0.05).
- **Decision thresholds** — AUTO_MATCH >= 0.85, NEEDS_REVIEW 0.60–0.84, NO_MATCH < 0.60.
- **Gate checks** — Grading company and grade must match exactly. Lots/bundles are auto-disqualified.
- **Two-tier price verification** — PriceCharting is the primary source; eBay scraping is the fallback.

### External APIs

| Service | Purpose | Auth | Rate Limit |
|---------|---------|------|------------|
| Magic Eden | NFT listings (Solana) | Optional API key | 1s delay between requests |
| Phygitals | NFT listings (aggregated vaults) | None | Built-in delays |
| eBay Germany | Sold item prices (web scraping) | None | 2s delay between requests |
| PriceCharting | Aggregated card prices | None | 1s delay per request |
| CoinGecko | SOL/USD price | None | 2-min cache |
| ExchangeRate-API | USD/EUR conversion | Optional key | 2-min cache |

## Configuration

Copy `.env.example` to `.env`. All variables have sensible defaults:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAGIC_EDEN_API_KEY` | (empty) | Optional; uses public endpoints |
| `SCAN_INTERVAL_SECONDS` | 300 | Loop mode scan interval |
| `MIN_PROFIT_PERCENT` | 30 | Minimum profit threshold |
| `MAX_NFT_COUNT` | 250 | NFTs to scan per run |
| `PRICECHARTING_ENABLED` | 1 | Use PriceCharting as primary |
| `PRICECHARTING_MIN_MATCH_SCORE` | 0.35 | Minimum PriceCharting match score |

## Code Conventions

- **Formatter**: black (line length default 88)
- **Linter**: ruff
- **Type hints**: Used throughout (Python 3.10+ style)
- **Naming**: snake_case for functions/variables, PascalCase for classes, UPPERCASE for constants, `_prefix` for internal helpers
- **Logging**: `logging` module with module-level loggers
- **Error handling**: try-except with logging for all external API calls
- **Docstrings**: Present on modules and key functions

## Testing

```bash
pytest tests/ -v                     # All tests
pytest tests/test_card_parser.py     # Card parsing only
pytest tests/test_matcher.py         # Matching only
pytest -k "test_parse" -v            # By pattern
```

Tests are unit tests with no external API calls. Key test areas:
- Card attribute extraction (grading, grades, card numbers, languages, special cases)
- Matching gate checks and scoring thresholds
- Currency conversion logic
- PriceCharting lookup logic

## Output Format

Results are saved to `results/scan_YYYYMMDD_HHMMSS.json` containing:
- Scan metadata (timestamp, count, threshold)
- Per-opportunity: card title, prices (EUR), profit %, match confidence, URLs, parsed attributes, match evidence

## Common Tasks

**Adding a new data source**: Create a new module in `scanner/` following the pattern of `magic_eden.py` or `phygitals.py`. Add the client to the pipeline in `arbitrage.py` and wire it into `cli.py`.

**Modifying matching logic**: Edit `scanner/matcher.py` for scoring weights/thresholds, `scanner/card_parser.py` for parsing patterns. Run `pytest tests/test_matcher.py tests/test_card_parser.py -v` after changes.

**Adding new card attributes**: Update `CardAttributes` in `models.py`, add extraction logic in `card_parser.py`, and add corresponding tests.
