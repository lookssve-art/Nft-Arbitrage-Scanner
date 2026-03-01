"""Enhanced deterministic parsing of graded Pokemon card attributes from titles.

Handles both Magic Eden and eBay title formats:
- ME:   "2021 #170 Full Art/Galarian Articuno V PSA 10 Sword & Shield Chilling Reign Pokemon"
- eBay: "Pokemon PSA 10 Galarian Articuno V 170/198 Chilling Reign"

Extracts: pokemon_name, variant, foil_type, card_number, grading, grade,
          set_name, edition, language, year, sub_grade, is_lot.
"""

import re
import logging
from typing import Optional

from scanner.models import CardAttributes, GradingCompany

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grading company patterns
# ---------------------------------------------------------------------------
_GRADING_PATTERNS: list[tuple[re.Pattern, GradingCompany]] = [
    (re.compile(r"\bPSA\b", re.IGNORECASE), GradingCompany.PSA),
    (re.compile(r"\bCGC\b", re.IGNORECASE), GradingCompany.CGC),
    (re.compile(r"\bBGS\b", re.IGNORECASE), GradingCompany.BGS),
    (re.compile(r"\bBeckett\b", re.IGNORECASE), GradingCompany.BGS),
    (re.compile(r"\bSGC\b", re.IGNORECASE), GradingCompany.SGC),
]

# Grade pattern: "PSA 10", "CGC 9.5", "SGC 8.5", etc.
_GRADE_PATTERN = re.compile(
    r"\b(?:PSA|CGC|BGS|Beckett|SGC)\s+(\d{1,2}(?:\.\d)?)\b",
    re.IGNORECASE,
)

# Sub-grade: "Pristine", "Gem Mint", "Perfect"
_SUB_GRADE_PATTERNS = [
    (re.compile(r"\bPristine\b", re.IGNORECASE), "Pristine"),
    (re.compile(r"\bGem\s*Mint\b", re.IGNORECASE), "Gem Mint"),
    (re.compile(r"\bPerfect\b", re.IGNORECASE), "Perfect"),
]

