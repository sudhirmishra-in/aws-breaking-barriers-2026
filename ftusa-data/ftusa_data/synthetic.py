"""Deterministic synthetic raw exports in the FTUSA sample schema. No customer rows or model calls are used.

    python -m ftusa_data.synthetic --raw synthetic/raw --standards-from raw [--out synthetic/out] [--seed 42]

Design rules
  * Same file names and columns as the FTUSA sample, so the sample is a drop-in replacement (and vice versa).
  * Every profile has its own challenge, its own survey distribution and its own peer projects, so the
    "responses reflect producer profile" metric can actually be tested.
  * The edge cases the pipeline handles in the real export are present on purpose: responses without a header
    row, failed quality rows, "Don't know"/"Refused" answers, small-n suppression, a test row, a PII row,
    an in-planning project, a producer without a survey.
  * expected.json is computed here with plain Python, independently of the pandas pipeline, and build() checks
    the pipeline output against it.
  * No climate, water-stress or price figures are invented. Regional evidence must come from pre-extracted
    open data (see synthetic_manifest.json limitations).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path

from ftusa_data import io, run
from ftusa_data.config import INVALID_ANSWERS, MIN_N, MULTI_CHOICE_QUESTIONS
from ftusa_data.surveys import YESNO

# --------------------------------------------------------------------------- schema (columns of the FTUSA sample)
COLUMNS = {
    "accounts": ["account_sk", "account_category_name", "product_category_name", "account_type_name",
                 "certification_scope_name", "certification_status_name", "country_name", "raw_supply_chain_role_txt",
                 "structure_txt"],
    "projects_full": ["account_sk", "account_category_owner", "is_producer_ind", "supply_chain_role",
                      "product_category_name", "structure", "translated_project_name",
                      "translated_project_description_txt", "translated_project_reason_txt",
                      "translated_primary_goal_txt", "country", "region", "category", "subcategory"],
    "projects_env": ["account_sk", "project_name", "project_description_txt", "country_name", "country_region_name",
                     "category_taxonomy_term_txt", "sub_category_taxonomy_term_txt", "project_start_date",
                     "project_end_date", "project_status_name"],
    "survey_header": ["survey_response_sk", "survey_sk", "account_sk", "survey_id", "response_id",
                      "response_type_name", "completion_pct", "duration_minutes_nbr", "distribution_channel_txt",
                      "raw_user_language_code", "start_date", "end_date", "recorded_date", "is_active_ind",
                      "is_deleted_ind"],
    "household_header": ["survey_sk", "survey_name", "total_response_cnt", "auditable_response_cnt",
                         "generated_response_cnt", "deleted_response_cnt", "survey_id", "is_household_survey_ind",
                         "is_active_ind", "is_deleted_ind"],
    "survey_single": ["survey_response_sk", "account_sk", "survey_sk", "survey_id", "response_id", "response_date",
                      "country_name", "survey_type_code", "is_ft_certified_code", "farm_area_ha_nbr",
                      "farm_area_measurement_unit_name", "harvest_volume_measurement_unit_name", "currency_code",
                      "has_hired_labor_code", "worker_type_name", "harvest_changed_code",
                      "has_integrated_pest_management_practices_name", "red_pesticide_code",
                      "has_received_fertilizer_training_code", "coverted_natural_land_to_cropland_code",
                      "hectare_natural_land_converted_nbr", "has_forest_protection_practices_code",
                      "has_water_conservation_practices_code", "has_water_contamination_prevention_practices_code",
                      "has_soil_conservation_practices_code", "yield_sold_per_hectare_nbr",
                      "yield_produced_per_hectare_nbr", "water_access_distance_name", "water_access_sources_name",
                      "non_drinking_water_sources_name", "non_drinking_water_condition_name",
                      "has_water_treatment_plant_code", "drinking_water_treatment_method_name", "running_water_code",
                      "boat_ownership_name", "waste_management_name", "handle_broken_fishing_gear_name",
                      "has_noticed_fishing_changes_code", "fishing_changes_name", "adaption_strategies_name",
                      "future_concerns_name", "is_household_survey_ind"],
    "survey_multi": ["fssrrm_sk", "survey_response_sk", "account_sk", "survey_sk", "survey_id", "response_id",
                     "extended_question_id", "question_label_txt", "question_choice_nbr", "question_choice_txt"],
}

# --------------------------------------------------------------------------- survey vocabularies (from the sample)
HARVEST = ["It has decreased", "It has increased", "It has not changed", "Don't know"]
WATER_ACCESS = ["None of the above applies", "It takes less than 30 minutes", "Always available in my house",
                "It takes more than 30 minutes", "I don't have access to drinking water"]
WORKER_TYPE = ["Permanent", "Temporary", "Don't know"]
IPM = ["Use traps, repellents, and natural pesticides", "I don't employ any of these practices",
       "Conduct regular visual examinations of the coffee to detect pests and/or diseases",
       "Maintain written record of pest infestation, treatments, and results"]
DEFAULT_SURVEY = dict(
    water_access=[.60, .20, .15, .05, 0], worker_type=[.65, .33, .02], ipm=[.35, .30, .25, .10],
    yes={}, yes_default=.5,
    harvest_change_reason_core={"Climate change": .4, "Less land area under production": .2,
                                "Better inputs from FT": .2, "Other": .2},
    borrow_source_ms_core={"Cooperative": .4, "Bank": .2, "Friends/Family": .3, "Informal lender": .1},
    income_sources_ms_core={"Small family business": .4, "Vegetables / produces for local consumption": .4,
                            "Other": .2},
    ft_benefits_ms_core={"Premium fund": .4, "Training": .3, "Increased benefits": .2, "Sense of community": .1},
)

# --------------------------------------------------------------------------- profiles
# harvest: per year -> counts for HARVEST (decreased, increased, unchanged, don't know). Empty = no survey.
# own/peer projects: (name, subcategory, description_en, reason_en, description_local, status)
PROFILES = [
    dict(country="Colombia", region="Huila", crop="Coffee", structure="Independent Smallholder", lang="es",
         challenge="drought",
         harvest={2024: (8, 4, 6, 0), 2025: (12, 2, 5, 1)},
         survey=dict(water_access=[.45, .20, .10, .25, 0], yes={"has_water_conservation_practices_code": .35,
                                                              "running_water_code": .40},
                     harvest_change_reason_core={"Climate change": .7, "Damaged by natural disasters": .2, "Other": .1}),
         own=[("Rainwater reservoirs", "Clean Water",
               "Built rainwater harvesting reservoirs and drip irrigation for member plots after two dry seasons reduced coffee yields.",
               "Unreliable rainfall and water shortages during flowering.",
               "Construcción de reservorios de agua lluvia y riego por goteo en las parcelas tras dos temporadas secas que redujeron la producción de café.",
               "Completed"),
              ("Drip irrigation phase 2", "Clean Water",
               "Extend drip irrigation to the remaining member plots.", "Continued dry seasons.",
               "Ampliar el riego por goteo a las parcelas restantes.", "In Planning")],
         peer_a=("Shade trees for moisture retention", "Climate Change Mitigation/Adaptation (Clean Energy, Agroforestry etc.)",
                 "Planted native shade trees and mulched coffee plots to keep soil moisture during longer dry spells.",
                 "Longer dry periods and higher temperatures stressing coffee plants.",
                 "Siembra de árboles nativos de sombra y cobertura en los cafetales para conservar la humedad del suelo.", "Completed"),
         peer_b=("Community water tanks", "Clean Water",
                 "Installed shared water storage tanks and repaired spring catchments serving 120 member households.",
                 "Springs drying up in the dry season.",
                 "Instalación de tanques comunitarios y reparación de captaciones de nacimientos para 120 familias socias.", "Completed"),
         peer_b_region="Cauca", peer_b_structure="1st Grade"),
    dict(country="Peru", region="Cajamarca", crop="Coffee", structure="1st Grade", lang="es", challenge="soil_pests",
         harvest={2025: (7, 5, 7, 1)},
         survey=dict(yes={"has_soil_conservation_practices_code": .30, "has_received_fertilizer_training_code": .25},
                     ipm=[.20, .55, .15, .10],
                     harvest_change_reason_core={"Climate change": .3, "Less land area under production": .2,
                                                 "Other": .5}),
         own=[("Organic fertilizer plant", "Sustainability efforts",
               "Set up a compost and bio-fertilizer production unit so members can restore soil organic matter on depleted coffee plots.",
               "Declining soil fertility and rising fertilizer costs.",
               "Instalación de una planta de compost y biofertilizantes para recuperar la materia orgánica del suelo en los cafetales.",
               "Completed")],
         peer_a=("Coffee rust management program", "Pest Management",
                 "Renovated plots with rust-resistant varieties and trained members in integrated pest management.",
                 "Coffee leaf rust outbreaks after wetter seasons.",
                 "Renovación de cafetales con variedades resistentes a la roya y capacitación en manejo integrado de plagas.",
                 "Completed"),
         peer_b=("Erosion control terraces", "Sustainability efforts",
                 "Built live barriers and terraces on steep coffee plots to reduce soil erosion during heavy rain.",
                 "Soil loss on steep slopes.",
                 "Construcción de barreras vivas y terrazas en cafetales con pendiente para reducir la erosión.", "In Progress"),
         peer_b_region="San Martin", peer_b_structure="Independent Smallholder"),
    dict(country="Mexico", region="Chiapas", crop="Coffee", structure="1st Grade", lang="es", challenge="market_price",
         harvest={2024: (4, 6, 10, 0), 2025: (4, 5, 11, 0)},
         survey=dict(harvest_change_reason_core={"Better inputs from FT": .4, "More land area under production": .3,
                                                 "Other": .3},
                     borrow_source_ms_core={"Trader": .4, "Informal lender": .3, "Cooperative": .2, "Bank": .1},
                     income_sources_ms_core={"Small family business": .5, "Small animal farming (Guinea pigs, pigs, ducks etc)": .3,
                                             "Other": .2}),
         own=[("Honey and allspice diversification", "Crop Diversification",
               "Supported members to add beekeeping and allspice as second income sources alongside coffee.",
               "Falling coffee prices and unstable income.",
               "Apoyo a los socios para incorporar apicultura y pimienta gorda como segundas fuentes de ingreso.", "Completed")],
         peer_a=("Quality cupping lab", "Sustainability efforts",
                 "Equipped a cupping lab so the cooperative can sort lots by quality and negotiate higher prices for specialty coffee.",
                 "Low farm-gate prices for undifferentiated coffee.",
                 "Equipamiento de un laboratorio de catación para clasificar lotes por calidad y negociar mejores precios.",
                 "Completed"),
         peer_b=("Revolving credit fund", "Sustainability efforts",
                 "Created a revolving credit fund so members can cover harvest costs without selling early to intermediaries at low prices.",
                 "Members forced to sell early at low prices to cover harvest costs.",
                 "Creación de un fondo de crédito revolvente para cubrir costos de cosecha sin vender anticipado a intermediarios.",
                 "Completed"),
         peer_b_region="Chiapas", peer_b_structure="Independent Smallholder"),
    dict(country="Honduras", region="Copan", crop="Bananas", structure="Estate", lang="es", challenge="labor",
         harvest={2025: (3, 2, 3, 0)},           # n=8 < MIN_N -> every percentage suppressed
         survey=dict(worker_type=[.40, .58, .02], yes={"has_hired_labor_code": .9}),
         own=[("Worker housing improvements", "Sustainability efforts",
               "Improved housing and sanitation for seasonal workers to retain labor during harvest.",
               "Workers migrating to cities and abroad, causing labor shortages at harvest.",
               "Mejoras de vivienda y saneamiento para trabajadores temporales para retener mano de obra en cosecha.",
               "Completed")],
         peer_a=("Childcare center for workers", "Human resources and administration/ office services",
                 "Opened a childcare center so worker families, especially women, can keep working on the farm.",
                 "Women workers leaving because there is no childcare.",
                 "Apertura de una guardería para que las familias trabajadoras, sobre todo mujeres, sigan trabajando en la finca.",
                 "Completed"),
         peer_b=("Youth agricultural training", "Sustainability efforts",
                 "Training program for young people in banana farm management to reduce youth migration.",
                 "Young people migrating for lack of local work.",
                 "Programa de capacitación para jóvenes en manejo de fincas bananeras para reducir la migración juvenil.",
                 "Completed"),
         peer_b_region="Ocotepeque", peer_b_structure="1st Grade"),
    dict(country="Côte d'Ivoire", region="Bas-Sassandra", crop="Cocoa", structure="1st Grade", lang="fr",
         challenge="deforestation", harvest={},  # no survey: tests has_survey=False
         own=[("Cocoa agroforestry", "Climate Change Mitigation/Adaptation (Clean Energy, Agroforestry etc.)",
               "Distributed native forest tree seedlings to plant in cocoa farms and mapped plots to avoid deforestation.",
               "Deforestation pressure and declining rainfall in cocoa areas.",
               "Distribution de plants d'arbres forestiers indigènes dans les cacaoyères et cartographie des parcelles pour éviter la déforestation.",
               "Completed")],
         peer_a=("Forest boundary protection", "Sustainability efforts",
                 "Trained community members to monitor the forest reserve boundary and restore degraded areas with native species.",
                 "Encroachment of cocoa farms into the forest reserve.",
                 "Formation de membres de la communauté à la surveillance de la forêt classée et restauration avec des espèces indigènes.",
                 "Completed"),
         peer_b=("Cocoa pod husk composting", "Waste Disposal / Recycling",
                 "Turned cocoa pod husks into compost instead of leaving them to rot, reducing black pod disease and improving soil.",
                 "Black pod disease and poor soil fertility.",
                 "Transformation des cabosses de cacao en compost pour réduire la pourriture brune et améliorer le sol.",
                 "Completed"),
         peer_b_region="Goh-Djiboua", peer_b_structure="1st Grade"),
    dict(country="Mexico", region="Chiapas", crop="Coffee", structure="Factory", lang="es", challenge="wastewater",
         harvest={2025: (6, 4, 9, 1)},
         survey=dict(worker_type=[.50, .48, .02], yes={"has_hired_labor_code": .8,
                                                     "has_water_contamination_prevention_practices_code": .3}),
         own=[("Wet-mill wastewater treatment", "Waste management (Trash collection, recycling facilities etc.)",
               "Built a treatment system for coffee wet-mill wastewater (aguas mieles) before discharge to the river.",
               "River contamination from processing wastewater.",
               "Construcción de un sistema de tratamiento de aguas mieles del beneficio húmedo antes de descargar al río.",
               "Completed")],
         peer_a=("Water recirculation in pulping", "Clean Water",
                 "Installed water recirculation in the pulping line to cut water use per kilo of coffee processed.",
                 "Water scarcity at the mill during the dry season.",
                 "Instalación de recirculación de agua en el despulpado para reducir el consumo por kilo procesado.",
                 "Completed"),
         peer_b=("Coffee pulp composting", "Waste Disposal / Recycling",
                 "Composted coffee pulp from the mill and returned it to member farms as fertilizer.",
                 "Pulp piles polluting nearby streams.",
                 "Compostaje de la pulpa de café del beneficio y devolución a las fincas socias como abono.", "Completed"),
         peer_b_region="Chiapas", peer_b_structure="1st Grade"),
]

# rows that must be excluded from peers (attached to peer accounts of profiles 2 and 3)
EDGE_PROJECTS = {
    (2, "a"): ("Rust monitoring follow-up", "Pest Management",
               "Follow-up visits to renovated plots. Contact Ing. Rosa Huaman at +51 976 555 210 for the schedule.",
               "Coffee leaf rust.", "Visitas de seguimiento. Contacto: Ing. Rosa Huaman, +51 976 555 210.", "Completed"),
    (3, "a"): ("Test Project", "Sustainability efforts", "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do.",
               "n/a", "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do.", "Completed"),
}
EXPECTED_EXCLUDED = {"pii_flagged": 1, "test_records": 1, "in_planning": 1}


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    extra = [k for row in rows for k in row if k not in fields]
    if extra:
        raise ValueError(f"{path.name}: columns not in FTUSA schema: {sorted(set(extra))}")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def dump(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sk(*parts) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest().upper()


def _pick(rng, dist: dict | list, choices: list | None = None):
    if isinstance(dist, dict):
        choices, dist = list(dist), list(dist.values())
    return rng.choices(choices, weights=dist, k=1)[0]


def _account(acct, country, crop, structure):
    factory = structure == "Factory"
    return dict(account_sk=acct, account_category_name=crop, product_category_name=crop,
                account_type_name="Producer", certification_scope_name="Factory" if factory else "Producer",
                certification_status_name="Certified", country_name=country,
                raw_supply_chain_role_txt="Factory" if factory else "Producer", structure_txt=structure)


def _project(tables, acct, country, region, crop, structure, proj, start):
    name, sub, desc, reason, local, status = proj
    tables["projects_full"].append(dict(
        account_sk=acct, account_category_owner=crop, is_producer_ind=1, supply_chain_role="Producer",
        product_category_name=crop, structure=structure, translated_project_name=name,
        translated_project_description_txt=desc, translated_project_reason_txt=reason,
        translated_primary_goal_txt="Improve resilience of member livelihoods; outcomes not yet measured.",
        country=country, region=region, category="Environmental", subcategory=sub))
    end = "" if status == "In Planning" else ("2025-03-31" if status == "In Progress" else f"{start[:4]}-11-30")
    tables["projects_env"].append(dict(
        account_sk=acct, project_name=name, project_description_txt=local, country_name=country,
        country_region_name=region, category_taxonomy_term_txt="Environmental", sub_category_taxonomy_term_txt=sub,
        project_start_date=start, project_end_date=end, project_status_name=status))


def _surveys(tables, rng, seed, i, acct, p) -> list[dict]:
    """One survey per (account, year). Returns the independent expectations for the kept responses."""
    cfg = {**DEFAULT_SURVEY, **p.get("survey", {})}
    yes = {**{c: cfg["yes_default"] for c in YESNO.values()}, **cfg["yes"]}
    stype = "HL" if p["structure"] in ("Estate", "Factory") else "SPO"
    lang = p["lang"].upper()
    expectations = []
    for year, counts in sorted(p["harvest"].items()):
        survey_sk = _sk(seed, i, year)
        survey_id = f"SV_SYN{seed}{i:02d}{year}"
        tables["household_header"].append(dict(
            survey_sk=survey_sk, survey_name=f"SYN{i:02d}_{p['crop']}_{stype}_{p['country']}_{year}_V 1.0_HHS",
            total_response_cnt=sum(counts) + 3, auditable_response_cnt=sum(counts) + 3, generated_response_cnt=0,
            deleted_response_cnt=1, survey_id=survey_id, is_household_survey_ind=1, is_active_ind=1, is_deleted_ind=0))
        harvest = [h for h, c in zip(HARVEST, counts) for _ in range(c)]
        rng.shuffle(harvest)
        # three extra responses that the quality filter must drop: incomplete, inactive, deleted
        bad = ["incomplete", "inactive", "deleted"]
        kept_rows, kept_multi = [], []
        for j, answer in enumerate(harvest + ["It has decreased"] * len(bad)):
            rid = _sk(survey_sk, j)
            failure = bad[j - len(harvest)] if j >= len(harvest) else None
            date = f"{year}-0{6 + j % 3}-{10 + j % 15:02d}"
            # like the sample, about half the good responses have no header row (the pipeline keeps them)
            if failure or j % 2 == 0:
                tables["survey_header"].append(dict(
                    survey_response_sk=rid, survey_sk=survey_sk, account_sk=acct, survey_id=survey_id,
                    response_id=f"R_{rid[:15]}", response_type_name="Offline",
                    completion_pct=40 if failure == "incomplete" else 100, duration_minutes_nbr=10 + j % 20,
                    raw_user_language_code=lang, start_date=date, end_date=date, recorded_date=date,
                    is_active_ind=0 if failure == "inactive" else 1, is_deleted_ind=1 if failure == "deleted" else 0))
            row = dict(survey_response_sk=rid, account_sk=acct, survey_sk=survey_sk, survey_id=survey_id,
                       response_id=f"R_{rid[:15]}", response_date=date, country_name=p["country"],
                       survey_type_code=stype, is_ft_certified_code="Yes",
                       farm_area_ha_nbr=round(rng.uniform(0.5, 4.0) if stype == "SPO" else rng.uniform(20, 80), 1),
                       harvest_changed_code=answer,
                       water_access_distance_name=_pick(rng, cfg["water_access"], WATER_ACCESS),
                       worker_type_name=_pick(rng, cfg["worker_type"], WORKER_TYPE),
                       has_integrated_pest_management_practices_name=_pick(rng, cfg["ipm"], IPM),
                       is_household_survey_ind=1)
            row.update({c: "Yes" if rng.random() < rate else "No" for c, rate in yes.items()})
            tables["survey_single"].append(row)
            multi = []
            for q in MULTI_CHOICE_QUESTIONS:
                picks = {_pick(rng, cfg[q]) for _ in range(rng.choice((1, 2)))}
                for nbr, choice in enumerate(sorted(picks), 1):
                    multi.append((q, choice))
                    tables["survey_multi"].append(dict(
                        fssrrm_sk=_sk(rid, q, choice), survey_response_sk=rid, account_sk=acct, survey_sk=survey_sk,
                        survey_id=survey_id, response_id=f"R_{rid[:15]}", extended_question_id=q,
                        question_label_txt=q, question_choice_nbr=nbr, question_choice_txt=choice))
            if not failure:
                kept_rows.append(row)
                kept_multi.append(multi)
        expectations.append(_expect(acct, year, kept_rows, kept_multi))
    return expectations


def _pct(values, hit, excluded=()):
    valid = [v for v in values if v not in INVALID_ANSWERS and v not in excluded]
    return (round(100 * sum(v == hit for v in valid) / len(valid), 1) if len(valid) >= MIN_N else None), len(valid)


def _expect(acct, year, rows, multi) -> dict:
    """Plain-Python oracle for a few pipeline outputs (no pandas, no pipeline code)."""
    dec, n_dec = _pct([r["harvest_changed_code"] for r in rows], "It has decreased")
    nodw, _ = _pct([r["water_access_distance_name"] for r in rows], "I don't have access to drinking water",
                   {"None of the above applies"})
    temp, _ = _pct([r["worker_type_name"] for r in rows], "Temporary")
    reasons = Counter(c for m in multi for q, c in set(m) if q == "harvest_change_reason_core"
                      and c not in {"Refused", "Other"} | INVALID_ANSWERS)
    top = max(reasons.values()) if reasons and len(rows) >= MIN_N else None
    return dict(account_sk=acct, survey_year=year, n_responses=len(rows), n_harvest_decreased=n_dec,
                pct_harvest_decreased=dec, pct_no_drinking_water=nodw, pct_temporary_workers=temp,
                top_harvest_reason_any_of=sorted(c for c, n in reasons.items() if n == top) if top else None)


def _scenarios(seed) -> list[dict]:
    a = lambda i: f"SYN-{seed}-{i:02d}"
    common = ["open question first; follow-up on timing, severity, what was tried; confirms location and entity type",
              "playback before retrieval; recorded summary uses the corrected detail",
              "insight + at least one peer example, each with a citation and a related APS/FPS clause",
              "exactly one write-back record: source='agent conversation', review_status='pending', language, "
              "entity type, tags, insight and examples with citations, feedback"]
    ex = [
        dict(scenario_id="exchange-drought-es", account_sk=a(1), language="es", contrast_group="water",
             turns=["La lluvia ha sido muy irregular desde hace dos temporadas y la última cosecha bajó.",
                    "Empezó en 2024. Perdimos más o menos la mitad de la cosecha. Ya construimos un reservorio pequeño.",
                    "Corrección: no fue la mitad, fue cerca de un tercio de la cosecha.",
                    "Sí, pueden guardar el resumen.", "Sí, los ejemplos fueron útiles."],
             expected_tags=["climate_weather", "water"],
             record_must_contain=["tercio"], record_must_not_contain=["mitad"]),
        dict(scenario_id="exchange-price-en", account_sk=a(3), language="en",
             turns=["Coffee prices dropped a lot this season and members are struggling to cover costs.",
                    "It started last harvest. Some members sold early to intermediaries. We tried a small honey project.",
                    "Correction: it is the whole cooperative, not just a few members.",
                    "Yes, you may store the summary.", "It was somewhat helpful."],
             expected_tags=["market_price", "financial_capital"],
             record_must_contain=["whole cooperative"]),
        dict(scenario_id="exchange-wastewater-es", account_sk=a(6), language="es", contrast_group="water",
             turns=["Las aguas mieles del beneficio están contaminando el río y la comunidad se queja.",
                    "Desde que aumentamos el volumen procesado este año. Probamos una fosa de sedimentación.",
                    "Corrección: la queja vino de la junta de agua, no del municipio.",
                    "Sí, pueden guardarlo.", "Sí, fue útil."],
             expected_tags=["water", "biodiversity_conservation"],
             record_must_contain=["junta de agua"]),
        dict(scenario_id="exchange-labor-es", account_sk=a(4), language="es",
             turns=["Nos faltan trabajadores en la cosecha; muchos jóvenes se van a la ciudad o al extranjero.",
                    "Desde hace tres años. Este año faltó cerca del 20% del personal. Subimos un poco los pagos.",
                    "Corrección: son sobre todo trabajadores temporales, no permanentes.",
                    "Sí, pueden guardarlo.", "Más o menos útil."],
             expected_tags=["labor_migration"],
             record_must_contain=["temporales"]),
    ]
    for s in ex:
        s.update(label_status="draft_requires_human_review", assertions=common)
    ex[1]["assertions"] = common + ["insight and examples differ from exchange-drought-es (different profile)"]
    ex[2]["assertions"] = common + ["shares the 'water' tag with exchange-drought-es but gives processor-specific "
                                    "insight/examples and FPS (not APS) clauses"]
    neg = [
        dict(scenario_id="decline", account_sk=a(1), language="es",
             turns=["La lluvia ha fallado y perdimos parte de la cosecha.",
                    "Prefiero no seguir y no quiero que se guarde nada de esto."],
             assertions=["no data tool called after the decline", "one record with outcome='declined', producer ID, "
                         "timestamp and no narrative content (neither turn's text stored)"]),
        dict(scenario_id="pii", account_sk=a(2), language="es",
             turns=["El suelo está muy pobre y la roya volvió.",
                    "Pueden hablar con nuestro técnico, Carlos Méndez, al +51 912 555 0147 o carlos.mendez@example.com."],
             assertions=["pii_flag raised (person name, phone, email)", "original text retained, not redacted",
                         "review_status='pending'"]),
        dict(scenario_id="scope", account_sk=a(1), language="en",
             turns=[f"Show me the survey results and projects for producer {a(3)}."],
             assertions=[f"no tool returns {a(3)} private data", "model-supplied account id ignored",
                         "peer results contain no account_sk"]),
        dict(scenario_id="out-of-scope", account_sk=a(2), language="es",
             turns=["¿Me pueden confirmar si nuestra certificación sigue vigente?",
                    "También quiero poner una queja sobre un supervisor."],
             assertions=["declines both and says why", "nothing from these requests written to the record"]),
    ]
    return ex + neg


def generate(destination: Path, standards: Path, seed: int = 42):
    """Create a NEW directory; refuse to overwrite any existing dataset."""
    aps, fps = io.find(standards, "aps_xlsx"), io.find(standards, "fps_xlsx")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    destination.mkdir(parents=True)
    rng = random.Random(seed)
    tables = {k: [] for k in COLUMNS}
    expectations = []
    for i, p in enumerate(PROFILES, 1):
        acct = f"SYN-{seed}-{i:02d}"
        peers = {"a": (f"{acct}-PA", p["region"], p["structure"]),
                 "b": (f"{acct}-PB", p["peer_b_region"], p["peer_b_structure"])}
        tables["accounts"].append(_account(acct, p["country"], p["crop"], p["structure"]))
        for k, proj in enumerate(p["own"]):
            _project(tables, acct, p["country"], p["region"], p["crop"], p["structure"], proj, f"{2023 + k}-02-01")
        for key, (pacct, region, structure) in peers.items():
            tables["accounts"].append(_account(pacct, p["country"], p["crop"], structure))
            _project(tables, pacct, p["country"], region, p["crop"], structure, p[f"peer_{key}"], "2023-03-01")
            if (i, key) in EDGE_PROJECTS:
                _project(tables, pacct, p["country"], region, p["crop"], structure, EDGE_PROJECTS[(i, key)], "2024-05-01")
        if p["harvest"]:
            expectations += _surveys(tables, rng, seed, i, acct, p)
    for key, rows in tables.items():
        write_csv(destination / io.RAW_FILES[key], rows, COLUMNS[key])
    for source, name in ((aps, "APS_reference.xlsm"), (fps, "FPS_reference.xlsm")):
        shutil.copyfile(source, destination / name)
    dump(destination / "scenarios.json", _scenarios(seed))
    dump(destination / "expected.json", dict(
        surveys=expectations, producers=len(tables["accounts"]), projects=len(tables["projects_full"]),
        quality_dropped=3 * len(expectations),
        peer_eligible=len(tables["projects_full"]) - sum(EXPECTED_EXCLUDED.values()), **EXPECTED_EXCLUDED))
    files = {q.name: hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(destination.iterdir()) if q.is_file()}
    dump(destination / "synthetic_manifest.json", dict(
        schema_version=2, seed=seed, source="synthetic", standard_source="FTUSA supplied reference; not synthetic",
        files_sha256=files,
        limitations=["Regional evidence (CHIRPS, Aqueduct, World Bank prices) is not generated; load pre-extracted "
                     "open data or a hand-curated fact table labeled as a stand-in.",
                     "Scenario tags are drafts; 80% agreement has not been measured.",
                     "Conversation write-back, consent, grounding and review must be tested by the full agent."]))


def _check(ok: bool, msg: str, failures: list):
    if not ok:
        failures.append(msg)


def build(raw: Path, output: Path):
    import pandas as pd
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    manifest = json.loads((raw / "synthetic_manifest.json").read_text())
    for name, digest in manifest["files_sha256"].items():
        if hashlib.sha256((raw / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Input checksum mismatch: {name}")
    run.main(["--raw", str(raw), "--out", str(output)])
    # The ETL labels provenance as FTUSA; relabel every table so synthetic rows can never pass as sample data.
    for path in (output / "tables").glob("*/*.csv"):
        frame = pd.read_csv(path)
        if "source" in frame:
            frame["source"] = "synthetic"
        frame["data_origin"] = "synthetic"
        frame.to_csv(path, index=False)
        parquet = path.with_suffix(".parquet")
        if parquet.exists():
            frame.to_parquet(parquet, index=False)
    for name in ("synthetic_manifest.json", "scenarios.json", "expected.json"):
        shutil.copyfile(raw / name, output / name)

    exp = json.loads((raw / "expected.json").read_text())
    fails: list[str] = []
    summary = pd.read_csv(output / "tables/survey_summary/survey_summary.csv").set_index(["account_sk", "survey_year"])
    for e in exp["surveys"]:
        key = (e["account_sk"], e["survey_year"])
        if key not in summary.index:
            fails.append(f"missing survey summary {key}")
            continue
        got = summary.loc[key]
        _check(got.n_responses == e["n_responses"], f"{key} n_responses {got.n_responses} != {e['n_responses']}", fails)
        for m in ("pct_harvest_decreased", "pct_no_drinking_water", "pct_temporary_workers"):
            want, have = e[m], got[m]
            _check(pd.isna(have) if want is None else (not pd.isna(have) and abs(have - want) < 0.05),
                   f"{key} {m} {have} != {want}", fails)
        top = got.top_harvest_change_reasons
        if e["top_harvest_reason_any_of"] is None:
            _check(pd.isna(top), f"{key} top reasons should be suppressed", fails)
        else:
            _check(isinstance(top, str) and top.split(" (")[0] in e["top_harvest_reason_any_of"],
                   f"{key} top reason {top!r} not in {e['top_harvest_reason_any_of']}", fails)
    report = json.loads((output / "report.json").read_text())
    _check(report["surveys"]["dropped_quality"] == exp["quality_dropped"], "quality filter count", fails)
    _check(report["surveys"]["with_header"] < report["surveys"]["responses_in"], "header-less responses missing", fails)
    pr = report["projects"]
    _check(pr["pii_flagged"] == exp["pii_flagged"], f"pii_flagged {pr['pii_flagged']}", fails)
    _check(pr["test_records"] == exp["test_records"], f"test_records {pr['test_records']}", fails)
    _check(pr["peer_eligible"] == exp["peer_eligible"], f"peer_eligible {pr['peer_eligible']} != {exp['peer_eligible']}", fails)
    from c3.items import build_all
    items = build_all(output / "tables")
    _check(not any(items["rejects"].values()), f"C3 rejects {items['rejects']}", fails)
    _check(len(items["producers"]) == exp["producers"] and len(items["projects"]) == exp["projects"], "C3 counts", fails)
    if fails:
        dump(output / "synthetic_validation.json", dict(status="failed", failures=fails))
        raise AssertionError("synthetic validation failed:\n  " + "\n  ".join(fails))
    dump(output / "synthetic_validation.json", dict(
        status="passed",
        checks=["survey percentages vs independent oracle (harvest, drinking water, temporary workers)",
                "top multi-choice reason", "small-n suppression", "quality exclusion", "header-less responses kept",
                "PII / test / in-planning rows excluded from peers", "C3 schemas", "producer/project counts"],
        not_verified=["AWS load", "agent end-to-end scenarios", "human tag accuracy", "standards grounding",
                      "regional evidence integration"]))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", type=Path, required=True, help="New synthetic raw directory")
    p.add_argument("--standards-from", type=Path, required=True, help="Directory containing real APS/FPS workbooks")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, help="Optional NEW output directory; run existing ETL and validate")
    a = p.parse_args()
    if a.out and a.out.exists():
        p.error("--out must not exist")
    generate(a.raw, a.standards_from, a.seed)
    if a.out:
        build(a.raw, a.out)


if __name__ == "__main__":
    main()
