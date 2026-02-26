"""Strict deterministic parsing of graded Pokemon card attributes from titles.

NO fuzzy matching. NO AI-based semantic matching.
Uses regex-based extraction for:
- Grading company (PSA, CGC, BGS/Beckett)
- Grade (numeric, e.g. 10, 9.5, 9)
- Card number (e.g. #4/102, 025/165)
- Set name (e.g. Base Set, Jungle, Fossil)
- Edition (1st Edition, Unlimited)
- Language (English, Japanese, German, etc.)
"""

import re
import logging

from scanner.models import CardAttributes, GradingCompany

logger = logging.getLogger(__name__)

# --- Grading company patterns ---
_GRADING_PATTERNS: list[tuple[re.Pattern, GradingCompany]] = [
    (re.compile(r"\bPSA\b", re.IGNORECASE), GradingCompany.PSA),
    (re.compile(r"\bCGC\b", re.IGNORECASE), GradingCompany.CGC),
    (re.compile(r"\bBGS\b", re.IGNORECASE), GradingCompany.BGS),
    (re.compile(r"\bBeckett\b", re.IGNORECASE), GradingCompany.BGS),
]

# --- Grade pattern: matches "PSA 10", "CGC 9.5", "BGS 10", etc. ---
_GRADE_PATTERN = re.compile(
    r"\b(?:PSA|CGC|BGS|Beckett)\s+(\d{1,2}(?:\.\d)?)\b",
    re.IGNORECASE,
)

# --- Card number patterns ---
# Matches: #4/102, 4/102, #025/165, 025, #025, No. 25, etc.
_CARD_NUMBER_PATTERNS = [
    re.compile(r"#?(\d{1,4}\s*/\s*\d{1,4})"),  # 4/102, #025/165
    re.compile(r"\bNo\.?\s*(\d{1,4})\b", re.IGNORECASE),  # No. 25
    re.compile(r"#(\d{1,4})\b"),  # #025
]

# --- Edition patterns ---
_EDITION_PATTERNS = [
    (re.compile(r"\b1st\s+Edition\b", re.IGNORECASE), "1st Edition"),
    (re.compile(r"\bFirst\s+Edition\b", re.IGNORECASE), "1st Edition"),
    (re.compile(r"\bUnlimited\b", re.IGNORECASE), "Unlimited"),
    (re.compile(r"\bShadowless\b", re.IGNORECASE), "Shadowless"),
]

# --- Known Pokemon TCG set names ---
_KNOWN_SETS = [
    "Base Set", "Base Set 2", "Jungle", "Fossil", "Team Rocket",
    "Gym Heroes", "Gym Challenge", "Neo Genesis", "Neo Discovery",
    "Neo Revelation", "Neo Destiny", "Legendary Collection",
    "Expedition", "Aquapolis", "Skyridge",
    "Ruby & Sapphire", "Sandstorm", "Dragon", "Team Magma vs Team Aqua",
    "Hidden Legends", "FireRed & LeafGreen", "Team Rocket Returns",
    "Deoxys", "Emerald", "Unseen Forces", "Delta Species",
    "Legend Maker", "Holon Phantoms", "Crystal Guardians",
    "Dragon Frontiers", "Power Keepers",
    "Diamond & Pearl", "Mysterious Treasures", "Secret Wonders",
    "Great Encounters", "Majestic Dawn", "Legends Awakened",
    "Stormfront", "Platinum", "Rising Rivals", "Supreme Victors",
    "Arceus", "HeartGold & SoulSilver", "Unleashed", "Undaunted",
    "Triumphant", "Call of Legends",
    "Black & White", "Emerging Powers", "Noble Victories",
    "Next Destinies", "Dark Explorers", "Dragons Exalted",
    "Boundaries Crossed", "Plasma Storm", "Plasma Freeze",
    "Plasma Blast", "Legendary Treasures",
    "XY", "Flashfire", "Furious Fists", "Phantom Forces",
    "Primal Clash", "Roaring Skies", "Ancient Origins",
    "BREAKthrough", "BREAKpoint", "Fates Collide",
    "Steam Siege", "Evolutions",
    "Sun & Moon", "Guardians Rising", "Burning Shadows",
    "Shining Legends", "Crimson Invasion", "Ultra Prism",
    "Forbidden Light", "Celestial Storm", "Lost Thunder",
    "Team Up", "Unbroken Bonds", "Unified Minds",
    "Hidden Fates", "Cosmic Eclipse",
    "Sword & Shield", "Rebel Clash", "Darkness Ablaze",
    "Champion's Path", "Vivid Voltage", "Shining Fates",
    "Battle Styles", "Chilling Reign", "Evolving Skies",
    "Celebrations", "Fusion Strike", "Brilliant Stars",
    "Astral Radiance", "Pokemon GO", "Lost Origin",
    "Silver Tempest", "Crown Zenith",
    "Scarlet & Violet", "Paldea Evolved", "Obsidian Flames",
    "151", "Paradox Rift", "Paldean Fates",
    "Temporal Forces", "Twilight Masquerade", "Shrouded Fable",
    "Stellar Crown", "Surging Sparks", "Prismatic Evolutions",
]