# ---------------------------------------------------------------------------
# Card number patterns (ordered by specificity)
# ---------------------------------------------------------------------------
_CARD_NUMBER_PATTERNS = [
    # Prefixed: SV60, TG03, GG10, SWSH261
    re.compile(r"\b((?:SV|TG|GG|SWSH|SM|XY|BW|DP|RC)\d{1,4})\b", re.IGNORECASE),
    # Slash format: 4/102, 170/198, 025/165
    re.compile(r"#?(\d{1,4}\s*/\s*\d{1,4})"),
    # Hash-prefixed: #170, #025
    re.compile(r"#(\d{1,4})\b"),
    # "No. 25" format
    re.compile(r"\bNo\.?\s*(\d{1,4})\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Year pattern
# ---------------------------------------------------------------------------
_YEAR_PATTERN = re.compile(r"\b(19[89]\d|20[012]\d)\b")

# ---------------------------------------------------------------------------
# Edition patterns
# ---------------------------------------------------------------------------
_EDITION_PATTERNS = [
    (re.compile(r"\b1st\s+Edition\b", re.IGNORECASE), "1st Edition"),
    (re.compile(r"\bFirst\s+Edition\b", re.IGNORECASE), "1st Edition"),
    (re.compile(r"\bUnlimited\b", re.IGNORECASE), "Unlimited"),
    (re.compile(r"\bShadowless\b", re.IGNORECASE), "Shadowless"),
]

# ---------------------------------------------------------------------------
# Language patterns
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Variant patterns (Pokemon card subtypes)
# Order: longest first to avoid partial matches
# ---------------------------------------------------------------------------
_VARIANT_PATTERNS = [
    (re.compile(r"\bV[\s-]*Union\b", re.IGNORECASE), "V-Union"),
    (re.compile(r"\bVSTAR\b", re.IGNORECASE), "Vstar"),
    (re.compile(r"\bVMAX\b", re.IGNORECASE), "Vmax"),
    (re.compile(r"\bV\b"), "V"),  # Case-sensitive: only capital V
    (re.compile(r"\bGX\b", re.IGNORECASE), "GX"),
    # Uppercase EX = older era (Black & White, XY); lowercase ex = SV era
    (re.compile(r"\bEX\b"), "EX"),
    (re.compile(r"\bex\b"), "ex"),
    (re.compile(r"\bLV\s*\.?\s*X\b", re.IGNORECASE), "LV.X"),
    (re.compile(r"\bBREAK\b"), "BREAK"),
    (re.compile(r"\bPRISM\s*STAR\b", re.IGNORECASE), "Prism Star"),
    (re.compile(r"\bRadiant\b", re.IGNORECASE), "Radiant"),
    (re.compile(r"\bAmazing\s*Rare\b", re.IGNORECASE), "Amazing Rare"),
]

# ---------------------------------------------------------------------------
# Foil/art type patterns
# ---------------------------------------------------------------------------
_FOIL_PATTERNS = [
    (re.compile(r"\bFull\s*Art\b", re.IGNORECASE), "Full Art"),
    (re.compile(r"\bAlt(?:ernate)?\s*Art\b", re.IGNORECASE), "Alt Art"),
    (re.compile(r"\bSpecial\s*Art\b", re.IGNORECASE), "Special Art"),
    (re.compile(r"\bIllustration\s*Rare\b", re.IGNORECASE), "Illustration Rare"),
    (re.compile(r"\bSecret\s*Rare\b", re.IGNORECASE), "Secret Rare"),
    (re.compile(r"\bArt\s*Rare\b", re.IGNORECASE), "Art Rare"),
    (re.compile(r"\bMaster\s*Ball\b", re.IGNORECASE), "Master Ball"),
    (re.compile(r"\bReverse[\s-]*(?:Holo|Foil)\b", re.IGNORECASE), "Reverse Holo"),
    (re.compile(r"\bHolo(?:graphic)?\b", re.IGNORECASE), "Holo"),
    (re.compile(r"\bGold\s*(?:Star|Rare)\b", re.IGNORECASE), "Gold"),
    (re.compile(r"\bRainbow\s*Rare\b", re.IGNORECASE), "Rainbow Rare"),
    (re.compile(r"\bTrainer\s*Gallery\b", re.IGNORECASE), "Trainer Gallery"),
    (re.compile(r"\bGalarian\s*Gallery\b", re.IGNORECASE), "Galarian Gallery"),
    (re.compile(r"\bCrown\s*Rare\b", re.IGNORECASE), "Crown Rare"),
    (re.compile(r"\bShiny\b", re.IGNORECASE), "Shiny"),
]

# ---------------------------------------------------------------------------
# Lot/bundle detection (DISQUALIFIERS)
# ---------------------------------------------------------------------------
_LOT_PATTERNS = [
    re.compile(r"\b(?:lot|bundle|sammlung|konvolut)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(?:cards?|karten?|stk\.?|pieces?|x)\b", re.IGNORECASE),
    re.compile(r"\b(?:set\s+of|collection\s+of)\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bx\s*\d+\b", re.IGNORECASE),  # "x5", "x 10"
]

# ---------------------------------------------------------------------------
# Pokemon names (comprehensive list for extraction from eBay titles)
# Sorted longest-first to prefer "Galarian Articuno" over "Articuno"
# ---------------------------------------------------------------------------
_POKEMON_NAMES = sorted([
    # Prefixed forms (must come first due to longest-first sorting)
    "Galarian Articuno", "Galarian Zapdos", "Galarian Moltres",
    "Galarian Rapidash", "Galarian Slowpoke", "Galarian Slowbro",
    "Galarian Slowking", "Galarian Ponyta", "Galarian Farfetch'd",
    "Galarian Weezing", "Galarian Darmanitan", "Galarian Corsola",
    "Galarian Zigzagoon", "Galarian Obstagoon", "Galarian Stunfisk",
    "Galarian Yamask", "Galarian Meowth", "Galarian Mr. Mime",
    "Alolan Vulpix", "Alolan Ninetales", "Alolan Exeggutor",
    "Alolan Raichu", "Alolan Marowak", "Alolan Sandshrew",
    "Alolan Muk", "Alolan Grimer", "Alolan Golem", "Alolan Dugtrio",
    "Hisuian Zoroark", "Hisuian Typhlosion", "Hisuian Decidueye",
    "Hisuian Samurott", "Hisuian Arcanine", "Hisuian Lilligant",
    "Hisuian Goodra", "Hisuian Braviary", "Hisuian Electrode",
    "Origin Forme Palkia", "Origin Forme Dialga",
    "Armored Mewtwo", "Shadow Rider Calyrex", "Ice Rider Calyrex",
    "Shining Magikarp", "Shining Gyarados", "Shining Charizard",
    "Shining Mewtwo", "Shining Mew", "Shining Raichu",
    "Dark Charizard", "Dark Blastoise", "Dark Gyarados",
    "Dark Dragonite", "Dark Dugtrio", "Dark Machamp",
    "Dark Alakazam", "Dark Arbok", "Dark Vileplume", "Dark Slowbro",
    "Dark Weezing", "Dark Magneton", "Dark Hypno", "Dark Golbat",
    "Dark Jolteon", "Dark Flareon", "Dark Vaporeon",
    "Sabrina's Gengar", "Sabrina's Mr. Mime", "Sabrina's Alakazam",
    "Brock's Ninetales", "Blaine's Charizard", "Blaine's Arcanine",
    "Misty's Golduck", "Lt. Surge's Electabuzz", "Erika's Venusaur",
    "Giovanni's Gyarados", "Koga's Beedrill", "Rocket's Mewtwo",
    "Flying Pikachu", "Surfing Pikachu", "Birthday Pikachu",
    "Detective Pikachu", "Ash's Pikachu",
    "Reshiram & Zekrom", "Reshiram & Charizard",
    "Pikachu & Zekrom", "Mew & Mewtwo", "Mewtwo & Mew",
    "Mega Charizard X", "Mega Charizard Y", "Mega Charizard",
    "Mega Blastoise", "Mega Venusaur", "Mega Rayquaza",
    "Mega Mewtwo X", "Mega Mewtwo Y", "Mega Gengar", "Mega Gardevoir",
    "Mega Latias", "Mega Latios", "Mega Lucario", "Mega Sceptile",
    "Mega Swampert", "Mega Blaziken", "Mega Tyranitar",
    "Tapu Koko", "Tapu Lele", "Tapu Bulu", "Tapu Fini",
    "Mr. Mime", "Mr. Rime", "Mime Jr.",
    "Ho-Oh", "Porygon-Z", "Porygon2", "Type: Null",
    "Gouging Fire", "Raging Bolt", "Iron Valiant", "Iron Hands",
    "Iron Thorns", "Iron Bundle", "Iron Moth", "Iron Leaves",
    "Iron Crown", "Iron Boulder", "Walking Wake", "Great Tusk",
    "Scream Tail", "Brute Bonnet", "Sandy Shocks", "Slither Wing",
    "Roaring Moon", "Flutter Mane",
    "Hop's Zacian", "Team Rocket's Weezing", "Team Rocket's Wobbuffet",
    "Iono's Wattrel", "Iono's Bellibolt",
    # Base Pokemon (single names)
    "Charizard", "Pikachu", "Mewtwo", "Blastoise", "Venusaur",
    "Eevee", "Umbreon", "Espeon", "Flareon", "Jolteon", "Vaporeon",
    "Glaceon", "Leafeon", "Sylveon",
    "Rayquaza", "Lugia", "Ho-Oh", "Gengar", "Dragonite", "Snorlax",
    "Mew", "Raichu", "Kangaskhan", "Diancie", "Swablu", "Zekrom",
    "Reshiram", "Yveltal", "Victini", "Haunter", "Feraligatr",
    "Scizor", "Tyranitar", "Bulbasaur", "Meowth", "Gyarados",
    "Hoopa", "Gardevoir", "Ninetales", "Lucario", "Deoxys",
    "Ditto", "Shuckle", "Inteleon", "Calyrex", "Machoke",
    "Articuno", "Zapdos", "Moltres", "Dragonair", "Dratini",
    "Magikarp", "Lapras", "Machamp", "Alakazam", "Starmie",
    "Chansey", "Wigglytuff", "Clefairy", "Clefable", "Nidoking",
    "Nidoqueen", "Vileplume", "Poliwrath", "Kadabra", "Exeggutor",
    "Electrode", "Weezing", "Arcanine", "Rapidash", "Slowbro",
    "Magneton", "Dewgong", "Muk", "Hypno", "Kingler",
    "Beedrill", "Pidgeot", "Butterfree", "Raikou", "Entei", "Suicune",
    "Celebi", "Groudon", "Kyogre", "Latias", "Latios", "Jirachi",
    "Dialga", "Palkia", "Giratina", "Darkrai", "Arceus", "Shaymin",
    "Cresselia", "Heatran", "Regigigas", "Manaphy", "Phione",
    "Xerneas", "Zygarde", "Diancie", "Volcanion",
    "Solgaleo", "Lunala", "Necrozma", "Marshadow", "Zeraora",
    "Zacian", "Zamazenta", "Eternatus", "Urshifu",
    "Melmetal", "Meltan", "Zarude", "Regieleki", "Regidrago",
    "Glastrier", "Spectrier",
    "Koraidon", "Miraidon", "Terapagos",
    "Ogerpon", "Pecharunt", "Munkidori", "Okidogi", "Fezandipiti",
    "Squirtle", "Charmander", "Wartortle", "Charmeleon", "Ivysaur",
    "Psyduck", "Golduck", "Poliwag", "Poliwhirl", "Geodude",
    "Golem", "Ponyta", "Abra", "Gastly", "Onix", "Cubone",
    "Hitmonchan", "Hitmonlee", "Lickitung", "Rhyhorn", "Tangela",
    "Horsea", "Seadra", "Staryu", "Scyther", "Jynx",
    "Electabuzz", "Magmar", "Pinsir", "Tauros", "Aerodactyl",
    "Kabuto", "Kabutops", "Omanyte", "Omastar",
    "Totodile", "Cyndaquil", "Chikorita", "Bayleef", "Meganium",
    "Typhlosion", "Croconaw", "Quilava",
    "Pichu", "Togepi", "Togetic", "Marill", "Azumarill",
    "Heracross", "Sneasel", "Houndoom", "Houndour",
    "Kingdra", "Donphan", "Porygon", "Steelix", "Smeargle",
    "Larvitar", "Pupitar",
    "Treecko", "Torchic", "Mudkip", "Grovyle", "Combusken",
    "Marshtomp", "Sceptile", "Blaziken", "Swampert",
    "Gardevoir", "Ralts", "Kirlia", "Aggron", "Absol",
    "Salamence", "Metagross", "Bagon", "Beldum", "Milotic",
    "Feebas", "Flygon", "Altaria", "Zangoose", "Seviper",
    "Banette", "Shuppet", "Dusclops", "Chimecho",
    "Turtwig", "Chimchar", "Piplup", "Grotle", "Monferno",
    "Prinplup", "Torterra", "Infernape", "Empoleon",
    "Staraptor", "Luxray", "Roserade", "Garchomp", "Lucario",
    "Togekiss", "Leafeon", "Glaceon", "Gallade", "Froslass",
    "Rotom", "Weavile", "Magnezone", "Rhyperior",
    "Snivy", "Tepig", "Oshawott", "Serperior", "Emboar",
    "Samurott", "Zoroark", "Zorua", "Hydreigon", "Volcarona",
    "Chandelure", "Excadrill", "Haxorus", "Bisharp",
    "Braviary", "Mandibuzz", "Durant", "Cobalion", "Terrakion",
    "Virizion", "Tornadus", "Thundurus", "Landorus",
    "Chespin", "Fennekin", "Froakie", "Quilladin", "Braixen",
    "Frogadier", "Chesnaught", "Delphox", "Greninja",
    "Talonflame", "Aegislash", "Gogoat", "Pangoro",
    "Hawlucha", "Dedenne", "Goodra", "Noivern",
    "Rowlet", "Litten", "Popplio", "Decidueye", "Incineroar",
    "Primarina", "Lycanroc", "Mimikyu", "Toxapex",
    "Golisopod", "Salazzle", "Kommo-o", "Silvally",
    "Buzzwole", "Pheromosa", "Xurkitree", "Celesteela",
    "Kartana", "Guzzlord", "Poipole", "Naganadel",
    "Stakataka", "Blacephalon",
    "Grookey", "Scorbunny", "Sobble", "Rillaboom", "Cinderace",
    "Inteleon", "Corviknight", "Toxtricity", "Grimmsnarl",
    "Alcremie", "Dragapult", "Dracovish", "Duraludon",
    "Copperajah", "Wooloo", "Cramorant",
    "Sprigatito", "Fuecoco", "Quaxly", "Meowscarada",
    "Skeledirge", "Quaquaval", "Armarouge", "Ceruledge",
    "Palafin", "Tinkaton", "Kingambit", "Annihilape",
    "Gholdengo", "Baxcalibur", "Dondozo", "Tatsugiri",
    "Chien-Pao", "Ting-Lu", "Chi-Yu", "Wo-Chien",
    "Helioptile", "Heliolisk", "Trubbish", "Garbodor",
    "Riolu", "Piplup", "Maractus", "Exeggcute",
    "Delcatty", "Shiftry", "Eelektrik", "Eelektross",
    "Raticate", "Rattata", "Rattfratz", "Porenta",
    "Smogon", "Oricorio",
], key=len, reverse=True)

# ---------------------------------------------------------------------------
# Known Pokemon TCG set names + abbreviation mappings
# ---------------------------------------------------------------------------
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
    "Journey Together", "Destined Rivals",
    # Japanese set names (commonly found in ME titles)
    "Vstar Universe", "Eevee Heroes", "Dream League",
    "Terastal Fest", "Super Electric Breaker",
    "Battle Partners", "Glory of Team Rocket",
    "Infinity Zone", "Mega Symphonia", "Inferno X",
    "Mega Brave", "Mega Dream", "White Flare",
    "Cyber Judge", "Wild Force", "Night Wanderer",
    "Crimson Haze", "Mask of Change",
    "Shiny Treasure", "Ancient Roar", "Future Flash",
    "Ruler of the Black Flame", "Snow Hazard", "Clay Burst",
    "Triplet Beat", "Violet ex", "Scarlet ex",
    "25th Anniversary Collection",
    "Galactic's Conquest", "Tidal Storm", "Undone Seal",
    "Bonds to End of Time",
    # Common abbreviated/informal names
    "Black Star Promo", "Swsh Black Star Promo",
    "SM Promo", "XY Promo", "BW Promo",
    "Classic Collection", "Celebrations Classic Collection",
    "Detective Pikachu",
]

# Abbreviation → full set name mapping
_SET_ABBREVIATIONS: dict[str, str] = {
    "cr": "Chilling Reign",
    "es": "Evolving Skies",
    "bs": "Battle Styles",
    "vv": "Vivid Voltage",
    "da": "Darkness Ablaze",
    "rc": "Rebel Clash",
    "sf": "Shining Fates",
    "cp": "Champion's Path",
    "hf": "Hidden Fates",
    "ce": "Cosmic Eclipse",
    "um": "Unified Minds",
    "ub": "Unbroken Bonds",
    "tu": "Team Up",
    "lt": "Lost Thunder",
    "fs": "Fusion Strike",
    "brs": "Brilliant Stars",
    "ar": "Astral Radiance",
    "lo": "Lost Origin",
    "st": "Silver Tempest",
    "cz": "Crown Zenith",
    "sv": "Scarlet & Violet",
    "pe": "Paldea Evolved",
    "of": "Obsidian Flames",
    "pr": "Paradox Rift",
    "pf": "Paldean Fates",
    "tf": "Temporal Forces",
    "tm": "Twilight Masquerade",
    "sc": "Stellar Crown",
    "ssp": "Surging Sparks",
    "pre": "Prismatic Evolutions",
    "jtg": "Journey Together",
    "dri": "Destined Rivals",
    "swsh": "Sword & Shield",
    "sm": "Sun & Moon",
}

# Pre-compile set name patterns (longest first)
_SET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE), s)
    for s in sorted(_KNOWN_SETS, key=len, reverse=True)
]


