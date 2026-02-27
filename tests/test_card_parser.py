"""Tests for the enhanced card title parser."""

from scanner.card_parser import parse_card_title, extract_from_me_attributes
from scanner.models import CardAttributes, GradingCompany


# ---------------------------------------------------------------------------
# Grading extraction
# ---------------------------------------------------------------------------

def test_parse_psa_10():
    title = "PSA 10 Charizard 4/102 Base Set 1st Edition"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 10
    assert attrs.card_number == "4/102"
    assert attrs.set_name == "Base Set"
    assert attrs.edition == "1st Edition"


def test_parse_cgc_9_5():
    title = "CGC 9.5 Pikachu #025 Jungle Unlimited"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.CGC
    assert attrs.grade == 9.5
    assert attrs.card_number == "025"
    assert attrs.set_name == "Jungle"
    assert attrs.edition == "Unlimited"


def test_parse_bgs():
    title = "BGS 9 Blastoise 2/102 Base Set 1st Edition English"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.BGS
    assert attrs.grade == 9
    assert attrs.card_number == "2/102"
    assert attrs.edition == "1st Edition"
    assert attrs.language == "English"


def test_parse_beckett_alias():
    title = "Beckett 10 Mewtwo #150 Base Set"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.BGS
    assert attrs.grade == 10


def test_parse_sgc():
    title = "1999 #52 Exeggcute SGC 8.5 Pokemon Jungle"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.SGC
    assert attrs.grade == 8.5
    assert attrs.card_number == "52"


def test_parse_no_grading():
    title = "Charizard Base Set 4/102"
    attrs = parse_card_title(title)
    assert attrs.grading_company == GradingCompany.UNKNOWN
    assert attrs.grade is None


# ---------------------------------------------------------------------------
# Pokemon name extraction
# ---------------------------------------------------------------------------

def test_extract_pokemon_name_simple():
    title = "PSA 10 Charizard 4/102 Base Set"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Charizard"


def test_extract_pokemon_name_galarian():
    title = "2021 #170 Full Art/Galarian Articuno V PSA 10 Chilling Reign Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Galarian Articuno"


def test_extract_pokemon_name_tag_team():
    title = "Reshiram & Zekrom GX CGC 10 Dream League Japanese"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Reshiram & Zekrom"


def test_extract_pokemon_name_prefixed():
    title = "2021 #005 Dark Gyarados-Holo CGC 10 Pristine Promo"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Dark Gyarados"


def test_extract_pokemon_sabrina():
    title = "2000 #59 Sabrina's Mr. Mime 1st Edition CGC 10 Gym Challenge"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Sabrina's Mr. Mime"


def test_extract_pokemon_hop_zacian():
    title = "2025 #186 Hop's Zacian EX PSA 9 Journey Together Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Hop's Zacian"


def test_extract_pokemon_team_rocket():
    title = "2025 #199 Team Rocket's Weezing PSA 10 Destined Rivals Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Team Rocket's Weezing"


# ---------------------------------------------------------------------------
# Variant extraction
# ---------------------------------------------------------------------------

def test_extract_variant_v():
    title = "Galarian Articuno V PSA 10 Chilling Reign"
    attrs = parse_card_title(title)
    assert attrs.variant == "V"


def test_extract_variant_vmax():
    title = "2021 #180 Full Art/Flareon Vmax PSA 9 Promo Pokemon"
    attrs = parse_card_title(title)
    assert attrs.variant == "Vmax"


def test_extract_variant_vstar():
    title = "2022 #051 Mewtwo Vstar CGC 10 Pristine Japanese"
    attrs = parse_card_title(title)
    assert attrs.variant == "Vstar"


def test_extract_variant_gx():
    title = "2019 #SV60 Full Art/Espeon GX PSA 10 Hidden Fates"
    attrs = parse_card_title(title)
    assert attrs.variant == "GX"


def test_extract_variant_ex_uppercase():
    title = "PSA 10 Charizard EX 12/108 XY Evolutions"
    attrs = parse_card_title(title)
    assert attrs.variant == "EX"


def test_extract_variant_ex_lowercase():
    title = "Charizard ex PSA 10 Obsidian Flames"
    attrs = parse_card_title(title)
    assert attrs.variant == "ex"


def test_extract_variant_v_union():
    title = "2021 #166 Zacian V-Union PSA 9 Swsh Black Star Promo"
    attrs = parse_card_title(title)
    assert attrs.variant == "V-Union"


def test_no_variant_for_old_cards():
    title = "PSA 10 Charizard 4/102 Base Set 1st Edition"
    attrs = parse_card_title(title)
    assert attrs.variant == ""


# ---------------------------------------------------------------------------
# Foil/art type extraction
# ---------------------------------------------------------------------------