# Pre-compile set name patterns (case-insensitive, word-boundary)
_SET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE), s)
    for s in sorted(_KNOWN_SETS, key=len, reverse=True)  # longest first to avoid partial matches
]

# --- Language patterns ---
_LANGUAGE_PATTERNS = [
    (re.compile(r"\bJapanese\b", re.IGNORECASE), "Japanese"),
    (re.compile(r"\bEnglish\b", re.IGNORECASE), "English"),
    (re.compile(r"\bGerman\b", re.IGNORECASE), "German"),
    (re.compile(r"\bFrench\b", re.IGNORECASE), "French"),
    (re.compile(r"\bItalian\b", re.IGNORECASE), "Italian"),
    (re.compile(r"\bSpanish\b", re.IGNORECASE), "Spanish"),
    (re.compile(r"\bKorean\b", re.IGNORECASE), "Korean"),
    (re.compile(r"\bChinese\b", re.IGNORECASE), "Chinese"),
    (re.compile(r"\bDeutsch\b", re.IGNORECASE), "German"),
    (re.compile(r"\bJPN\b", re.IGNORECASE), "Japanese"),
    (re.compile(r"\bENG\b", re.IGNORECASE), "English"),
    (re.compile(r"\bGER\b", re.IGNORECASE), "German"),
]


def parse_card_title(title: str) -> CardAttributes:
    """Parse a card title into structured attributes using strict regex matching.

    Returns CardAttributes with all fields that could be extracted.
    Fields that cannot be determined are left empty/None.
    """
    attrs = CardAttributes()

    # 1. Extract grading company
    for pattern, company in _GRADING_PATTERNS:
        if pattern.search(title):
            attrs.grading_company = company
            break

    # 2. Extract grade
    grade_match = _GRADE_PATTERN.search(title)
    if grade_match:
        try:
            attrs.grade = float(grade_match.group(1))
        except ValueError:
            pass

    # 3. Extract card number
    for pattern in _CARD_NUMBER_PATTERNS:
        match = pattern.search(title)
        if match:
            attrs.card_number = match.group(1).replace(" ", "")
            break

    # 4. Extract set name
    for pattern, set_name in _SET_PATTERNS:
        if pattern.search(title):
            attrs.set_name = set_name
            break

    # 5. Extract edition
    for pattern, edition in _EDITION_PATTERNS:
        if pattern.search(title):
            attrs.edition = edition
            break

    # 6. Extract language
    for pattern, language in _LANGUAGE_PATTERNS:
        if pattern.search(title):
            attrs.language = language
            break

    logger.debug(
        "Parsed '%s' → company=%s grade=%s number=%s set=%s edition=%s lang=%s",
        title,
        attrs.grading_company.value,
        attrs.grade,
        attrs.card_number,
        attrs.set_name,
        attrs.edition,
        attrs.language,
    )
    return attrs