def _extract_year(title: str) -> str:
    """Extract a 4-digit year from the title."""
    m = _YEAR_PATTERN.search(title)
    return m.group(1) if m else ""


def _extract_grading(title: str) -> tuple[GradingCompany, Optional[float], str]:
    """Extract grading company, grade, and sub-grade from title."""
    company = GradingCompany.UNKNOWN
    for pattern, comp in _GRADING_PATTERNS:
        if pattern.search(title):
            company = comp
            break

    grade = None
    grade_match = _GRADE_PATTERN.search(title)
    if grade_match:
        try:
            grade = float(grade_match.group(1))
        except ValueError:
            pass

    sub_grade = ""
    for pattern, sg in _SUB_GRADE_PATTERNS:
        if pattern.search(title):
            sub_grade = sg
            break

    return company, grade, sub_grade


def _extract_card_number(title: str) -> str:
    """Extract card number from title, avoiding year matches."""
    year = _extract_year(title)
    for pattern in _CARD_NUMBER_PATTERNS:
        for m in pattern.finditer(title):
            num = m.group(1).replace(" ", "")
            # Skip if this is just the year
            if num == year:
                continue
            # Skip numbers that are clearly grades (1-10 after grading company)
            if _GRADE_PATTERN.search(title):
                grade_match = _GRADE_PATTERN.search(title)
                if grade_match and m.start() == grade_match.start(1):
                    continue
            return num
    return ""


