"""Symbol configuration loading, canonical traditional tarot symbolism, and cohesive image generation."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

from .config import HAS_TQDM, Config, logger, requests, retry_on_failure

if HAS_TQDM:
    from tqdm import tqdm


# ==================== CANONICAL TRADITIONAL TAROT SYMBOLS ====================
# Comprehensive registry of traditional tarot archetypal symbols across the 22 Major Arcana,
# the 4 Elemental Suits, and Court archetypes (Rider-Waite-Smith & classical esoteric tradition).

TRADITIONAL_TAROT_SYMBOLS: list[dict[str, Any]] = [
    # --- Major Arcana: 0 The Fool ---
    {
        "id": "small_white_dog",
        "name": "small white dog",
        "category": "major_arcana",
        "cards": ["The Fool"],
        "description": (
            "Loyal small white companion dog bounding playfully at the traveler's "
            "heels at the cliff precipice"
        ),
        "keywords": [
            "dog", "puppy", "hound", "canine", "companion dog",
            "small dog", "white dog", "wolf pup",
        ],
        "element": "Air",
    },
    {
        "id": "white_rose_of_purity",
        "name": "white rose of purity",
        "category": "major_arcana",
        "cards": ["The Fool"],
        "description": (
            "Pristine white rose symbolizing innocence, untamed spirit, "
            "and uncorrupted beginnings"
        ),
        "keywords": [
            "rose", "white rose", "flower", "blossom", "white flower", "pure rose",
        ],
        "element": "Air",
    },
    {
        "id": "feathered_cap_and_pack",
        "name": "feathered cap and pilgrim bundle",
        "category": "major_arcana",
        "cards": ["The Fool"],
        "description": (
            "Red-feathered cap and embroidered knapsack carried upon a wooden staff "
            "containing pure potential"
        ),
        "keywords": [
            "feather", "cap", "pack", "knapsack", "bundle", "staff",
            "pilgrim pack", "wanderer",
        ],
        "element": "Air",
    },
    {
        "id": "cliff_precipice",
        "name": "sunlit cliff precipice",
        "category": "major_arcana",
        "cards": ["The Fool"],
        "description": (
            "Dramatic mountain cliff edge opening into boundless golden morning "
            "skies and infinite horizons"
        ),
        "keywords": [
            "cliff", "precipice", "edge", "abyss", "mountain ledge", "canyon", "chasm",
        ],
        "element": "Air",
    },

    # --- Major Arcana: 1 The Magician ---
    {
        "id": "infinity_lemniscate",
        "name": "infinity lemniscate",
        "category": "major_arcana",
        "cards": ["The Magician"],
        "description": (
            "Floating golden figure-eight infinity symbol radiating divine "
            "intelligence above the head"
        ),
        "keywords": [
            "infinity", "lemniscate", "figure eight", "infinity symbol",
            "infinite halo", "eternal loop",
        ],
        "element": "Air",
    },
    {
        "id": "four_elemental_altar_tokens",
        "name": "four elemental altar tokens",
        "category": "major_arcana",
        "cards": ["The Magician"],
        "description": (
            "Table altar holding the four sacred elemental tools: wand of fire, "
            "chalice of water, sword of air, and pentacle of earth"
        ),
        "keywords": [
            "table tokens", "elemental tools", "altar tools",
            "wand cup sword pentacle", "magician tools", "four elements",
        ],
        "element": "Spirit",
    },
    {
        "id": "ouroboros_serpent_belt",
        "name": "ouroboros serpent belt",
        "category": "major_arcana",
        "cards": ["The Magician"],
        "description": (
            "Glistening serpent coiled with its tail in its mouth worn as a belt "
            "of eternity and renewal"
        ),
        "keywords": [
            "ouroboros", "snake belt", "serpent belt", "tail biting snake",
            "coiled snake", "eternal snake",
        ],
        "element": "Earth",
    },
    {
        "id": "red_roses_white_lilies",
        "name": "red roses and white lilies",
        "category": "major_arcana",
        "cards": ["The Magician"],
        "description": (
            "Garden canopy of vibrant red passion roses and pristine white wisdom "
            "lilies framing the scene"
        ),
        "keywords": [
            "roses and lilies", "garden flowers", "red roses",
            "white lilies", "floral bower", "flowers",
        ],
        "element": "Earth",
    },

    # --- Major Arcana: 2 The High Priestess ---
    {
        "id": "twin_pillars_boaz_jachin",
        "name": "twin sanctuary pillars Boaz and Jachin",
        "category": "major_arcana",
        "cards": ["The High Priestess"],
        "description": (
            "Dual black and white sanctuary pillars representing cosmic duality, "
            "balance, and temple threshold"
        ),
        "keywords": [
            "two pillars", "twin pillars", "black and white pillars",
            "boaz", "jachin", "temple pillars", "columns",
        ],
        "element": "Water",
    },
    {
        "id": "pomegranate_veil",
        "name": "pomegranate veil tapestry",
        "category": "major_arcana",
        "cards": ["The High Priestess"],
        "description": (
            "Embroidered mystical veil depicting ripe ruby pomegranates and lush palm "
            "fronds guarding the inner sanctum"
        ),
        "keywords": [
            "pomegranate", "veil", "pomegranate veil", "tapestry",
            "sanctuary curtain", "palm fronds",
        ],
        "element": "Water",
    },
    {
        "id": "crescent_moon_footstool",
        "name": "crescent moon footstool",
        "category": "major_arcana",
        "cards": ["The High Priestess"],
        "description": (
            "Luminous pearlescent silver crescent moon resting gracefully at the "
            "priestess's feet"
        ),
        "keywords": [
            "crescent moon", "moon at feet", "silver crescent",
            "lunar sliver", "moon footstool", "luna",
        ],
        "element": "Water",
    },
    {
        "id": "sacred_tora_scroll",
        "name": "sacred esoteric scroll",
        "category": "major_arcana",
        "cards": ["The High Priestess"],
        "description": (
            "Ancient parchment scroll partially concealed in the lap inscribed with "
            "sacred law and esoteric mysteries"
        ),
        "keywords": [
            "scroll", "torah", "tora", "manuscript", "papyrus",
            "sacred text", "parchment",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 3 The Empress ---
    {
        "id": "twelve_star_crown",
        "name": "twelve star celestial crown",
        "category": "major_arcana",
        "cards": ["The Empress"],
        "description": (
            "Diadem crown of twelve radiant brilliant six-pointed stars uniting the "
            "cosmic zodiac"
        ),
        "keywords": [
            "twelve stars", "star crown", "crown of stars",
            "diadem", "zodiac crown", "celestial crown",
        ],
        "element": "Earth",
    },
    {
        "id": "venus_heart_shield",
        "name": "heart shield of Venus",
        "category": "major_arcana",
        "cards": ["The Empress"],
        "description": (
            "Heart-shaped polished shield emblazoned with the sacred astrological glyph of Venus"
        ),
        "keywords": [
            "venus shield", "heart shield", "venus symbol", "shield of love", "empress shield",
        ],
        "element": "Earth",
    },
    {
        "id": "golden_wheat_field",
        "name": "golden ripe wheat field",
        "category": "major_arcana",
        "cards": ["The Empress"],
        "description": (
            "Abundant waving field of golden ripe grain and fertile wheat ears beneath "
            "radiant skies"
        ),
        "keywords": [
            "wheat", "wheat field", "grain", "harvest", "sheaf", "ripe grain", "cornfield",
        ],
        "element": "Earth",
    },
    {
        "id": "forest_waterfall_stream",
        "name": "forest waterfall and living stream",
        "category": "major_arcana",
        "cards": ["The Empress"],
        "description": (
            "Cascading crystal waterfall and winding woodland stream nurturing lush cypress trees"
        ),
        "keywords": [
            "waterfall", "river", "stream", "cypress", "forest spring", "running water",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 4 The Emperor ---
    {
        "id": "ram_head_stone_throne",
        "name": "ram carved stone cube throne",
        "category": "major_arcana",
        "cards": ["The Emperor"],
        "description": (
            "Monolithic cubic stone throne carved with sacred ram heads representing "
            "Aries, structure, and sovereignty"
        ),
        "keywords": [
            "ram throne", "ram head", "stone throne", "cube throne", "rams", "granite throne",
        ],
        "element": "Fire",
    },
    {
        "id": "ankh_scepter_and_orb",
        "name": "ankh scepter and imperial orb",
        "category": "major_arcana",
        "cards": ["The Emperor"],
        "description": (
            "Golden Egyptian ankh cruciform scepter of life held in right hand and sovereign "
            "golden orb in left"
        ),
        "keywords": [
            "ankh", "scepter", "ankh scepter", "golden orb",
            "orb", "imperial regalia", "cruciform scepter",
        ],
        "element": "Fire",
    },
    {
        "id": "rugged_red_mountains",
        "name": "rugged red mountain peaks",
        "category": "major_arcana",
        "cards": ["The Emperor"],
        "description": (
            "Imposing barren crimson and ochre craggy mountains standing as an unyielding fortress wall"
        ),
        "keywords": [
            "red mountains", "rugged peaks", "barren mountains",
            "stone mountains", "crimson crags",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 5 The Hierophant ---
    {
        "id": "papal_triple_tiara",
        "name": "papal triple crown tiara",
        "category": "major_arcana",
        "cards": ["The Hierophant"],
        "description": (
            "Three-tiered golden papal tiara crowned with a crucifix symbolizing mastery over three worlds"
        ),
        "keywords": [
            "triple crown", "papal tiara", "tiara", "pontifical crown", "three tier crown",
        ],
        "element": "Earth",
    },
    {
        "id": "crossed_golden_keys",
        "name": "crossed golden and silver keys",
        "category": "major_arcana",
        "cards": ["The Hierophant"],
        "description": (
            "Pair of crossed ornamental keys of spiritual mystery and doctrinal unlocking resting at the dais"
        ),
        "keywords": [
            "crossed keys", "keys", "golden keys", "keys of heaven", "two keys", "keys at feet",
        ],
        "element": "Earth",
    },
    {
        "id": "twin_sanctuary_acolytes",
        "name": "twin sanctuary acolytes",
        "category": "major_arcana",
        "cards": ["The Hierophant"],
        "description": (
            "Two kneeling tonsured acolytes in robes patterned with roses and lilies receiving instruction"
        ),
        "keywords": [
            "acolytes", "initiates", "monks", "twin seekers", "kneeling priests", "disciples",
        ],
        "element": "Earth",
    },

    # --- Major Arcana: 6 The Lovers ---
    {
        "id": "archangel_raphael",
        "name": "radiant Archangel Raphael",
        "category": "major_arcana",
        "cards": ["The Lovers"],
        "description": (
            "Magnificent celestial angel with outstretched violet and gold wings pouring benediction "
            "from purple clouds"
        ),
        "keywords": [
            "archangel", "raphael", "angel", "winged angel", "celestial messenger", "guardian angel",
        ],
        "element": "Air",
    },
    {
        "id": "tree_of_life_and_knowledge",
        "name": "tree of life and tree of knowledge with serpent",
        "category": "major_arcana",
        "cards": ["The Lovers"],
        "description": (
            "Twin sacred trees: one bearing twelve fiery leaves, the other "
            "bearing fruit entwined with a subtle serpent"
        ),
        "keywords": [
            "tree of life", "tree of knowledge", "serpent in tree",
            "apple tree", "snake and tree", "twin trees",
        ],
        "element": "Air",
    },

    # --- Major Arcana: 7 The Chariot ---
    {
        "id": "twin_black_and_white_sphinxes",
        "name": "twin black and white sphinxes",
        "category": "major_arcana",
        "cards": ["The Chariot"],
        "description": (
            "Duality of black and white resting sphinxes harnessed to will and "
            "focused intent pulling the war car"
        ),
        "keywords": [
            "sphinx", "sphinxes", "twin sphinxes", "black and white sphinx", "two sphinxes",
        ],
        "element": "Water",
    },
    {
        "id": "canopy_of_celestial_stars",
        "name": "canopy of celestial stars",
        "category": "major_arcana",
        "cards": ["The Chariot"],
        "description": (
            "Azure silk pavillion canopy powdered with twinkling silver and gold stars overhead"
        ),
        "keywords": [
            "star canopy", "azure canopy", "canopy of stars", "star tent", "celestial tent",
        ],
        "element": "Water",
    },
    {
        "id": "crescent_moon_pauldrons",
        "name": "crescent moon pauldrons",
        "category": "major_arcana",
        "cards": ["The Chariot"],
        "description": (
            "Polished lunar crescent shoulder pauldrons facing inward upon ornate breastplate armor"
        ),
        "keywords": [
            "crescent armor", "moon pauldrons", "lunar epaulettes", "shoulder armor", "moon shoulder",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 8 Strength ---
    {
        "id": "gentled_golden_lion",
        "name": "gentled golden lion",
        "category": "major_arcana",
        "cards": ["Strength"],
        "description": (
            "Regal golden lion peacefully closing its jaws beneath the soft, "
            "loving touch of the serene maiden"
        ),
        "keywords": ["lion", "tamed lion", "golden lion", "beast", "gentle lion", "lion jaw"],
        "element": "Fire",
    },
    {
        "id": "floral_infinity_garland",
        "name": "rose garland and infinity halo",
        "category": "major_arcana",
        "cards": ["Strength"],
        "description": (
            "Continuous woven chain garland of wild roses binding maiden and lion under a floating "
            "infinity lemniscate"
        ),
        "keywords": [
            "flower garland", "rose chain", "floral wreath", "infinity halo", "lemniscate garland",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 9 The Hermit ---
    {
        "id": "lantern_of_the_star",
        "name": "lantern of the six pointed star",
        "category": "major_arcana",
        "cards": ["The Hermit"],
        "description": (
            "Raised hexagonal brass lantern sheltering the luminous six-pointed golden Star of Truth"
        ),
        "keywords": [
            "lantern", "hermit lantern", "beacon", "star lantern", "hexagram lantern", "lamp of truth",
        ],
        "element": "Earth",
    },
    {
        "id": "pilgrim_wooden_staff",
        "name": "tall wooden pilgrim staff",
        "category": "major_arcana",
        "cards": ["The Hermit"],
        "description": (
            "Tall rustic gold-veined wooden walking staff of authority and steadfast inner guidance"
        ),
        "keywords": [
            "pilgrim staff", "walking staff", "wooden staff", "crutch", "long staff", "wand of hermit",
        ],
        "element": "Earth",
    },
    {
        "id": "hooded_grey_cloak_and_snow",
        "name": "hooded grey cloak on snowy peak",
        "category": "major_arcana",
        "cards": ["The Hermit"],
        "description": (
            "Heavy hooded monk's cloak of introspection standing alone atop a "
            "frozen snow-crested mountain peak"
        ),
        "keywords": [
            "grey cloak", "hooded cloak", "cowl", "snow peak", "solitary mountain", "monk robe",
        ],
        "element": "Earth",
    },

    # --- Major Arcana: 10 Wheel of Fortune ---
    {
        "id": "celestial_rotating_wheel",
        "name": "celestial rotating wheel with letters",
        "category": "major_arcana",
        "cards": ["Wheel of Fortune"],
        "description": (
            "Great eight-spoke cosmic wheel inscribed with TARO and Hebrew letters surrounded by "
            "alchemical symbols"
        ),
        "keywords": [
            "wheel", "cosmic wheel", "wheel of fortune", "rotating wheel", "spoked wheel", "taro wheel",
        ],
        "element": "Fire",
    },
    {
        "id": "four_winged_evangelist_beasts",
        "name": "four winged cherubic beasts with books",
        "category": "major_arcana",
        "cards": ["Wheel of Fortune", "The World"],
        "description": (
            "Four winged celestial creatures (Angel, Eagle, Lion, Bull) resting upon golden clouds "
            "reading open books"
        ),
        "keywords": [
            "four beasts", "winged creatures", "tetramorph", "cherubim",
            "angel eagle lion bull", "cloud beasts",
        ],
        "element": "Spirit",
    },
    {
        "id": "sphinx_hermanubis_typhon",
        "name": "crowning sphinx and ascending figures",
        "category": "major_arcana",
        "cards": ["Wheel of Fortune"],
        "description": (
            "Blue sphinx with upright sword perched at wheel apex, red jackal ascending and yellow "
            "serpent descending"
        ),
        "keywords": [
            "sphinx with sword", "anubis", "hermanubis", "typhon", "snake on wheel", "jackal on wheel",
        ],
        "element": "Spirit",
    },

    # --- Major Arcana: 11 Justice ---
    {
        "id": "upright_double_edged_sword",
        "name": "upright double edged steel sword",
        "category": "major_arcana",
        "cards": ["Justice"],
        "description": (
            "Pristine vertical double-edged steel sword of discernment and truth "
            "raised steadfast in right hand"
        ),
        "keywords": [
            "sword of justice", "upright sword", "justice sword",
            "steel blade", "raised sword", "double edged",
        ],
        "element": "Air",
    },
    {
        "id": "golden_scales_of_balance",
        "name": "golden scales of balance",
        "category": "major_arcana",
        "cards": ["Justice"],
        "description": (
            "Balanced twin golden pans of judgment and karmic equilibrium suspended from left fingers"
        ),
        "keywords": [
            "scales", "golden scales", "scales of balance", "balances", "twin pans", "scales of justice",
        ],
        "element": "Air",
    },
    {
        "id": "purple_sanctuary_veil_justice",
        "name": "purple veil between stone pillars",
        "category": "major_arcana",
        "cards": ["Justice"],
        "description": (
            "Rich royal purple velvet veil hung between solemn grey stone courtroom pillars"
        ),
        "keywords": [
            "purple veil", "court drape", "purple curtain", "stone pillars", "hall of justice",
        ],
        "element": "Air",
    },

    # --- Major Arcana: 12 The Hanged Man ---
    {
        "id": "living_tau_cross",
        "name": "living wooden tau cross",
        "category": "major_arcana",
        "cards": ["The Hanged Man"],
        "description": (
            "Living wooden T-shaped timber cross sprouting fresh green leaves and budding shoots"
        ),
        "keywords": [
            "living cross", "tau cross", "wooden beam", "gallows tree", "green shoots cross", "timber",
        ],
        "element": "Water",
    },
    {
        "id": "golden_illumination_halo",
        "name": "golden halo of illumination",
        "category": "major_arcana",
        "cards": ["The Hanged Man"],
        "description": (
            "Radiant glowing golden nimbus and solar aura bursting around the inverted head of serene "
            "contemplation"
        ),
        "keywords": [
            "halo", "nimbus", "golden aura", "enlightened halo", "radiance around head", "solar crown",
        ],
        "element": "Water",
    },
    {
        "id": "figure_four_inverted_legs",
        "name": "inverted figure four crossed leg",
        "category": "major_arcana",
        "cards": ["The Hanged Man"],
        "description": (
            "Serene upside-down suspension by right ankle with left leg bent behind into a sacred figure four"
        ),
        "keywords": [
            "figure four", "crossed legs", "inverted pose", "upside down pose", "suspended ankle",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 13 Death ---
    {
        "id": "white_mystic_rose_banner",
        "name": "black banner with white mystic rose",
        "category": "major_arcana",
        "cards": ["Death"],
        "description": (
            "Heavy black war banner emblazoned with five-petaled white mystic rose of life and purification"
        ),
        "keywords": [
            "white rose banner", "black flag", "mystic rose", "death banner",
            "five petal rose", "black standard",
        ],
        "element": "Water",
    },
    {
        "id": "armored_skeleton_on_white_horse",
        "name": "black armored skeleton on pale horse",
        "category": "major_arcana",
        "cards": ["Death"],
        "description": (
            "Skeletal knight in gleaming dark gothic armor mounted upon an unhurried sacred white horse"
        ),
        "keywords": [
            "armored skeleton", "skeleton knight", "pale horse", "black armor", "reaper horse", "white steed",
        ],
        "element": "Water",
    },
    {
        "id": "twin_horizon_towers_and_dawn",
        "name": "twin gateway towers with rising dawn sun",
        "category": "major_arcana",
        "cards": ["Death"],
        "description": (
            "Two distant stone monolith towers on the far horizon framing the golden immortal rising sun"
        ),
        "keywords": [
            "twin towers", "rising sun", "golden dawn", "horizon sun", "gateway towers", "immortal dawn",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 14 Temperance ---
    {
        "id": "water_pouring_between_two_chalices",
        "name": "water flowing between two golden chalices",
        "category": "major_arcana",
        "cards": ["Temperance"],
        "description": (
            "Luminous unbroken stream of living water flowing horizontally between two tilted golden vessels"
        ),
        "keywords": [
            "two chalices", "pouring water", "two urns", "flowing stream", "mixing chalices", "dual cups",
        ],
        "element": "Fire",
    },
    {
        "id": "great_feathered_angel_wings",
        "name": "great flame-tinted angel wings",
        "category": "major_arcana",
        "cards": ["Temperance"],
        "description": (
            "Towering feathered wings of the angel shimmering with sunset crimson, amber, and celestial light"
        ),
        "keywords": [
            "angel wings", "archangel wings", "feathered wings", "flame wings", "wings of temperance",
        ],
        "element": "Fire",
    },
    {
        "id": "water_and_earth_dual_stance",
        "name": "one foot in water one foot on earth",
        "category": "major_arcana",
        "cards": ["Temperance"],
        "description": (
            "Serene spiritual stance with one bare foot submerged in clear pool and other on flowering soil"
        ),
        "keywords": [
            "water and earth foot", "foot in water", "dual stance", "shoreline stance", "pool and grass",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 15 The Devil ---
    {
        "id": "baphomet_horned_satyr",
        "name": "horned Baphomet goat perched on altar",
        "category": "major_arcana",
        "cards": ["The Devil"],
        "description": (
            "Winged horned goat-deity with bat wings perched atop a dark square stone pedestal"
        ),
        "keywords": [
            "baphomet", "horned goat", "goat deity", "devil goat", "satyr", "bat wings",
        ],
        "element": "Earth",
    },
    {
        "id": "inverted_forehead_pentagram",
        "name": "inverted forehead pentagram",
        "category": "major_arcana",
        "cards": ["The Devil"],
        "description": (
            "Luminous inverted five-pointed star gleaming on the brow between goat horns"
        ),
        "keywords": [
            "inverted pentagram", "downward star", "pentagram on head", "reverse pentacle", "devil star",
        ],
        "element": "Earth",
    },
    {
        "id": "chained_captives_with_horns",
        "name": "chained horned captives on altar",
        "category": "major_arcana",
        "cards": ["The Devil"],
        "description": (
            "Male and female figures with small horns and tails loosely chained by "
            "iron neck rings to pedestal"
        ),
        "keywords": [
            "chained captives", "neck chains", "horned man and woman", "loose chains", "iron collars",
        ],
        "element": "Earth",
    },

    # --- Major Arcana: 16 The Tower ---
    {
        "id": "lightning_striking_golden_crown",
        "name": "lightning bolt shattering golden crown",
        "category": "major_arcana",
        "cards": ["The Tower"],
        "description": (
            "Violent jagged zigzag lightning bolt blasting the golden crown off the summit of the fortress"
        ),
        "keywords": [
            "lightning bolt", "lightning strike", "shattered crown", "forked lightning", "crown knocked off",
        ],
        "element": "Fire",
    },
    {
        "id": "burning_stone_fortress_tower",
        "name": "burning stone fortress tower",
        "category": "major_arcana",
        "cards": ["The Tower"],
        "description": (
            "Ancient grey stone tower on dark rock bursting with billowing yellow and red flames from windows"
        ),
        "keywords": [
            "burning tower", "crumbling tower", "stone fortress", "blazing tower", "tower on rock",
        ],
        "element": "Fire",
    },
    {
        "id": "falling_figures_into_chasm",
        "name": "figures falling headlong into abyss",
        "category": "major_arcana",
        "cards": ["The Tower"],
        "description": (
            "Two royally clad figures tumbling headlong through stormy clouds amid showers of golden sparks"
        ),
        "keywords": [
            "falling figures", "falling people", "falling into abyss",
            "tumbling bodies", "falling from tower",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 17 The Star ---
    {
        "id": "great_eight_pointed_star",
        "name": "great eight pointed golden star",
        "category": "major_arcana",
        "cards": ["The Star"],
        "description": (
            "Dominant luminous eight-pointed golden star radiant in the center of the deep indigo night sky"
        ),
        "keywords": [
            "eight pointed star", "central star", "golden star", "guiding star", "brilliant star", "sirius",
        ],
        "element": "Air",
    },
    {
        "id": "seven_surrounding_white_stars",
        "name": "seven surrounding white stars",
        "category": "major_arcana",
        "cards": ["The Star"],
        "description": (
            "Constellation of seven smaller white stars shimmering around the central beacon like Pleiades"
        ),
        "keywords": [
            "seven stars", "small stars", "star cluster", "surrounding stars", "pleiades",
        ],
        "element": "Air",
    },
    {
        "id": "dual_pitchers_pouring_water",
        "name": "dual clay pitchers pouring living water",
        "category": "major_arcana",
        "cards": ["The Star"],
        "description": (
            "Two earthenware amphorae pouring streams of crystal water: one into pool, one onto fertile soil"
        ),
        "keywords": [
            "dual pitchers", "two jugs", "pouring amphorae", "water vessels", "two pitchers", "water jugs",
        ],
        "element": "Air",
    },
    {
        "id": "sacred_ibis_in_tree",
        "name": "sacred ibis bird in grove tree",
        "category": "major_arcana",
        "cards": ["The Star"],
        "description": (
            "Sacred bird of Thoth perched alert upon a blooming acacia tree branch by the starlit pool"
        ),
        "keywords": [
            "ibis bird", "bird in tree", "sacred bird", "sacred ibis", "thoth bird",
        ],
        "element": "Air",
    },

    # --- Major Arcana: 18 The Moon ---
    {
        "id": "howling_dog_and_wolf",
        "name": "howling domesticated dog and wild wolf",
        "category": "major_arcana",
        "cards": ["The Moon"],
        "description": (
            "A domesticated dog and a wild wolf sitting side by side howling upwards at the lunar orb"
        ),
        "keywords": [
            "howling wolves", "dog and wolf", "canines howling", "twin beasts",
            "wolf and hound", "jackal and dog",
        ],
        "element": "Water",
    },
    {
        "id": "crayfish_emerging_from_deep",
        "name": "crayfish crawling from primordial water",
        "category": "major_arcana",
        "cards": ["The Moon"],
        "description": (
            "Primitive armoured crayfish or lobster crawling forth from dark depths onto winding path"
        ),
        "keywords": [
            "crayfish", "lobster", "crab", "water beast", "primordial creature", "crawfish",
        ],
        "element": "Water",
    },
    {
        "id": "twin_moon_sentry_towers",
        "name": "twin stone sentry towers framing path",
        "category": "major_arcana",
        "cards": ["The Moon"],
        "description": (
            "Two dark stone guard towers flanking a winding path leading over distant hills into unknown"
        ),
        "keywords": [
            "dual towers", "moon towers", "sentry towers", "twin monoliths", "stone towers on hills",
        ],
        "element": "Water",
    },
    {
        "id": "dual_phase_dripping_moon",
        "name": "dual phase profile moon shedding dew",
        "category": "major_arcana",
        "cards": ["The Moon"],
        "description": (
            "Enigmatic moon with serene human profile within full disk casting golden drops of moisture"
        ),
        "keywords": [
            "dual moon", "moon face", "lunar dew", "dripping moon", "moon profile", "yod drops",
        ],
        "element": "Water",
    },

    # --- Major Arcana: 19 The Sun ---
    {
        "id": "radiant_smiling_solar_face",
        "name": "radiant smiling solar disk with rays",
        "category": "major_arcana",
        "cards": ["The Sun"],
        "description": (
            "Magnificent beaming golden sun disk with gentle face radiating straight and wavy rays"
        ),
        "keywords": [
            "smiling sun", "solar face", "radiant sun", "golden sun rays", "sun disk", "solar deity",
        ],
        "element": "Fire",
    },
    {
        "id": "crowned_child_on_white_horse",
        "name": "crowned child riding gentle white horse",
        "category": "major_arcana",
        "cards": ["The Sun"],
        "description": (
            "Joyous naked crowned child riding bareback upon a gentle white steed with outstretched arms"
        ),
        "keywords": [
            "child on horse", "white horse", "innocent child", "sun child",
            "crowned toddler", "gentle steed",
        ],
        "element": "Fire",
    },
    {
        "id": "blooming_giant_sunflowers",
        "name": "blooming giant sunflowers on wall",
        "category": "major_arcana",
        "cards": ["The Sun"],
        "description": (
            "Cluster of vibrant towering golden sunflowers nodding high along a rustic grey stone garden wall"
        ),
        "keywords": [
            "sunflowers", "blooming sunflowers", "golden flowers", "sun wall", "four sunflowers",
        ],
        "element": "Fire",
    },
    {
        "id": "billowing_red_banner_of_victory",
        "name": "billowing red silk victory banner",
        "category": "major_arcana",
        "cards": ["The Sun"],
        "description": (
            "Sweeping vibrant scarlet silk standard fluttering buoyantly behind the child rider"
        ),
        "keywords": [
            "red banner", "scarlet standard", "victory banner", "red flag", "crimson silk",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 20 Judgement ---
    {
        "id": "archangel_trumpet_with_cross_banner",
        "name": "angelic golden trumpet with cross banner",
        "category": "major_arcana",
        "cards": ["Judgement"],
        "description": (
            "Archangel Gabriel sounding the great golden horn of awakening adorned with a cross banner"
        ),
        "keywords": [
            "trumpet", "golden trumpet", "angel trumpet", "horn of awakening",
            "cross banner", "horn of gabriel",
        ],
        "element": "Fire",
    },
    {
        "id": "reborn_figures_rising_from_tombs",
        "name": "reborn figures rising from floating tombs",
        "category": "major_arcana",
        "cards": ["Judgement"],
        "description": (
            "Men, women, and children standing upright in floating stone sarcophagi with joyous open arms"
        ),
        "keywords": [
            "rising figures", "open tombs", "sarcophagi", "reborn souls",
            "resurrection figures", "arms outstretched",
        ],
        "element": "Fire",
    },

    # --- Major Arcana: 21 The World ---
    {
        "id": "dancing_cosmic_maiden",
        "name": "dancing cosmic maiden with two wands",
        "category": "major_arcana",
        "cards": ["The World"],
        "description": (
            "Triumphant ecstatic dancer draped in flowing violet silk holding a "
            "white wooden wand in each hand"
        ),
        "keywords": [
            "cosmic dancer", "dancing maiden", "world dancer", "dual wands", "dancer with wands",
        ],
        "element": "Spirit",
    },
    {
        "id": "sacred_oval_laurel_wreath",
        "name": "sacred oval emerald laurel wreath",
        "category": "major_arcana",
        "cards": ["The World"],
        "description": (
            "Grand elliptical green laurel wreath encircled with red ribbon bows forming infinity ties"
        ),
        "keywords": [
            "laurel wreath", "oval wreath", "green wreath", "leaf garland", "cosmic oval", "mandorla",
        ],
        "element": "Spirit",
    },

    # --- Suit of Wands (Fire) ---
    {
        "id": "suit_flowering_wand",
        "name": "flowering wooden wand",
        "category": "suit_wands",
        "cards": ["Suit of Wands"],
        "description": (
            "Living carved wooden staff bursting with fresh green leaf buds and vital sap"
        ),
        "keywords": [
            "wand", "staff", "rod", "baton", "stave", "wooden wand", "flowering wand", "sprouting staff",
        ],
        "element": "Fire",
    },
    {
        "id": "suit_living_flame",
        "name": "sacred living flame",
        "category": "suit_wands",
        "cards": ["Suit of Wands"],
        "description": (
            "Luminous dancing flame and radiant ember sparks of creative inspiration and vitality"
        ),
        "keywords": [
            "flame", "fire", "torch", "ember", "sparks", "blaze", "fire energy",
        ],
        "element": "Fire",
    },
    {
        "id": "suit_fire_salamander",
        "name": "fire salamander",
        "category": "suit_wands",
        "cards": ["Suit of Wands"],
        "description": (
            "Ornate golden fire salamander curled with tail in mouth amidst glowing coals"
        ),
        "keywords": [
            "salamander", "fire lizard", "lizard", "ember beast", "elemental lizard",
        ],
        "element": "Fire",
    },

    # --- Suit of Cups (Water) ---
    {
        "id": "suit_golden_chalice",
        "name": "golden chalice of living water",
        "category": "suit_cups",
        "cards": ["Suit of Cups"],
        "description": (
            "Chased golden chalice brimming with crystal clear spring water and sparkling ripples"
        ),
        "keywords": [
            "chalice", "cup", "golden cup", "goblet", "grail", "vessel", "water cup",
        ],
        "element": "Water",
    },
    {
        "id": "suit_flowing_spring_water",
        "name": "flowing streams and spring water",
        "category": "suit_cups",
        "cards": ["Suit of Cups"],
        "description": (
            "Cascading clear streams, bubbling waterfalls, and undulating ripples of living spring water"
        ),
        "keywords": ["water", "stream", "waves", "spring water", "ripples", "ocean", "river"],
        "element": "Water",
    },
    {
        "id": "suit_sacred_lotus_flower",
        "name": "sacred lotus blossom",
        "category": "suit_cups",
        "cards": ["Suit of Cups"],
        "description": (
            "Pristine white and pink water lotus blossom floating serenely upon tranquil deep water"
        ),
        "keywords": [
            "lotus", "water lily", "aquatic flower", "lotus blossom", "floating bloom",
        ],
        "element": "Water",
    },

    # --- Suit of Swords (Air) ---
    {
        "id": "suit_double_edged_sword",
        "name": "double edged steel sword",
        "category": "suit_swords",
        "cards": ["Suit of Swords"],
        "description": (
            "Pristine double-edged steel blade with ornate gold crossguard pointed resolutely upward"
        ),
        "keywords": [
            "sword", "blade", "steel sword", "dagger", "broadsword", "steel blade", "rapier",
        ],
        "element": "Air",
    },
    {
        "id": "suit_storm_clouds_and_wind",
        "name": "turbulent storm clouds and sweeping wind",
        "category": "suit_swords",
        "cards": ["Suit of Swords"],
        "description": (
            "Dynamic billowing cumulus storm clouds and gusts of wind sweeping across high skies"
        ),
        "keywords": [
            "clouds", "storm clouds", "wind", "tempest", "gust", "stormy sky",
        ],
        "element": "Air",
    },
    {
        "id": "suit_soaring_falcon_or_hawk",
        "name": "soaring falcon raptor",
        "category": "suit_swords",
        "cards": ["Suit of Swords"],
        "description": (
            "Keen-eyed falcon or eagle gliding effortlessly through thin mountainous air currents"
        ),
        "keywords": [
            "falcon", "hawk", "eagle", "soaring bird", "raptor", "air bird",
        ],
        "element": "Air",
    },

    # --- Suit of Pentacles (Earth) ---
    {
        "id": "suit_golden_pentacle_coin",
        "name": "golden pentacle talisman coin",
        "category": "suit_pentacles",
        "cards": ["Suit of Pentacles"],
        "description": (
            "Solid circular golden disk deeply engraved with a sacred five-pointed pentagram star"
        ),
        "keywords": [
            "pentacle", "coin", "golden coin", "pentagram disk", "talisman", "gold disk",
        ],
        "element": "Earth",
    },
    {
        "id": "suit_grapevine_and_harvest",
        "name": "grapevine with ripe clusters and wheat",
        "category": "suit_pentacles",
        "cards": ["Suit of Pentacles"],
        "description": (
            "Climbing lush grapevines laden with deep purple fruit clusters beside golden harvest wheat"
        ),
        "keywords": [
            "grapevine", "grapes", "vine", "fruit clusters", "wheat", "harvest", "garden",
        ],
        "element": "Earth",
    },
    {
        "id": "suit_carved_stone_masonry",
        "name": "carved stone arch and foundation",
        "category": "suit_pentacles",
        "cards": ["Suit of Pentacles"],
        "description": (
            "Weathered sturdy granite stone archway and masonry foundation set firmly in garden soil"
        ),
        "keywords": [
            "stone arch", "masonry", "carved stone", "foundation stone", "castle wall",
        ],
        "element": "Earth",
    },

    # --- Court Archetypes ---
    {
        "id": "court_page_messenger",
        "name": "eager page messenger",
        "category": "court",
        "cards": ["Page of Wands", "Page of Cups", "Page of Swords", "Page of Pentacles"],
        "description": (
            "Youthful student or herald holding the suit talisman with keen curiosity and open wonder"
        ),
        "keywords": [
            "page", "messenger", "youth", "student", "herald", "seeker",
        ],
        "element": "Earth",
    },
    {
        "id": "court_questing_knight",
        "name": "questing armored knight on steed",
        "category": "court",
        "cards": ["Knight of Wands", "Knight of Cups", "Knight of Swords", "Knight of Pentacles"],
        "description": (
            "Armored knight mounted upon a noble spirited steed riding forth with mission and focus"
        ),
        "keywords": [
            "knight", "armored rider", "warhorse", "steed", "cavalier", "mounted knight",
        ],
        "element": "Fire",
    },
    {
        "id": "court_enthroned_queen",
        "name": "enthroned serene queen",
        "category": "court",
        "cards": ["Queen of Wands", "Queen of Cups", "Queen of Swords", "Queen of Pentacles"],
        "description": (
            "Dignified queen seated upon an ornate stone throne carved with nature and elemental emblems"
        ),
        "keywords": [
            "queen", "enthroned queen", "serene ruler", "consort", "reigning queen",
        ],
        "element": "Water",
    },
    {
        "id": "court_commanding_king",
        "name": "enthroned commanding king",
        "category": "court",
        "cards": ["King of Wands", "King of Cups", "King of Swords", "King of Pentacles"],
        "description": (
            "Authoritative mature monarch seated upon a grand throne holding the suit regalia of mastery"
        ),
        "keywords": [
            "king", "enthroned king", "commanding monarch", "sovereign", "reigning king",
        ],
        "element": "Air",
    },
]


# ==================== TRADITIONAL DECK REGISTRY ====================

class TraditionalDeckRegistry:
    """Registry and tools for canonical traditional tarot symbols and artist matching."""

    @classmethod
    def get_all_symbols(cls) -> list[dict[str, Any]]:
        """Return all canonical traditional tarot symbols."""
        return [s.copy() for s in TRADITIONAL_TAROT_SYMBOLS]

    @classmethod
    def get_symbol_by_id(cls, symbol_id: str) -> dict[str, Any] | None:
        """Find a canonical symbol by its ID."""
        for sym in TRADITIONAL_TAROT_SYMBOLS:
            if sym["id"] == symbol_id:
                return sym.copy()
        return None

    @classmethod
    def get_symbols_for_card(cls, card_def_or_title: str | dict[str, Any]) -> list[dict[str, Any]]:
        """
        Return the canonical traditional symbols associated with a specific card.
        Accepts either a string card title (e.g. 'The Fool', 'Three of Cups', 'Queen of Swords')
        or a card definition dictionary.
        """
        if isinstance(card_def_or_title, str):
            title = card_def_or_title.strip()
            suit = None
            rank = None
            for s in Config.SUITS:
                if f"of {s}" in title or title.startswith(s):
                    suit = s
                    break
        else:
            title = card_def_or_title.get("title", "")
            suit = card_def_or_title.get("suit")
            rank = card_def_or_title.get("rank")

        matched: list[dict[str, Any]] = []

        # 1. Exact card title match in symbol's cards list
        for sym in TRADITIONAL_TAROT_SYMBOLS:
            if title in sym.get("cards", []):
                matched.append(sym.copy())

        # 2. Suit-based match for Minor Arcana
        if suit:
            suit_cat = f"suit_{suit.lower()}"
            for sym in TRADITIONAL_TAROT_SYMBOLS:
                if sym.get("category") == suit_cat and sym not in matched:
                    matched.append(sym.copy())

            # Court card motifs
            rank_str = str(rank) if rank is not None else ""
            courts = ["Page", "Knight", "Queen", "King"]
            if any(court in title or court == rank_str for court in courts):
                for court in courts:
                    if court in title or court == rank_str:
                        for sym in TRADITIONAL_TAROT_SYMBOLS:
                            if (
                                sym.get("category") == "court"
                                and court.lower() in sym["id"]
                                and sym not in matched
                            ):
                                matched.append(sym.copy())

        return matched

    @classmethod
    def match_artist_symbols(cls, artist_symbols: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze artist-provided symbols and match them against canonical traditional tarot archetypes.

        Returns a detailed report including:
        - matched: list of artist symbols correlated to traditional archetypes with card associations
        - unmatched_artist: custom symbols provided by artist that don't match standard archetypes
        - missing_traditional: traditional tarot symbols still unfulfilled
        - coverage: summary statistics (percentages, suits covered, major arcana covered)
        """
        canonical_pool = cls.get_all_symbols()
        matched: list[dict[str, Any]] = []
        covered_canonical_ids: set[str] = set()
        unmatched_artist: list[dict[str, Any]] = []

        for artist_sym in artist_symbols:
            name = (artist_sym.get("name") or "").strip().lower()
            desc = (artist_sym.get("description") or "").strip().lower()
            best_match: dict[str, Any] | None = None
            best_score = 0.0

            for canon in canonical_pool:
                canon_name = canon["name"].lower()
                canon_id = canon["id"].lower()
                score = 0.0

                # Exact name or ID match
                if name in (canon_name, canon_id):
                    score = 1.0
                elif canon_name in name or name in canon_name:
                    score = 0.85
                else:
                    # Keyword matching
                    kw_hits = sum(
                        1 for kw in canon.get("keywords", [])
                        if re.search(rf"\b{re.escape(kw)}\b", f"{name} {desc}")
                    )
                    if kw_hits > 0:
                        score = min(0.9, 0.55 + (kw_hits * 0.15))

                if score > best_score:
                    best_score = score
                    best_match = canon

            if best_match and best_score >= 0.50:
                covered_canonical_ids.add(best_match["id"])
                matched.append({
                    "traditional_id": best_match["id"],
                    "traditional_name": best_match["name"],
                    "traditional_category": best_match["category"],
                    "associated_cards": best_match["cards"],
                    "match_score": round(best_score, 2),
                    "artist_symbol": artist_sym,
                })
            else:
                unmatched_artist.append(artist_sym)

        # Missing traditional symbols
        missing_traditional = [
            c for c in canonical_pool if c["id"] not in covered_canonical_ids
        ]

        # Calculate coverage metrics
        total_canon = len(canonical_pool)
        matched_count = len(covered_canonical_ids)
        pct = round((matched_count / total_canon) * 100.0, 1) if total_canon else 0.0

        # Suit coverage
        suits_covered = []
        for suit in Config.SUITS:
            suit_cat = f"suit_{suit.lower()}"
            if any(m["traditional_category"] == suit_cat for m in matched):
                suits_covered.append(suit)

        # Major Arcana coverage
        majors_covered = []
        for _, major_title in Config.MAJOR_ARCANA:
            if any(major_title in m["associated_cards"] for m in matched):
                majors_covered.append(major_title)

        return {
            "matched": matched,
            "matched_count": matched_count,
            "unmatched_artist": unmatched_artist,
            "unmatched_count": len(unmatched_artist),
            "missing_traditional": missing_traditional,
            "missing_count": len(missing_traditional),
            "coverage": {
                "total_traditional_symbols": total_canon,
                "provided_symbols_count": len(artist_symbols),
                "matched_traditional_count": matched_count,
                "coverage_percentage": pct,
                "suits_covered": suits_covered,
                "suits_missing": [s for s in Config.SUITS if s not in suits_covered],
                "major_arcana_covered": majors_covered,
                "major_arcana_covered_count": len(majors_covered),
            },
        }

    @classmethod
    def get_missing_symbols(
        cls,
        provided_symbols: list[dict[str, Any]],
        target_scope: str = "full",
    ) -> list[dict[str, Any]]:
        """
        Extract missing canonical traditional symbols given a list of provided symbols.
        target_scope can be 'full' (all cards), 'major' (Major only), or 'suits'.
        """
        analysis = cls.match_artist_symbols(provided_symbols)
        missing = analysis["missing_traditional"]

        if target_scope == "major":
            return [s for s in missing if s.get("category") == "major_arcana"]
        elif target_scope == "suits":
            return [s for s in missing if s.get("category", "").startswith("suit_")]
        return missing

    @classmethod
    def assign_symbols_for_card(
        cls,
        card_def: dict[str, Any],
        available_symbols: list[dict[str, Any]] | None = None,
        traditional_mode: bool = True,
        max_symbols: int = 4,
    ) -> list[str]:
        """
        Assign authentic symbols for a specific card.

        If traditional_mode is True:
        1. Identifies the canonical traditional symbols for this card.
        2. If available_symbols match those canonical archetypes, uses the artist's symbol.
        3. If traditional slots remain, fills with the traditional archetype descriptions.
        4. If extra space remains, blends in unmatched artist symbols (accent/flair symbols).

        If traditional_mode is False:
        Falls back to legacy random sampling.
        """
        if not traditional_mode:
            import random
            available = available_symbols or Config.DEFAULT_SYMBOLS
            names = [s["name"] if isinstance(s, dict) else s for s in available]
            num_pick = min(max_symbols, len(names))
            return random.sample(names, k=num_pick)

        card_symbols: list[str] = []
        canonical_symbols = cls.get_symbols_for_card(card_def)

        # Map available symbols to canonical archetypes if present
        matched_map: dict[str, dict[str, Any]] = {}
        unmatched_artist: list[dict[str, Any]] = []
        if available_symbols:
            analysis = cls.match_artist_symbols(available_symbols)
            for m in analysis["matched"]:
                matched_map[m["traditional_id"]] = m["artist_symbol"]
            unmatched_artist = analysis["unmatched_artist"]

        # Prioritize artist-provided symbols that match this card's canonical archetypes
        for canon in canonical_symbols:
            cid = canon["id"]
            if cid in matched_map:
                art_sym = matched_map[cid]
                # Use artist's symbol name + description
                desc = art_sym.get("description", art_sym.get("name", ""))
                card_symbols.append(f"{art_sym['name']} ({desc})")
            elif len(card_symbols) < max_symbols:
                # Use canonical traditional symbol description
                card_symbols.append(canon["name"])

        # If card has fewer symbols than max, sprinkle in unmatched artist symbols as creative accent
        if len(card_symbols) < max_symbols and unmatched_artist:
            for art in unmatched_artist:
                art_str = art.get("name", "")
                if art_str and art_str not in card_symbols:
                    card_symbols.append(art_str)
                    if len(card_symbols) >= max_symbols:
                        break

        # Fallback if somehow still empty
        if not card_symbols:
            card_symbols = [s["name"] for s in canonical_symbols[:max_symbols]]

        return card_symbols[:max_symbols]

    @classmethod
    def complete_deck_symbols(
        cls,
        symbols_config: dict[str, Any],
        deck_name: str,
        deck_prompt: str,
        api_key: str,
        image_model: str,
        target_scope: str = "full",
        max_missing: int | None = None,
        rate_limit: float = 1.5,
    ) -> dict[str, Any]:
        """
        Take an artist's partial symbol set, identify missing traditional symbols,
        and generate cohesive reference artwork for them using Venice AI in the artist's visual style.
        Returns the unified symbols_config containing both artist and generated symbols.
        """
        symbols_dir = os.path.join(Config.OUTPUT_DIR, deck_name, "symbols")
        os.makedirs(symbols_dir, exist_ok=True)

        provided = symbols_config.get("symbols", [])
        # Tag provided symbols as source: artist
        for s in provided:
            if "source" not in s:
                s["source"] = "artist"

        missing = cls.get_missing_symbols(provided, target_scope=target_scope)
        if max_missing and max_missing > 0:
            missing = missing[:max_missing]

        if not missing:
            logger.info("No missing traditional symbols need generation")
            return symbols_config

        style = symbols_config.get("style_prompt", "")
        if not style:
            style = (
                "intricate symbolic linework, vivid atmospheric lighting, "
                "sacred geometry, dramatic composition, masterwork tarot illustration"
            )
        if deck_prompt:
            style = f"{deck_prompt}. {style}"

        logger.info(f"Generating {len(missing)} missing traditional tarot symbols in artist style...")

        generated_symbols: list[dict[str, Any]] = []
        iterator = range(len(missing))
        if HAS_TQDM:
            iterator = tqdm(iterator, desc="Generating Traditional Symbols", unit="symbol", ncols=110)

        for i in iterator:
            sym = missing[i]
            if HAS_TQDM:
                iterator.set_description(f"Symbol: {sym['name'][:25]}")

            prompt = (
                f"A single isolated symbolic tarot icon: {sym['description']}. "
                f"Visual style: {style}. "
                "Centered iconic composition on dark neutral background, "
                "suitable as a recurring traditional tarot card symbol. No card borders, no letters, no text."
            )

            img_path = _generate_single_symbol(
                prompt=prompt,
                name=sym["name"],
                output_dir=symbols_dir,
                api_key=api_key,
                model=image_model,
                rate_limit=rate_limit,
            )

            entry = {
                "name": sym["name"],
                "description": sym["description"],
                "image": img_path,
                "source": "generated",
                "traditional_id": sym["id"],
                "category": sym["category"],
            }
            generated_symbols.append(entry)

        # Merge provided and generated symbols
        merged_symbols = list(provided) + generated_symbols
        updated_config = {
            "style_prompt": symbols_config.get("style_prompt", ""),
            "symbols": merged_symbols,
            "artist_symbol_count": len(provided),
            "generated_symbol_count": len(generated_symbols),
        }

        # Save manifest
        manifest_path = os.path.join(symbols_dir, "symbols.json")
        with open(manifest_path, "w") as f:
            json.dump(updated_config, f, indent=2)
        logger.info(f"Completed symbols saved to: {manifest_path}")

        return updated_config


