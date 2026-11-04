"""Producer_Accounts -> producers, certifications; projects -> regions.

producers is the session-context table: the agent's tools look up the
session's account_sk here and nowhere else.
"""
from __future__ import annotations

import hashlib

import pandas as pd

from .config import (
    COUNTRY_LANGUAGE, CROP_ALIASES, ENTITY_STANDARD, NAME_PARTS, ORG_LEVEL, PRIORITY_COUNTRIES, PRIORITY_CROPS,
    REGION_CENTROIDS, STRUCTURE_TO_ENTITY,
)
from .io import iso3, is_suspect_country, join_list, norm_country, slug, split_list

DOCS = {
    "producers": {
        "account_sk": "FTUSA account key (hashed, from source). Primary key for every table.",
        "display_id": "Short alias for demos/UI, e.g. PRD-COL-0007. Not used for joins.",
        "org_name_fictional": "Generated name, clearly marked (fictional). Source has no names.",
        "entity_type": "cooperative | smallholder | estate | processing_operation | unknown (from structure_txt)",
        "org_level": "1 = first-grade org, 2 = second-grade union, blank otherwise",
        "structure_raw": "Original structure_txt",
        "account_category": "account_category_name (Coffee, Produce, CPG, Seafood, Factory ...)",
        "crops": "Normalized product categories, pipe-separated",
        "primary_crop": "First priority crop present, else first crop",
        "country": "Normalized country name",
        "country_iso3": "ISO3 code",
        "region": "Most frequent region across this account's Premium projects (source has no account region)",
        "region_id": "Join key to regions table",
        "primary_language": "Assumed from country (es/fr/pt/en ...)",
        "certification_status": "certification_status_name from source",
        "certification_scope": "certification_scope_name from source",
        "applicable_standard": "APS for farms, FPS (Factory Production Standard) for processing_operation",
        "supply_chain_roles": "raw_supply_chain_role_txt, pipe-separated",
        "n_projects": "Premium projects for this account",
        "has_survey": "Account appears in household survey data",
        "is_priority": "Country in PRIORITY_COUNTRIES and primary crop in PRIORITY_CROPS",
    },
    "certifications": {
        "account_sk": "FK producers", "certification_status": "Authorized | Certified | Suspended | Not Authorized | Decertified",
        "certification_scope": "Producer | Factory", "applicable_standard": "APS or FPS",
        "is_in_good_standing": "status in (Authorized, Certified)",
        "source": "Producer_Accounts.csv (no dates in source; none invented)",
    },
    "regions": {
        "region_id": "ISO3-REGIONSLUG", "country": "Normalized country", "country_iso3": "ISO3",
        "region": "Region name as in project data", "n_projects": "Projects in region", "n_accounts": "Accounts in region",
        "latitude": "Approximate admin-1 centroid (priority countries only)", "longitude": "see latitude",
        "centroid_source": "'approximate, manual - verify' or blank", "is_priority_country": "bool",
    },
}


def _crop(tokens: list[str]) -> list[str]:
    out = []
    for t in tokens:
        c = CROP_ALIASES.get(t.lower(), t.lower())
        if c not in out:
            out.append(c)
    return out


def _entity(row) -> str:
    s = row.get("structure_txt")
    if isinstance(s, str) and s in STRUCTURE_TO_ENTITY:
        return STRUCTURE_TO_ENTITY[s]
    if row.get("certification_scope_name") == "Factory" or "Factory" in split_list(row.get("raw_supply_chain_role_txt")):
        return "processing_operation"
    return "unknown"


def _fictional_name(account_sk: str, lang: str, entity: str, used: set) -> str:
    kinds, words = NAME_PARTS.get(lang, NAME_PARTS["en"])
    h = int(hashlib.sha1(account_sk.encode()).hexdigest(), 16)
    base = f"{kinds[entity]} {words[h % len(words)]}"
    name, i = base, 2
    while name in used:
        name, i = f"{base} {i}", i + 1
    used.add(name)
    return f"{name} (fictional)"


