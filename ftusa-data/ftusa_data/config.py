"""All mapping decisions in one place.

Anything marked PENDING is a judgement call that FTUSA (Impact, Research &
Learning) should confirm. Change it here; every script reads from this file.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- scope
PRIORITY_COUNTRIES = ["Colombia", "Peru", "Honduras", "Mexico", "Côte d'Ivoire"]
PRIORITY_CROPS = ["coffee", "cocoa", "banana"]

# The 11 challenge tags agreed with Impact, Research & Learning
CHALLENGE_TAGS = [
    "climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
    "education", "health", "infrastructure", "biodiversity_conservation", "social_community",
]

# --------------------------------------------------------------------------- countries
COUNTRY_ALIASES = {
    "Côte d’Ivoire": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire", "Cote D'Ivoire": "Côte d'Ivoire",
    "Bolivia (Plurinational State of)": "Bolivia", "USA": "United States",
}
# Values that look like form-dropdown defaults rather than real locations
SUSPECT_COUNTRIES = {"Åland Islands", "Afghanistan", "Andorra"}

COUNTRY_ISO3 = {
    "Colombia": "COL", "Peru": "PER", "Honduras": "HND", "Mexico": "MEX", "Côte d'Ivoire": "CIV",
    "Guatemala": "GTM", "Nicaragua": "NIC", "Ecuador": "ECU", "Brazil": "BRA", "Costa Rica": "CRI",
    "Ethiopia": "ETH", "Rwanda": "RWA", "Kenya": "KEN", "India": "IND", "Sri Lanka": "LKA", "Indonesia": "IDN",
    "Philippines": "PHL", "Vietnam": "VNM", "Thailand": "THA", "China": "CHN", "Ghana": "GHA", "Haiti": "HTI",
    "Morocco": "MAR", "Paraguay": "PRY", "Belize": "BLZ", "Bolivia": "BOL", "New Zealand": "NZL",
    "Solomon Islands": "SLB", "United States": "USA", "Chile": "CHL", "Åland Islands": "ALA",
    "Afghanistan": "AFG", "Andorra": "AND",
}

COUNTRY_LANGUAGE = {
    "Colombia": "es", "Peru": "es", "Honduras": "es", "Mexico": "es", "Guatemala": "es", "Nicaragua": "es",
    "Ecuador": "es", "Costa Rica": "es", "Paraguay": "es", "Bolivia": "es", "Chile": "es",
    "Côte d'Ivoire": "fr", "Haiti": "fr", "Morocco": "fr", "Brazil": "pt", "Indonesia": "id",
    "Vietnam": "vi", "Thailand": "th", "China": "zh",
}  # default "en"

# --------------------------------------------------------------------------- entities
# structure_txt -> entity_type
STRUCTURE_TO_ENTITY = {
    "1st Grade": "cooperative",
    "2nd Grade": "cooperative",          # second-level union; org_level=2
    "Estate": "estate",
    "Multi-Estate": "estate",
    "Independent Smallholder": "smallholder",
    "Independent Smallholder - Worker Inclusion": "smallholder",
    "Factory": "processing_operation",
}
ORG_LEVEL = {"1st Grade": 1, "2nd Grade": 2}

# Which standard grounds which entity type. FPS = Factory Production Standard (as provided).
ENTITY_STANDARD = {
    "cooperative": "APS", "smallholder": "APS", "estate": "APS",
    "processing_operation": "FPS", "unknown": "APS",
}

# product_category tokens -> normalized crop
CROP_ALIASES = {
    "coffee": "coffee", "cocoa": "cocoa", "bananas": "banana", "banana": "banana",
    "camellia sinensis tea": "tea", "tea": "tea", "cane sugar": "sugar", "sugar": "sugar",
}

# --------------------------------------------------------------------------- project tagging
# FTUSA sub-category -> (tags, pending_confirmation)
SUBCATEGORY_TAGS = {
    "Clean Water": (["water"], False),
    "Climate Change Mitigation/Adaptation (Clean Energy, Agroforestry etc.)": (["climate_weather"], False),
    "Crop Diversification": (["market_price", "soil_land"], True),           # PENDING: income resilience vs agronomy
    "Pest Management": (["soil_land"], True),                                 # PENDING: no 'crop health' tag
    "Waste Disposal / Recycling": (["biodiversity_conservation"], True),      # PENDING: no 'waste' tag in the 11
    "Waste management (Trash collection, recycling facilities etc.)": (["biodiversity_conservation", "infrastructure"], True),
    "Waste Management (trash collection, recycling facilities etc.)": (["biodiversity_conservation", "infrastructure"], True),
    "Human resources and administration/ office services": (["social_community"], True),
    "Sustainability efforts": ([], False),                                    # too broad -> keywords / LLM decide
}

# Keyword rules on the translated English text (name + description + reason + goal).
# Each hit adds the tag; the tag with most hits becomes primary when the sub-category gives none.
KEYWORD_TAGS = {
    "climate_weather": r"climat|drought|rainfall|\brain\b|\bheat\b|weather|carbon|emission|solar|renewable|clean energy|energy|agroforest|adaptation",
    "water": r"water|irrigat|wastewater|honey water|aguas mieles|\bwells\b|reservoir|catchment|aqueduct|watershed",
    "soil_land": r"\bsoil|compost|fertili[sz]|organic matter|erosion|lime\b|liming|bio-?fertili|manure|pest|disease|\brust\b|borer|fungi",
    "market_price": r"diversif|income|market|price|quality|productivity|yield",
    "labor_migration": r"worker|labou?r|migra|employee",
    "financial_capital": r"credit|loan|savings|financ",
    "education": r"training|workshop|educat|school|capacit|awareness|course",
    "health": r"health|clinic|medical|sanitation|hygien",
    "infrastructure": r"construct|build|install|equipment|road|warehouse|dryer|tank|panel|machine|facility|plant\b",
    "biodiversity_conservation": r"biodivers|reforest|forest|\btrees?\b|native species|conservation|wildlife|\bbees?\b|beekeep|apicult|recycl|waste|plastic|trash|garbage|pollut",
    "social_community": r"communit|women|youth|famil|household",
}
MAX_TAGS = 3

# --------------------------------------------------------------------------- surveys
MIN_COMPLETION_PCT = 80
MIN_N = 10            # suppress any percentage computed on fewer than MIN_N valid answers
TOP_K_CHOICES = 3
MULTI_CHOICE_QUESTIONS = {
    "harvest_change_reason_core": "harvest_change_reasons",
    "borrow_source_ms_core": "borrow_sources",
    "income_sources_ms_core": "income_sources",
    "ft_benefits_ms_core": "ft_benefits",
}
INVALID_ANSWERS = {"Refused", "Don't know", "Don't Know", "I don't know", "Don’t know", "I don't know.", ""}

# --------------------------------------------------------------------------- approximate admin-1 centroids
# (lat, lon), hand-entered approximations for the priority countries. VERIFY before use.
REGION_CENTROIDS = {
    ("Colombia", "Antioquia"): (6.70, -75.50), ("Colombia", "Caldas"): (5.30, -75.30),
    ("Colombia", "Cauca"): (2.40, -76.80), ("Colombia", "Cesar"): (9.30, -73.50),
    ("Colombia", "Huila"): (2.50, -75.50), ("Colombia", "Norte de Santander"): (8.00, -72.90),
    ("Colombia", "Risaralda"): (5.00, -75.90), ("Colombia", "Tolima"): (4.00, -75.20),
    ("Colombia", "Valle del Cauca"): (3.80, -76.50),
    ("Côte d'Ivoire", "Bas-Sassandra"): (5.30, -6.60), ("Côte d'Ivoire", "Goh-Djiboua"): (6.00, -5.60),
    ("Côte d'Ivoire", "Zanzan"): (8.50, -3.20),
    ("Honduras", "Copan"): (14.90, -88.90), ("Honduras", "Intibuca"): (14.30, -88.20),
    ("Honduras", "La Paz"): (14.10, -87.80), ("Honduras", "Lempira"): (14.40, -88.50),
    ("Honduras", "Ocotepeque"): (14.50, -89.00),
    ("Mexico", "Chiapas"): (16.50, -92.50), ("Mexico", "Guanajuato"): (21.00, -101.30),
    ("Mexico", "Jalisco"): (20.60, -103.60), ("Mexico", "Michoacan de Ocampo"): (19.20, -101.90),
    ("Mexico", "Sinaloa"): (25.00, -107.50), ("Mexico", "Sonora"): (29.30, -110.70),
    ("Mexico", "Yucatan"): (20.70, -89.10),
    ("Peru", "Amazonas"): (-5.00, -78.00), ("Peru", "Ancash"): (-9.40, -77.70),
    ("Peru", "Cajamarca"): (-6.40, -78.70), ("Peru", "Junin"): (-11.50, -75.00),
    ("Peru", "Lambayeque"): (-6.40, -79.80), ("Peru", "Pasco"): (-10.40, -75.50),
    ("Peru", "San Martin"): (-7.00, -76.70),
}

# --------------------------------------------------------------------------- fictional org names
NAME_PARTS = {
    "es": ({"cooperative": "Cooperativa", "smallholder": "Finca", "estate": "Hacienda",
            "processing_operation": "Beneficio", "unknown": "Organización"},
           ["Río Claro", "Nueva Esperanza", "Cerro Verde", "Las Palmas", "El Mirador", "Tierra Viva", "Monte Alto",
            "San Isidro", "Los Andes", "La Cumbre", "Valle Sereno", "El Progreso", "Santa Rosa", "Flor del Campo",
            "Agua Dulce", "Buena Vista", "Los Pinos", "El Roble", "La Esperanza", "Alto Mayo"]),
    "fr": ({"cooperative": "Coopérative", "smallholder": "Exploitation", "estate": "Plantation",
            "processing_operation": "Usine", "unknown": "Organisation"},
           ["Espoir", "Avenir", "Lumière", "Solidarité", "La Source", "Bel Air", "Grand Bois", "Nouvelle Terre"]),
    "en": ({"cooperative": "Cooperative", "smallholder": "Farm", "estate": "Estate",
            "processing_operation": "Processing", "unknown": "Organization"},
           ["Green Valley", "Highland", "Riverside", "Sunrise", "Hilltop", "Cedar", "Golden Field", "Blue Ridge"]),
}