# Series prefixes that are also valid set names but should yield to sub-sets
_SERIES_PREFIXES = {
    "Sword & Shield", "Sun & Moon", "Scarlet & Violet",
    "Black & White", "Diamond & Pearl", "XY",
    "HeartGold & SoulSilver", "Ruby & Sapphire",
}


def _extract_set_name(title: str) -> str:
    """Extract set name from title using known set list.

    When a generic series prefix matches (e.g. 'Sword & Shield'),
    prefer a more specific sub-set if found (e.g. 'Chilling Reign').
    """
    all_matches: list[str] = []
    for pattern, set_name in _SET_PATTERNS:
        if pattern.search(title):
            all_matches.append(set_name)

    if not all_matches:
        return ""

    # Prefer specific sets over generic series prefixes
    specific = [m for m in all_matches if m not in _SERIES_PREFIXES]
    if specific:
        return specific[0]

    return all_matches[0]


def _extract_edition(title: str) -> str:
    """Extract edition from title."""
    for pattern, edition in _EDITION_PATTERNS:
        if pattern.search(title):
            return edition
    return ""


def _extract_language(title: str) -> str:
    """Extract language from title."""
    for pattern, language in _LANGUAGE_PATTERNS:
        if pattern.search(title):
            return language
    return ""


def _extract_variant(title: str) -> str:
    """Extract card variant (V, Vmax, GX, etc.) from title."""
    for pattern, variant in _VARIANT_PATTERNS:
        if pattern.search(title):
            return variant
    return ""