# ==================== SYMBOL CONFIGURATION ====================

def load_symbols_config(symbols_file: str = None) -> dict[str, Any]:
    """
    Load symbol definitions from a JSON file.

    Expected format:
    {
      "style_prompt": "shared visual style description (optional)",
      "symbols": [
        {"name": "...", "description": "...", "image": "path/to/img.png (optional)"},
        ...
      ]
    }

    Falls back to Config.DEFAULT_SYMBOLS if no file provided or found.
    Also supports legacy custom_elements/elements_config.json for backward compatibility.
    """
    # Try explicit symbols file
    if symbols_file and os.path.exists(symbols_file):
        try:
            with open(symbols_file) as f:
                config = json.load(f)
            if "symbols" in config and isinstance(config["symbols"], list):
                logger.info(f"Loaded {len(config['symbols'])} symbols from {symbols_file}")
                return config
            else:
                logger.warning(f"Invalid symbols file (missing 'symbols' list): {symbols_file}")
        except Exception as e:
            logger.warning(f"Could not parse symbols file {symbols_file}: {e}")

    # Try legacy elements_config.json
    legacy_path = os.path.join("custom_elements", "elements_config.json")
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path) as f:
                legacy = json.load(f)
            symbols = []
            for name, filename in legacy.items():
                img_path = os.path.join("custom_elements", filename)
                symbols.append({
                    "name": name,
                    "description": name,
                    "image": img_path if os.path.exists(img_path) else None,
                    "source": "artist",
                })
            logger.info(f"Loaded {len(symbols)} symbols from legacy elements_config.json")
            return {"symbols": symbols, "style_prompt": ""}
        except Exception as e:
            logger.warning(f"Could not parse legacy config: {e}")

    # Default
    logger.info("Using default symbol definitions")
    return {"symbols": [s.copy() for s in Config.DEFAULT_SYMBOLS], "style_prompt": ""}


