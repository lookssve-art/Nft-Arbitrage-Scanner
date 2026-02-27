"""Data models for the NFT Arbitrage Scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Currency(Enum):
    SOL = "SOL"
    USDC = "USDC"


class GradingCompany(Enum):
    PSA = "PSA"
    CGC = "CGC"
    BGS = "BGS"  # Beckett Grading Services
    BECKETT = "BGS"  # Alias
    SGC = "SGC"
    UNKNOWN = "UNKNOWN"


class MatchDecision(Enum):
    AUTO_MATCH = "auto_match"       # Confidence >= 0.85
    NEEDS_REVIEW = "needs_review"   # Confidence 0.60–0.84
    NO_MATCH = "no_match"           # Confidence < 0.60 or disqualified


@dataclass
class CardAttributes:
    """Parsed attributes of a graded Pokemon card."""

    grading_company: GradingCompany = GradingCompany.UNKNOWN
    grade: float | None = None          # e.g. 10, 9.5, 9
    card_number: str = ""               # e.g. "170", "SV60", "4/102"
    set_name: str = ""                  # e.g. "Chilling Reign", "Hidden Fates"
    edition: str = ""                   # e.g. "1st Edition", "Unlimited"
    language: str = ""                  # e.g. "English", "Japanese"
    pokemon_name: str = ""              # e.g. "Charizard", "Galarian Articuno"
    variant: str = ""                   # e.g. "V", "Vmax", "Vstar", "GX", "EX", "ex"
    foil_type: str = ""                 # e.g. "Full Art", "Reverse Holo", "Holo"
    year: str = ""                      # e.g. "2021", "1999"
    sub_grade: str = ""                 # e.g. "Pristine", "Gem Mint"
    is_lot: bool = False                # True if listing contains multiple cards

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower().replace("-", " ").replace("_", " ")

    @staticmethod
    def _normalize_card_number(num: str) -> str:
        """Normalize card number for comparison.

        - Remove '#' prefix, spaces
        - Take main number (before '/' set total)
        - Strip leading zeros from numeric parts
        - Preserve letter prefixes (sv, tg, gg)
        """
        import re
        n = num.strip().lower().replace("#", "").replace(" ", "")
        # Take the main number before /
        main = n.split("/")[0]
        # Pure numeric: strip leading zeros
        if main.isdigit():
            main = str(int(main))
        else:
            # Prefixed: "sv60", "tg03", "gg10" → strip zeros from numeric suffix
            m = re.match(r"([a-z]+)0*(\d+)", main)
            if m:
                main = m.group(1) + str(int(m.group(2)))
        return main


@dataclass
class MatchEvidence:
    """Per-field match evidence for debugging and transparency."""

    field_name: str
    nft_value: str
    ebay_value: str
    score: float        # 0.0 to 1.0 for this field
    weight: float       # Weight applied to this field
    reason: str         # Human-readable explanation

    def to_dict(self) -> dict:
        return {
            "field": self.field_name,
            "nft": self.nft_value,
            "ebay": self.ebay_value,
            "score": round(self.score, 3),
            "weight": self.weight,
            "reason": self.reason,
        }


@dataclass
class MatchResult:
    """Result of matching an NFT to an eBay listing."""

    nft_title: str
    ebay_title: str
    total_score: float          # 0.0 to 1.0
    decision: MatchDecision
    evidence: list[MatchEvidence] = field(default_factory=list)
    disqualified: bool = False
    disqualification_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "nft_title": self.nft_title,
            "ebay_title": self.ebay_title,
            "total_score": round(self.total_score, 3),
            "decision": self.decision.value,
            "disqualified": self.disqualified,
            "disqualification_reason": self.disqualification_reason,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class NFTListing:
    """A single NFT listing from Magic Eden."""

    title: str  # EXACT full title, never modified
    price: float
    currency: Currency
    price_eur: float = 0.0
    mint_address: str = ""
    magic_eden_url: str = ""
    attributes: CardAttributes = field(default_factory=CardAttributes)
    raw_me_attributes: list[dict] = field(default_factory=list)


@dataclass
class EbaySoldItem:
    """A single sold item from eBay."""

    title: str
    sold_price_eur: float
    sold_date: str = ""
    url: str = ""
    attributes: CardAttributes = field(default_factory=CardAttributes)


@dataclass
class ScoredEbayMatch:
    """An eBay item with its match score against an NFT."""

    ebay_item: EbaySoldItem
    match_result: MatchResult


@dataclass
class ArbitrageOpportunity:
    """A detected arbitrage opportunity."""

    nft: NFTListing
    ebay_avg_price_eur: float
    ebay_sold_count: int
    profit_percent: float
    ebay_search_url: str = ""
    ebay_matches: list[EbaySoldItem] = field(default_factory=list)
    match_confidence: float = 0.0
    scored_matches: list[ScoredEbayMatch] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"[{self.profit_percent:+.1f}%] {self.nft.title}\n"
            f"  Magic Eden: \u20ac{self.nft.price_eur:.2f}\n"
            f"  eBay avg:   \u20ac{self.ebay_avg_price_eur:.2f} ({self.ebay_sold_count} sales)\n"
            f"  Confidence: {self.match_confidence:.0%}\n"
            f"  ME link:    {self.nft.magic_eden_url}\n"
            f"  eBay link:  {self.ebay_search_url}"
        )