def _extract_foil_type(title: str) -> str:
    """Extract foil/art type from title."""
    for pattern, foil in _FOIL_PATTERNS:
        if pattern.search(title):
            return foil
    return ""


def _detect_lot(title: str) -> bool:
    """Detect if a listing is a lot/bundle of multiple cards."""
    for pattern in _LOT_PATTERNS:
        if pattern.search(title):
            return True
    return False


def _extract_pokemon_name(title: str) -> str:
    """Extract the Pokemon name from the title.

    Uses a comprehensive name list, preferring longer matches.
    The list is sorted longest-first, so "Galarian Articuno" matches
    before "Articuno".
    """
    title_lower = title.lower()
    for name in _POKEMON_NAMES:
        if name.lower() in title_lower:
            return name
    return ""


def _extract_pokemon_name_positional(title: str) -> str:
    """Extract Pokemon name from ME-format titles using position.

    ME format: "YEAR #NUMBER [FOIL/]POKEMON [VARIANT] GRADING GRADE ..."
    The Pokemon name is between the card number and grading info.
    """
    # Try to find the segment between card number and grading
    # Remove year prefix
    cleaned = re.sub(r"^\d{4}\s+", "", title)
    # Remove card number prefix
    cleaned = re.sub(r"^#\w+\s+", "", cleaned)
    # Remove foil prefix (before /)
    if "/" in cleaned:
        parts = cleaned.split("/", 1)
        if len(parts[0].split()) <= 3:  # Foil type is usually 1-3 words
            cleaned = parts[1].strip()

    # Now extract up to the grading company
    grading_match = re.search(r"\b(?:PSA|CGC|BGS|SGC|Beckett)\b", cleaned, re.IGNORECASE)
    if grading_match:
        before_grading = cleaned[:grading_match.start()].strip()
        # Remove variant from the end
        for pattern, _ in _VARIANT_PATTERNS:
            before_grading = pattern.sub("", before_grading).strip()
        if before_grading:
            return before_grading

    return ""