def test_extract_foil_full_art():
    title = "2021 #170 Full Art/Galarian Articuno V PSA 10"
    attrs = parse_card_title(title)
    assert attrs.foil_type == "Full Art"


def test_extract_foil_reverse_holo():
    title = "Eevee Reverse Holo PSA 9 Vivid Voltage"
    attrs = parse_card_title(title)
    assert attrs.foil_type == "Reverse Holo"


def test_extract_foil_master_ball():
    title = "Dragonair Master Ball Reverse Holo PSA 10 Japanese Sv2a"
    attrs = parse_card_title(title)
    assert attrs.foil_type == "Master Ball"


def test_extract_foil_art_rare():
    title = "Shiftry Art Rare CGC 10 Japanese Cyber Judge"
    attrs = parse_card_title(title)
    assert attrs.foil_type == "Art Rare"


# ---------------------------------------------------------------------------
# Card number extraction
# ---------------------------------------------------------------------------

def test_card_number_slash():
    title = "PSA 10 Charizard 4/102 Base Set"
    attrs = parse_card_title(title)
    assert attrs.card_number == "4/102"


def test_card_number_hash():
    title = "2021 #170 Articuno V PSA 10 Chilling Reign"
    attrs = parse_card_title(title)
    assert attrs.card_number == "170"


def test_card_number_prefixed():
    title = "2019 #SV60 Espeon GX PSA 10 Hidden Fates"
    attrs = parse_card_title(title)
    assert attrs.card_number == "SV60"


def test_card_number_not_year():
    """Card number extraction should not confuse with year."""
    title = "2021 #170 Articuno V PSA 10 Chilling Reign Pokemon"
    attrs = parse_card_title(title)
    assert attrs.card_number == "170"
    assert attrs.year == "2021"
    assert attrs.card_number != attrs.year


# ---------------------------------------------------------------------------
# Set name extraction
# ---------------------------------------------------------------------------

def test_set_name_simple():
    title = "PSA 10 Charizard 4/102 Base Set"
    attrs = parse_card_title(title)
    assert attrs.set_name == "Base Set"


def test_set_name_chilling_reign():
    title = "Articuno V PSA 10 #170 Chilling Reign"
    attrs = parse_card_title(title)
    assert attrs.set_name == "Chilling Reign"


def test_set_name_hidden_fates():
    title = "Espeon GX PSA 10 SV60 Hidden Fates"
    attrs = parse_card_title(title)
    assert attrs.set_name == "Hidden Fates"


def test_set_name_japanese():
    title = "Mewtwo Vstar CGC 10 Japanese Vstar Universe"
    attrs = parse_card_title(title)
    assert attrs.set_name == "Vstar Universe"


def test_set_name_journey_together():
    title = "2025 #186 Hop's Zacian EX PSA 9 Journey Together Pokemon"
    attrs = parse_card_title(title)
    assert attrs.set_name == "Journey Together"


# ---------------------------------------------------------------------------
# Language extraction
# ---------------------------------------------------------------------------

def test_language_japanese():
    title = "PSA 10 Charizard VMAX Japanese Shining Fates"
    attrs = parse_card_title(title)
    assert attrs.language == "Japanese"


def test_language_german():
    title = "1999 #61 Rattfratz 1st Edition PSA 9 German Pokemon"
    attrs = parse_card_title(title)
    assert attrs.language == "German"


def test_language_default_empty():
    title = "PSA 10 Charizard 4/102 Base Set"
    attrs = parse_card_title(title)
    assert attrs.language == ""


# ---------------------------------------------------------------------------
# Year extraction
# ---------------------------------------------------------------------------

def test_year_extraction():
    title = "2021 #170 Articuno V PSA 10 Chilling Reign"
    attrs = parse_card_title(title)
    assert attrs.year == "2021"


def test_year_old_card():
    title = "1999 #4 Charizard PSA 10 Base Set 1st Edition"
    attrs = parse_card_title(title)
    assert attrs.year == "1999"


# ---------------------------------------------------------------------------
# Sub-grade extraction
# ---------------------------------------------------------------------------

def test_sub_grade_pristine():
    title = "CGC 10 Pristine Pikachu Japanese SV-P Promo"
    attrs = parse_card_title(title)
    assert attrs.sub_grade == "Pristine"


def test_sub_grade_gem_mint():
    title = "PSA 10 GEM MINT Charizard 4/102 Base Set"
    attrs = parse_card_title(title)
    assert attrs.sub_grade == "Gem Mint"


# ---------------------------------------------------------------------------
# Lot/bundle detection
# ---------------------------------------------------------------------------

def test_lot_detection():
    title = "Lot of 5 Pokemon PSA 10 Cards Charizard"
    attrs = parse_card_title(title)
    assert attrs.is_lot is True


