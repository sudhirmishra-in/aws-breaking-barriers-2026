"""Household survey tables -> producer-level summaries.

Individual answers never reach the agent. Responses are filtered for quality,
then aggregated per (account_sk, survey_year). Any percentage resting on fewer
than MIN_N valid answers is suppressed (blank), and its n is always reported.

Outputs
  survey_summary        one row per account x year, wide metrics (for producer-record)
  survey_choice_shares  long table of multi-choice shares (citable detail)
"""
from __future__ import annotations

import re

import pandas as pd

from .config import INVALID_ANSWERS, MIN_COMPLETION_PCT, MIN_N, MULTI_CHOICE_QUESTIONS, TOP_K_CHOICES
from .io import norm_country, stable_id

YESNO = {  # metric -> single-choice column
    "pct_water_conservation": "has_water_conservation_practices_code",
    "pct_water_contamination_prevention": "has_water_contamination_prevention_practices_code",
    "pct_soil_conservation": "has_soil_conservation_practices_code",
    "pct_forest_protection": "has_forest_protection_practices_code",
    "pct_fertilizer_training": "has_received_fertilizer_training_code",
    "pct_converted_natural_land": "coverted_natural_land_to_cropland_code",
    "pct_uses_red_label_pesticide": "red_pesticide_code",
    "pct_running_water": "running_water_code",
    "pct_hired_labor": "has_hired_labor_code",
}
CATEGORICAL = {  # metric -> (column, value counted, values excluded from denominator)
    "pct_harvest_decreased": ("harvest_changed_code", "It has decreased", set()),
    "pct_harvest_increased": ("harvest_changed_code", "It has increased", set()),
    "pct_harvest_unchanged": ("harvest_changed_code", "It has not changed", set()),
    "pct_no_ipm_practices": ("has_integrated_pest_management_practices_name", "I don't employ any of these practices", {"Other"}),
    "pct_drinking_water_at_home": ("water_access_distance_name", "Always available in my house", {"None of the above applies"}),
    "pct_drinking_water_over_30min": ("water_access_distance_name", "It takes more than 30 minutes", {"None of the above applies"}),
    "pct_no_drinking_water": ("water_access_distance_name", "I don't have access to drinking water", {"None of the above applies"}),
    "pct_temporary_workers": ("worker_type_name", "Temporary", set()),
}

DOCS_SUMMARY = {
    "summary_id": "Stable ID for citations (SRVSUM-...)",
    "account_sk": "FK producers (many survey accounts are not in Producer_Accounts; see in_producer_accounts)",
    "survey_year": "Year of response_date",
    "country": "Normalized country (most common in responses)",
    "survey_types": "HL (hired labor) / SPO (small producer org), pipe-separated",
    "survey_names": "Qualtrics survey names, pipe-separated (when known)",
    "survey_crops": "Crop parsed from survey names, pipe-separated",
    "n_responses": "Responses kept after quality filter",
    **{m: f"% Yes among valid Yes/No answers ({c})" for m, c in YESNO.items()},
    **{m: f"% '{v}' among valid answers to {c}" for m, (c, v, _) in CATEGORICAL.items()},
    "n_<metric>": "Valid answers behind each pct_ metric; pct is blank when n < MIN_N",
    "median_farm_area_ha": "Median farm_area_ha_nbr over responses with area > 0",
    "top_<question>": "Top choices with share, e.g. 'Climate change (41%)|...' (multi-choice; Refused/Other excluded from ranking)",
    "in_producer_accounts": "account_sk exists in Producer_Accounts.csv",
    "source": "FTUSA household survey, aggregated",
}
DOCS_SHARES = {
    "account_sk": "FK", "survey_year": "int", "question": "question_label_txt", "metric": "friendly name",
    "choice": "question_choice_txt", "n_selected": "respondents choosing it", "n_respondents": "respondents answering",
    "share": "n_selected / n_respondents (blank if n_respondents < MIN_N)",
}

KNOWN_CROPS = ["Coffee", "Cocoa", "Bananas", "Banana", "Tomatoes", "Berries", "Coconut", "Dairy", "Tuna", "Shrimp",
               "Tea", "Honey", "Sugar", "Agave", "Grapes", "Mandarines", "Aquaculture"]


def parse_survey_name(name: str) -> dict:
    toks = re.split(r"[_\s]+", str(name))
    crop = next((t for t in toks if t in KNOWN_CROPS), None)
    typ = next((t for t in toks if t in ("HL", "SPO")), None)
    yr = re.search(r"(20\d{2})", str(name))
    return {"survey_crop": crop.lower() if crop else None, "survey_type_from_name": typ,
            "survey_year_from_name": int(yr.group(1)) if yr else None}


def _valid(s: pd.Series, extra=frozenset()) -> pd.Series:
    return s.notna() & ~s.isin(INVALID_ANSWERS | set(extra))


