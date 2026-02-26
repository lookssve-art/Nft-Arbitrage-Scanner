# NFT Arbitrage Scanner

**Magic Eden (Collector Crypt) → eBay Germany | Pokemon Graded Cards**

Scans tokenized Pokemon graded card NFTs on Magic Eden's Collector Crypt collection and compares prices against eBay Germany sold items to find arbitrage opportunities.

## How It Works

1. **Fetches** the latest 250 Pokemon NFT listings from Magic Eden (Collector Crypt collection, sorted by "Recently Listed")
2. **Extracts** exact title, price, and currency (SOL or USDC) for each listing
3. **Converts** prices to EUR using live exchange rates (CoinGecko for SOL, ExchangeRate-API for USD→EUR)
4. **Searches** eBay Germany for each card using the exact title in quotes, filtering by "Sold Items"
5. **Matches** results using strict deterministic rules (same grading company, grade, card number, set, edition, language)
6. **Flags** opportunities where eBay average sold price is ≥30% higher than Magic Eden price

## Strict Matching Rules

Every eBay result must match the NFT listing **1:1** on ALL of the following:

| Field | Example |
|-------|---------|
| Grading Company | PSA, CGC, BGS/Beckett |
| Grade | PSA 10, CGC 9.5, BGS 9 |
| Card Number | 4/102, #025 |
| Set | Base Set, Jungle, Fossil |
| Edition | 1st Edition, Unlimited, Shadowless |
| Language | English, Japanese (if mentioned) |

If **any** field differs → the result is discarded. No fuzzy matching. No AI-based semantic matching.

## Installation

```bash
# Clone the repository
git clone https://github.com/lookssve-art/Nft-Arbitrage-Scanner.git
cd Nft-Arbitrage-Scanner

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

## Usage

```bash
# Default scan (250 items, 30% profit threshold)
python -m scanner.cli

# Scan fewer items for a quick test
python -m scanner.cli --count 50

# Higher profit threshold
python -m scanner.cli --threshold 50

# Continuous scanning mode
python -m scanner.cli --loop --interval 300

# Verbose/debug output
python -m scanner.cli --verbose

# Save results to specific file
python -m scanner.cli --output results/my_scan.json
```

## Output

For each arbitrage opportunity found:
- Card title (exact)
- Magic Eden price in EUR
- eBay average sold price in EUR
- Profit percentage
- Direct link to Magic Eden listing
- Direct link to eBay search

Results are saved as JSON in the `results/` directory.

## Configuration

Edit `.env` or pass CLI flags:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_NFT_COUNT` | 250 | Number of NFTs to scan |
| `MIN_PROFIT_PERCENT` | 30 | Minimum profit % to flag |
| `SCAN_INTERVAL_SECONDS` | 300 | Seconds between scans (loop mode) |
| `MAGIC_EDEN_API_KEY` | (empty) | Optional API key for higher rate limits |
| `EBAY_APP_ID` | (empty) | Optional eBay API credentials |

## Project Structure

```
scanner/
├── __init__.py        # Package init
├── __main__.py        # python -m scanner entry point
├── cli.py             # CLI interface & main orchestrator
├── config.py          # Configuration & environment variables
├── models.py          # Data models (NFTListing, EbaySoldItem, etc.)
├── magic_eden.py      # Magic Eden API scraper
├── ebay.py            # eBay sold items scraper
├── card_parser.py     # Strict card title parser (regex-based)
├── matcher.py         # Strict deterministic matching engine
├── arbitrage.py       # Arbitrage detection logic
└── currency.py        # Live currency conversion (SOL/USDC → EUR)
tests/
├── test_card_parser.py
├── test_matcher.py
└── test_currency.py
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Technical Details

- **No fuzzy matching** — all comparisons are strict, deterministic, regex-based
- **Live exchange rates** — SOL price from CoinGecko, USD→EUR from ExchangeRate-API
- **Rate limiting** — built-in delays to respect API limits
- **Pagination** — correctly pages through Magic Eden API to collect all 250 items
- **Caching** — 2-minute cache on exchange rates to avoid redundant API calls

## License

MIT