def regions_from_projects(projects: pd.DataFrame) -> pd.DataFrame:
    p = projects.dropna(subset=["region"])
    g = p.groupby(["country", "region"]).agg(n_projects=("project_id", "count"), n_accounts=("account_sk", "nunique")).reset_index()
    g["country_iso3"] = g.country.map(iso3)
    g["region_id"] = g.country_iso3 + "-" + g.region.map(slug)
    cent = g.apply(lambda r: REGION_CENTROIDS.get((r.country, r.region)), axis=1)
    g["latitude"] = cent.map(lambda c: c[0] if c else None)
    g["longitude"] = cent.map(lambda c: c[1] if c else None)
    g["centroid_source"] = cent.map(lambda c: "approximate, manual - verify" if c else None)
    g["is_priority_country"] = g.country.isin(PRIORITY_COUNTRIES)
    return g[list(DOCS["regions"])].sort_values(["country", "region"]).reset_index(drop=True)


def build(accounts: pd.DataFrame, projects: pd.DataFrame, survey_accounts: set[str]):
    a = accounts.copy()
    a["country"] = a.country_name.map(norm_country)
    a["entity_type"] = a.apply(_entity, axis=1)
    a["crops_l"] = a.product_category_name.map(split_list).map(_crop)
    # no product category: fall back to the account category when it names a crop (e.g. "Coffee")
    a["crops_l"] = [c if c else _crop([ac]) if isinstance(ac, str) and ac.lower() in CROP_ALIASES else []
                    for c, ac in zip(a.crops_l, a.account_category_name)]
    a["primary_crop"] = a.crops_l.map(lambda cs: next((c for c in PRIORITY_CROPS if c in cs), cs[0] if cs else None))

    # region = mode of project regions for the account
    pr = projects.dropna(subset=["region"]).groupby("account_sk").region.agg(lambda s: s.value_counts().index[0])
    a["region"] = a.account_sk.map(pr)
    a["country_iso3"] = a.country.map(iso3)
    a["region_id"] = a.apply(lambda r: f"{r.country_iso3}-{slug(r.region)}" if isinstance(r.region, str) else None, axis=1)
    a["n_projects"] = a.account_sk.map(projects.account_sk.value_counts()).fillna(0).astype(int)
    a["has_survey"] = a.account_sk.isin(survey_accounts)
    a["primary_language"] = a.country.map(lambda c: COUNTRY_LANGUAGE.get(c, "en"))
    a["applicable_standard"] = a.entity_type.map(ENTITY_STANDARD)
    a["is_priority"] = a.country.isin(PRIORITY_COUNTRIES) & a.primary_crop.isin(PRIORITY_CROPS)
    a["org_level"] = a.structure_txt.map(ORG_LEVEL)

    a = a.sort_values(["country", "account_sk"]).reset_index(drop=True)
    a["display_id"] = "PRD-" + a.country_iso3 + "-" + (a.groupby("country_iso3").cumcount() + 1).map(lambda n: f"{n:04d}")
    used: set[str] = set()
    a["org_name_fictional"] = [_fictional_name(r.account_sk, r.primary_language, r.entity_type, used) for r in a.itertuples()]

    producers = pd.DataFrame({
        "account_sk": a.account_sk, "display_id": a.display_id, "org_name_fictional": a.org_name_fictional,
        "entity_type": a.entity_type, "org_level": a.org_level.astype("Int64"), "structure_raw": a.structure_txt,
        "account_category": a.account_category_name, "crops": a.crops_l.map(join_list), "primary_crop": a.primary_crop,
        "country": a.country, "country_iso3": a.country_iso3, "region": a.region, "region_id": a.region_id,
        "primary_language": a.primary_language, "certification_status": a.certification_status_name,
        "certification_scope": a.certification_scope_name, "applicable_standard": a.applicable_standard,
        "supply_chain_roles": a.raw_supply_chain_role_txt.map(split_list).map(join_list),
        "n_projects": a.n_projects, "has_survey": a.has_survey, "is_priority": a.is_priority,
    })
    certs = pd.DataFrame({
        "account_sk": a.account_sk, "certification_status": a.certification_status_name,
        "certification_scope": a.certification_scope_name, "applicable_standard": a.applicable_standard,
        "is_in_good_standing": a.certification_status_name.isin(["Authorized", "Certified"]),
        "source": "Producer_Accounts.csv",
    })
    warnings = []
    for r in a.itertuples():
        if is_suspect_country(r.country):
            warnings.append(f"account {r.account_sk}: suspect country {r.country!r}")
    n_unknown = int((a.entity_type == "unknown").sum())
    if n_unknown:
        warnings.append(f"{n_unknown} accounts have no structure_txt -> entity_type=unknown")
    return producers, certs, warnings
