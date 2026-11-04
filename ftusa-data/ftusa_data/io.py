"""Locating raw files and small shared helpers."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .config import COUNTRY_ALIASES, COUNTRY_ISO3, SUSPECT_COUNTRIES

# logical name -> filename suffix (FTUSA files arrive with random prefixes)
RAW_FILES = {
    "accounts": "Producer_Accounts.csv",
    "projects_full": "pprojects-full-environmental-with-acct-detail.csv",
    "projects_env": "Premium_Projects_Environmental.csv",
    "survey_header": "Survey_Response_Header.csv",
    "household_header": "Household_Survey_Header.csv",
    "survey_single": "Survey_Response_Questions_Single_Choice.csv",
    "survey_multi": "Survey_Response_Questions_Multiple_Choice.csv",
    "aps_xlsx": "APS_*.xlsm",
    "fps_xlsx": "FPS_*.xlsm",
}


def find(raw_dir: Path, key: str) -> Path:
    pattern = RAW_FILES[key]
    hits = sorted(raw_dir.glob(f"*{pattern}"))
    if not hits:
        raise FileNotFoundError(f"{key}: no file matching *{pattern} in {raw_dir}")
    if len(hits) > 1:
        print(f"  note: {key} matched {len(hits)} files, using {hits[-1].name}")
    return hits[-1]


def read_csv(raw_dir: Path, key: str) -> pd.DataFrame:
    return pd.read_csv(find(raw_dir, key), low_memory=False, dtype=str, keep_default_na=False, na_values=[""])


def norm_country(c) -> str | None:
    if c is None or (isinstance(c, float) and c != c) or str(c).strip() == "":
        return None
    c = str(c).strip()
    return COUNTRY_ALIASES.get(c, c)


def is_suspect_country(c) -> bool:
    return c in SUSPECT_COUNTRIES


def iso3(c) -> str:
    return COUNTRY_ISO3.get(c, "UNK")


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()


def stable_id(prefix: str, *parts, n: int = 10) -> str:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:n].upper()
    return f"{prefix}-{h}"


def split_list(v) -> list[str]:
    if v is None or (isinstance(v, float) and v != v) or str(v).strip() == "":
        return []
    return [x.strip() for x in str(v).split(";") if x.strip()]


def join_list(xs) -> str:
    return "|".join(xs)


def write(df: pd.DataFrame, out: Path, name: str):
    d = out / "tables" / name
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / f"{name}.csv", index=False)
    try:
        df.to_parquet(d / f"{name}.parquet", index=False)
    except ImportError:
        pass
