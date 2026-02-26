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
    UNKNOWN = "UNKNOWN"


@dataclass
class CardAttributes:
    """Parsed attributes of a graded Pokemon card."""

    grading_company: GradingCompany = GradingCompany.UNKNOWN
    grade: float | None = None  # e.g. 10, 9.5, 9
    card_number: str = ""  # e.g. "4/102", "#025"
    set_name: str = ""  # e.g. "Base Set", "Jungle"
    edition: str = ""  # e.g. "1st Edition", "Unlimited"
    language: str = ""  # e.g. "English", "Japanese"

    def matches(self, other: CardAttributes) -> bool:
        """Strict 1:1 deterministic matching. All non-empty fields must match exactly."""
        if self.grading_company != other.grading_company:
            return False
        if self.grade != other.grade:
            return False
        if self.card_number and other.card_number:
            if self._normalize_card_number(self.card_number) != self._normalize_card_number(other.card_number):
                return False
        if self.set_name and other.set_name:
            if self._normalize(self.set_name) != self._normalize(other.set_name):
                return False
        if self.edition and other.edition:
            if self._normalize(self.edition) != self._normalize(other.edition):
                return False
        if self.language and other.language:
            if self._normalize(self.language) != self._normalize(other.language):
                return False
        return True

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower().replace("-", " ").replace("_", " ")

    @staticmethod
    def _normalize_card_number(num: str) -> str:
        return num.strip().lower().replace("#", "").replace(" ", "")


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


@dataclass
class EbaySoldItem:
    """A single sold item from eBay."""

    title: str
    sold_price_eur: float
    sold_date: str = ""
    url: str = ""
    attributes: CardAttributes = field(default_factory=CardAttributes)


@dataclass
class ArbitrageOpportunity:
    """A detected arbitrage opportunity."""

    nft: NFTListing
    ebay_avg_price_eur: float
    ebay_sold_count: int
    profit_percent: float
    ebay_search_url: str = ""
    ebay_matches: list[EbaySoldItem] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"[{self.profit_percent:+.1f}%] {self.nft.title}\n"
            f"  Magic Eden: €{self.nft.price_eur:.2f}\n"
            f"  eBay avg:   €{self.ebay_avg_price_eur:.2f} ({self.ebay_sold_count} sales)\n"
            f"  ME link:    {self.nft.magic_eden_url}\n"
            f"  eBay link:  {self.ebay_search_url}"
        )