def filter_responses(single: pd.DataFrame, header: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    h = header[["survey_response_sk", "completion_pct", "is_active_ind", "is_deleted_ind", "raw_user_language_code"]]
    s = single.merge(h, on="survey_response_sk", how="left")
    known = s.completion_pct.notna()
    comp = pd.to_numeric(s.completion_pct, errors="coerce")
    bad = known & ((comp < MIN_COMPLETION_PCT) | (s.is_active_ind != "1") | (s.is_deleted_ind != "0"))
    stats = {"responses_in": len(s), "with_header": int(known.sum()), "dropped_quality": int(bad.sum()),
             "kept": int((~bad).sum())}
    return s[~bad].copy(), stats


def build(single: pd.DataFrame, multi: pd.DataFrame, header: pd.DataFrame, household: pd.DataFrame,
          producer_accounts: set[str]):
    s, stats = filter_responses(single, header)
    meta = household[["survey_sk", "survey_name"]].copy()
    meta = pd.concat([meta, meta.survey_name.apply(parse_survey_name).apply(pd.Series)], axis=1)
    s = s.merge(meta, on="survey_sk", how="left")
    s["survey_year"] = pd.to_datetime(s.response_date, errors="coerce").dt.year.astype("Int64")
    s["survey_type"] = s.survey_type_code.fillna(s.survey_type_from_name)
    s["country"] = s.country_name.map(norm_country)
    s = s.dropna(subset=["survey_year"])
    key = ["account_sk", "survey_year"]

    rows = []
    for (acct, yr), g in s.groupby(key):
        r = {"account_sk": acct, "survey_year": int(yr), "country": g.country.mode().iat[0] if g.country.notna().any() else None,
             "survey_types": "|".join(sorted(g.survey_type.dropna().unique())),
             "survey_names": "|".join(sorted(g.survey_name.dropna().unique())),
             "survey_crops": "|".join(sorted(g.survey_crop.dropna().unique())),
             "n_responses": len(g)}
        for m, c in YESNO.items():
            v = g[c][_valid(g[c])]
            n = len(v)
            r[m] = round(100 * (v == "Yes").mean(), 1) if n >= MIN_N else None
            r[f"n_{m[4:]}"] = n
        for m, (c, val, excl) in CATEGORICAL.items():
            v = g[c][_valid(g[c], excl)]
            n = len(v)
            r[m] = round(100 * (v == val).mean(), 1) if n >= MIN_N else None
            r[f"n_{m[4:]}"] = n
        area = pd.to_numeric(g.farm_area_ha_nbr, errors="coerce")
        area = area[area > 0]
        r["median_farm_area_ha"] = round(float(area.median()), 2) if len(area) >= MIN_N else None
        rows.append(r)
    summary = pd.DataFrame(rows)

    # multi-choice shares
    kept = s[["survey_response_sk", "account_sk", "survey_year"]]
    m = multi[multi.question_label_txt.isin(MULTI_CHOICE_QUESTIONS)].drop(columns=["account_sk"]).merge(
        kept, on="survey_response_sk", how="inner")
    resp = m.groupby(key + ["question_label_txt"]).survey_response_sk.nunique().rename("n_respondents")
    sel = m.dropna(subset=["question_choice_txt"]).groupby(key + ["question_label_txt", "question_choice_txt"]) \
        .survey_response_sk.nunique().rename("n_selected")
    shares = sel.reset_index().merge(resp.reset_index(), on=key + ["question_label_txt"])
    shares["share"] = (shares.n_selected / shares.n_respondents).round(3).where(shares.n_respondents >= MIN_N)
    shares = shares.rename(columns={"question_label_txt": "question", "question_choice_txt": "choice"})
    shares["metric"] = shares.question.map(MULTI_CHOICE_QUESTIONS)
    shares = shares[list(DOCS_SHARES)].sort_values(key + ["question", "n_selected"], ascending=[True, True, True, False])

    for q, label in MULTI_CHOICE_QUESTIONS.items():
        sub = shares[(shares.question == q) & shares.share.notna() & ~shares.choice.isin({"Refused", "Other"} | INVALID_ANSWERS)]
        top = sub.groupby(key).apply(
            lambda g: "|".join(f"{c} ({round(100 * x)}%)" for c, x in zip(g.choice.head(TOP_K_CHOICES), g.share.head(TOP_K_CHOICES))),
            include_groups=False).rename(f"top_{label}")
        nresp = shares[shares.question == q].groupby(key).n_respondents.first().rename(f"n_{label}")
        summary = summary.merge(top.reset_index(), on=key, how="left").merge(nresp.reset_index(), on=key, how="left")
        summary[f"n_{label}"] = summary[f"n_{label}"].fillna(0).astype(int)

    summary["in_producer_accounts"] = summary.account_sk.isin(producer_accounts)
    summary["source"] = "FTUSA household survey, aggregated"
    summary.insert(0, "summary_id", [stable_id("SRVSUM", a, y) for a, y in zip(summary.account_sk, summary.survey_year)])
    stats.update({"summary_rows": len(summary), "survey_accounts": int(summary.account_sk.nunique()),
                  "survey_accounts_in_producer_accounts": int(summary[summary.in_producer_accounts].account_sk.nunique())})
    return summary, shares.reset_index(drop=True), stats