def parse_card_title(title: str) -> CardAttributes:
    """Parse a card title into structured attributes.

    Works for both ME and eBay title formats. Uses regex-based extraction
    with comprehensive pattern lists.
    """
    attrs = CardAttributes()

    # 1. Lot/bundle detection (highest priority)
    attrs.is_lot = _detect_lot(title)

    # 2. Year
    attrs.year = _extract_year(title)

    # 3. Grading company + grade + sub-grade
    attrs.grading_company, attrs.grade, attrs.sub_grade = _extract_grading(title)

    # 4. Card number (avoid year collision)
    attrs.card_number = _extract_card_number(title)

    # 5. Set name
    attrs.set_name = _extract_set_name(title)

    # 6. Edition
    attrs.edition = _extract_edition(title)

    # 7. Language
    attrs.language = _extract_language(title)

    # 8. Variant (V, Vmax, GX, etc.)
    attrs.variant = _extract_variant(title)

    # 9. Foil/art type
    attrs.foil_type = _extract_foil_type(title)

    # 10. Pokemon name
    # Try list-based extraction first (works for both ME and eBay)
    attrs.pokemon_name = _extract_pokemon_name(title)
    # If that fails, try positional extraction (ME titles only)
    if not attrs.pokemon_name:
        attrs.pokemon_name = _extract_pokemon_name_positional(title)

    logger.debug(
        "Parsed '%s' → pokemon=%s variant=%s foil=%s company=%s grade=%s "
        "number=%s set=%s edition=%s lang=%s year=%s lot=%s",
        title[:80],
        attrs.pokemon_name,
        attrs.variant,
        attrs.foil_type,
        attrs.grading_company.value,
        attrs.grade,
        attrs.card_number,
        attrs.set_name,
        attrs.edition,
        attrs.language,
        attrs.year,
        attrs.is_lot,
    )
    return attrs