def test_bundle_detection():
    title = "Pokemon PSA 10 Bundle 3 Cards Pikachu Charizard"
    attrs = parse_card_title(title)
    assert attrs.is_lot is True


def test_not_a_lot():
    title = "PSA 10 Charizard 4/102 Base Set 1st Edition"
    attrs = parse_card_title(title)
    assert attrs.is_lot is False


# ---------------------------------------------------------------------------
# Edition extraction
# ---------------------------------------------------------------------------

def test_edition_1st():
    title = "1999 #61 Rattfratz 1st Edition PSA 9 German Pokemon"
    attrs = parse_card_title(title)
    assert attrs.edition == "1st Edition"


def test_edition_shadowless():
    title = "PSA 8 Charizard 4/102 Base Set Shadowless"
    attrs = parse_card_title(title)
    assert attrs.edition == "Shadowless"


# ---------------------------------------------------------------------------
# Full ME title parsing (integration tests)
# ---------------------------------------------------------------------------

def test_me_title_articuno():
    title = "2021 #170 Full Art/Galarian Articuno V PSA 10 Sword & Shield Chilling Reign Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Galarian Articuno"
    assert attrs.variant == "V"
    assert attrs.foil_type == "Full Art"
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 10
    assert attrs.card_number == "170"
    assert attrs.set_name == "Chilling Reign"
    assert attrs.year == "2021"


def test_me_title_mewtwo_vstar():
    title = "2022 #051 Mewtwo Vstar CGC 10 Pristine Japanese Sword & Shield Vstar Universe Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Mewtwo"
    assert attrs.variant == "Vstar"
    assert attrs.grading_company == GradingCompany.CGC
    assert attrs.grade == 10
    assert attrs.sub_grade == "Pristine"
    assert attrs.language == "Japanese"
    assert attrs.card_number == "051"


def test_me_title_espeon_gx():
    title = "2019 #SV60 FULL ART/ESPEON GX PSA 10 POKEMON SUN & MOON HIDDEN FATES"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Espeon"
    assert attrs.variant == "GX"
    assert attrs.foil_type == "Full Art"
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 10
    assert attrs.card_number == "SV60"
    assert attrs.set_name == "Hidden Fates"


def test_me_title_pikachu_ex():
    title = "2024 #219 Pikachu EX PSA 9 Ssp EN-Surging Sparks Pokemon"
    attrs = parse_card_title(title)
    assert attrs.pokemon_name == "Pikachu"
    assert attrs.variant == "EX"
    assert attrs.grading_company == GradingCompany.PSA
    assert attrs.grade == 9
    assert attrs.card_number == "219"
    assert attrs.set_name == "Surging Sparks"


# ---------------------------------------------------------------------------
# ME attribute enrichment
# ---------------------------------------------------------------------------

def test_me_attributes_override():
    me_attrs = [
        {"trait_type": "Category", "value": "Pokemon"},
        {"trait_type": "Grading Company", "value": "PSA"},
        {"trait_type": "Grade", "value": "10"},
        {"trait_type": "Year", "value": "2021"},
    ]
    title_attrs = CardAttributes()
    enriched = extract_from_me_attributes(me_attrs, title_attrs)
    assert enriched.grading_company == GradingCompany.PSA
    assert enriched.grade == 10
    assert enriched.year == "2021"


def test_me_attributes_enrich_existing():
    title_attrs = CardAttributes(
        pokemon_name="Charizard",
        variant="V",
        grading_company=GradingCompany.UNKNOWN,
    )
    me_attrs = [
        {"trait_type": "Grading Company", "value": "CGC"},
        {"trait_type": "Grade", "value": "9.5"},
    ]
    enriched = extract_from_me_attributes(me_attrs, title_attrs)
    assert enriched.grading_company == GradingCompany.CGC
    assert enriched.grade == 9.5
    assert enriched.pokemon_name == "Charizard"  # Preserved from title
    assert enriched.variant == "V"  # Preserved from title


# ---------------------------------------------------------------------------
# Card number normalization
# ---------------------------------------------------------------------------

def test_normalize_card_number_leading_zeros():
    assert CardAttributes._normalize_card_number("051") == "51"
    assert CardAttributes._normalize_card_number("007") == "7"
    assert CardAttributes._normalize_card_number("#025") == "25"


def test_normalize_card_number_slash():
    assert CardAttributes._normalize_card_number("4/102") == "4"
    assert CardAttributes._normalize_card_number("170/198") == "170"


def test_normalize_card_number_prefixed():
    assert CardAttributes._normalize_card_number("SV60") == "sv60"
    assert CardAttributes._normalize_card_number("TG03") == "tg3"
    assert CardAttributes._normalize_card_number("GG10") == "gg10"