def generate_symbol_images(
    symbols_config: dict[str, Any],
    deck_name: str,
    deck_prompt: str,
    api_key: str,
    image_model: str,
    rate_limit: float = 1.5,
) -> dict[str, Any]:
    """
    Generate cohesive symbol reference images for every symbol that lacks an image.
    Uses a shared style prompt so all generated symbols match visually.
    Returns the updated symbols_config with image paths filled in.
    """
    if not api_key or not requests:
        logger.warning("Cannot generate symbol images: missing API key or requests library")
        return symbols_config

    symbols_dir = os.path.join(Config.OUTPUT_DIR, deck_name, "symbols")
    os.makedirs(symbols_dir, exist_ok=True)

    style = symbols_config.get("style_prompt", "")
    if not style:
        style = (
            "psychedelic neon glitch vortex style, intricate symbolic linework, "
            "electric vivid colors, dramatic cinematic lighting, high detail"
        )
    if deck_prompt:
        style = f"{deck_prompt}. {style}"

    symbols = symbols_config["symbols"]
    need_gen = [s for s in symbols if not (s.get("image") and os.path.exists(str(s["image"])))]

    if not need_gen:
        logger.info("All symbols already have images — skipping generation")
        return symbols_config

    logger.info(f"Generating {len(need_gen)} symbol images with cohesive style...")

    iterator = range(len(need_gen))
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Symbols", unit="symbol", ncols=110)

    for i in iterator:
        symbol = need_gen[i]
        if HAS_TQDM:
            iterator.set_description(f"Symbol: {symbol['name'][:25]}")

        prompt = (
            f"A single isolated symbolic element: {symbol['description']}. "
            f"Visual style: {style}. "
            "Centered composition on a dark background, "
            "suitable as a recurring tarot card symbol. No text, no borders, no frames."
        )

        img_path = _generate_single_symbol(
            prompt=prompt,
            name=symbol["name"],
            output_dir=symbols_dir,
            api_key=api_key,
            model=image_model,
            rate_limit=rate_limit,
        )

        if img_path:
            symbol["image"] = img_path
            logger.info(f"  Generated symbol: {symbol['name']}")
        else:
            logger.warning(f"  Failed to generate symbol: {symbol['name']}")

    # Save manifest so symbols can be reused later
    manifest_path = os.path.join(symbols_dir, "symbols_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(symbols_config, f, indent=2)
    logger.info(f"Symbol manifest saved: {manifest_path}")

    return symbols_config


@retry_on_failure(max_retries=2, delay=2.0)
def _generate_single_symbol(
    prompt: str,
    name: str,
    output_dir: str,
    api_key: str,
    model: str,
    rate_limit: float,
) -> str | None:
    """Generate a single symbol image via Venice."""
    if not api_key or not requests:
        return None

    time.sleep(rate_limit)

    from .venice import _build_image_request, _extract_image_b64
    resp = requests.post(
        Config.VENICE_IMAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=_build_image_request(
            model, prompt, "1024x1024", Config.DEFAULT_NEGATIVE_PROMPT,
        ),
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    b64 = _extract_image_b64(data)
    if b64:
        safe_name = name.replace(" ", "_").replace("/", "-")[:30]
        filename = f"symbol_{safe_name}.png"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64))
        return filepath
    return None