def extract_from_me_attributes(
    me_attrs: list[dict],
    title_attrs: CardAttributes,
) -> CardAttributes:
    """Enrich CardAttributes with structured ME trait data.

    ME traits are more reliable than title parsing. If a trait provides
    a value, it overrides the title-parsed value.

    Common ME/Phygitals traits:
    - "Category": "Pokemon"
    - "Grading Company": "PSA"  (ME) or parsed from "Grade" (Phygitals)
    - "Grade": "10"  (ME) or "PSA 9.0" / "CGC 10.0" / "Ungraded" (Phygitals)
    - "Year": "2021"
    - "Name": "Pikachu"  (Phygitals: pokemon name)
    - "Card Id": "sv3pt5-21"  (Phygitals: set-number format)
    - "Number": "149"  (Phygitals: card number)
    - "Foil Type": "Normal" / "Holo"  (Phygitals)
    """
    for attr in me_attrs:
        trait = str(attr.get("trait_type", "")).strip()
        value = str(attr.get("value", "")).strip()
        if not trait or not value:
            continue

        trait_lower = trait.lower()

        if trait_lower == "grading company":
            for pattern, company in _GRADING_PATTERNS:
                if pattern.search(value):
                    title_attrs.grading_company = company
                    break

        elif trait_lower == "grade":
            # Phygitals format: "PSA 9.0", "CGC 10.0", "Ungraded"
            # ME format: just "10" or "9.5"
            if value.lower() == "ungraded":
                title_attrs.grading_company = GradingCompany.UNKNOWN
                title_attrs.grade = None
            else:
                # Try to extract grading company + grade from combined string
                for pattern, company in _GRADING_PATTERNS:
                    if pattern.search(value):
                        title_attrs.grading_company = company
                        break
                grade_match = _GRADE_PATTERN.search(value)
                if grade_match:
                    try:
                        title_attrs.grade = float(grade_match.group(1))
                    except ValueError:
                        pass
                else:
                    # Plain numeric grade (ME format)
                    try:
                        title_attrs.grade = float(value)
                    except ValueError:
                        pass

        elif trait_lower == "year":
            title_attrs.year = value

        elif trait_lower == "language":
            title_attrs.language = value

        elif trait_lower in ("set", "set name"):
            title_attrs.set_name = value

        elif trait_lower in ("card number", "card id"):
            # Phygitals Card Id format: "sv3pt5-21" -> take number after dash
            if "-" in value and not title_attrs.card_number:
                title_attrs.card_number = value.split("-")[-1]
            elif not title_attrs.card_number:
                title_attrs.card_number = value

        elif trait_lower == "number":
            # Phygitals "Number" trait: "149"
            if not title_attrs.card_number:
                title_attrs.card_number = value

        elif trait_lower == "edition":
            title_attrs.edition = value

        elif trait_lower == "name":
            # Phygitals "Name" trait: the Pokemon name
            if not title_attrs.pokemon_name:
                title_attrs.pokemon_name = value

        elif trait_lower == "foil type":
            if value.lower() != "normal" and not title_attrs.foil_type:
                title_attrs.foil_type = value

        elif trait_lower == "rarity":
            # Map rarity to foil type if relevant
            rarity_lower = value.lower()
            if not title_attrs.foil_type and rarity_lower in (
                "illustration rare", "special art rare", "art rare",
                "secret rare", "hyper rare", "ultra rare",
            ):
                title_attrs.foil_type = value

    return title_attrs


# Exported for use in ebay.py search query building
POKEMON_NAMES = _POKEMON_NAMES
SET_ABBREVIATIONS = _SET_ABBREVIATIONS
