"""APS / FPS workbooks -> standard_clauses.jsonl + standard_objectives.csv, and a BM25 search.

Workbook layout (as provided):
  APS_*.xlsm  'Set English'           Number | Name | Tab (module) | Farm size | Sub-Module | *_ES/_FR/... translations
              'Questions English'     header on row 3: Code | Question | Intent | Timeline* | Priority | ...
                                      | Hide/Show for Amendments | Question_ES | Intent_ES | Question_FR | ...
  FPS_*.xlsm  'Set English FPS'       Number | Name | Tab | Sub-Module | Hide/Show for Amendments
              'Questions English FPS' header on row 3: Code | Question | Intent | Timeline | ... (English only)
  Other sheets in the FPS file (#TT~..., Sheet1) are import scratch copies and are ignored.

One clause = one compliance criterion (Code, e.g. 3.1.1.d). Codes ending in
_v<TAG> are amendment variants (US, EUDR, CNVN = China/Vietnam ...). They are
kept with is_variant=True; search() returns base clauses unless asked.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

CODE = re.compile(r"^(?P<obj>\d+\.\d+\.\d+)(?:\.(?P<crit>[a-z]{1,2}))?(?:_v(?P<var>\w+))?$")
FARM_SIZE = {"SF": "small_farm", "MF": "mid_size_farm", "LF": "large_farm"}
APPLIES = {"APS": ["cooperative", "smallholder", "estate", "unknown"], "FPS": ["processing_operation"]}

DOCS = {
    "clause_id": "<STD>-<Code>, e.g. APS-3.1.1.d  (cite this)",
    "standard": "APS (Agricultural Production Standard) | FPS (Factory Production Standard)",
    "code": "Criterion code as in the workbook", "objective_number": "e.g. 3.1.1",
    "criterion": "letter(s) after the objective", "variant": "amendment tag from _v suffix, blank for base clause",
    "is_variant": "bool", "module": "Tab, e.g. 'Module 4: Biodiversity, Ecosystem Function, ...'",
    "sub_module": "Sub-Module text", "objective": "Objective name (without the 'Objective x.y.z:' prefix)",
    "farm_sizes": "APS only: SF/MF/LF the objective applies to (blank = all)",
    "question": "Criterion text (English)", "intent": "Guidance text (English)", "priority": "bool (Priority column)",
    "timeline": "Timeline / compliance year (small farm or default)",
    "hide_for_amendments": "raw", "show_for_amendments": "raw",
    "question_es": "Spanish criterion text (APS)", "intent_es": "Spanish guidance (APS)",
    "question_fr": "French criterion text (APS)", "intent_fr": "French guidance (APS)",
    "applies_to": "entity types this standard grounds, pipe-separated",
    "source_file": "workbook file name",
}


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).replace("\xa0", " ").strip()
    return s or None


def _strip_objective(name):
    return re.sub(r"^Objective\s+\d+(\.\d+)*\s*:\s*", "", name) if name else name


def parse_workbook(path: Path, standard: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    sheets = pd.ExcelFile(path).sheet_names
    set_sheet = next(s for s in sheets if s.startswith("Set English"))
    q_sheet = next(s for s in sheets if s.startswith("Questions English"))
    warnings = []

    st = pd.read_excel(path, sheet_name=set_sheet, dtype=str).dropna(subset=["Number"])
    st["Number"] = st.Number.str.strip()
    st["obj"] = st.Number.str.replace(r"_v\w+$", "", regex=True)
    has_fs = "Farm size" in st.columns
    objectives = (st[st.obj.str.count(r"\.") == 2]
                  .groupby("obj")
                  .agg(objective=("Name", lambda s: _strip_objective(_clean(s.dropna().iloc[0])) if s.notna().any() else None),
                       module=("Tab", "first"),
                       sub_module=("Sub-Module", "first"),
                       farm_sizes=("Farm size", lambda s: "|".join(sorted(s.dropna().unique()))) if has_fs else ("Tab", lambda s: ""))
                  .reset_index().rename(columns={"obj": "objective_number"}))
    objectives.insert(0, "standard", standard)

    q = pd.read_excel(path, sheet_name=q_sheet, header=None, dtype=str)
    hdr = next(i for i in range(10) if "Code" in q.iloc[i].fillna("").tolist())
    q.columns = [_clean(c) or f"col{i}" for i, c in enumerate(q.iloc[hdr])]
    q = q.iloc[hdr + 1:].dropna(subset=["Code"])
    q["Code"] = q.Code.str.strip()
    col = lambda *names: next((n for n in names if n in q.columns), None)  # noqa: E731
    c_comp = col("Compliance_Required_From", "Compliance Required From")

    rows, seen = [], {}
    obj_idx = objectives.set_index("objective_number")
    for r in q.to_dict("records"):
        m = CODE.match(r["Code"])
        if not m:
            warnings.append(f"{standard}: unparsed code {r['Code']!r}")
            continue
        code = r["Code"]
        if code in seen:
            same = seen[code]["question"] == _clean(r.get("Question"))
            warnings.append(f"{standard}: duplicate code {code} ({'identical' if same else 'DIFFERENT'} text) - kept first")
            continue
        o = obj_idx.loc[m["obj"]] if m["obj"] in obj_idx.index else None
        if o is None:
            warnings.append(f"{standard}: {code} has no objective {m['obj']} in {set_sheet}")
        rec = {
            "clause_id": f"{standard}-{code}", "standard": standard, "code": code, "objective_number": m["obj"],
            "criterion": m["crit"], "variant": m["var"], "is_variant": m["var"] is not None,
            "module": _clean(o["module"]) if o is not None else None,
            "sub_module": _clean(o["sub_module"]) if o is not None else None,
            "objective": _clean(o["objective"]) if o is not None else None,
            "farm_sizes": _clean(o["farm_sizes"]) if o is not None else None,
            "question": _clean(r.get("Question")), "intent": _clean(r.get("Intent")),
            "priority": _clean(r.get("Priority")) in ("Yes", "True"),
            "timeline": _clean(r.get(c_comp)) if c_comp else _clean(r.get("Timeline")),
            "hide_for_amendments": _clean(r.get("Hide for Amendments")),
            "show_for_amendments": _clean(r.get("Show for Amendments")),
            "question_es": _clean(r.get("Question_ES")), "intent_es": _clean(r.get("Intent_ES")),
            "question_fr": _clean(r.get("Question_FR")), "intent_fr": _clean(r.get("Intent_FR")),
            "applies_to": "|".join(APPLIES[standard]), "source_file": path.name,
        }
        seen[code] = rec
        rows.append(rec)
    return pd.DataFrame(rows)[list(DOCS)], objectives, warnings


def build(aps: Path, fps: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    a, ao, wa = parse_workbook(aps, "APS")
    f, fo, wf = parse_workbook(fps, "FPS")
    clauses = pd.concat([a, f], ignore_index=True)
    with open(out / "standard_clauses.jsonl", "w", encoding="utf-8") as fh:
        for r in clauses.to_dict("records"):
            fh.write(json.dumps({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()},
                                ensure_ascii=False) + "\n")
    pd.concat([ao, fo], ignore_index=True).to_csv(out / "standard_objectives.csv", index=False)
    return {"aps_clauses": len(a), "aps_base": int((~a.is_variant).sum()), "fps_clauses": len(f),
            "fps_base": int((~f.is_variant).sum()), "aps_objectives": len(ao), "fps_objectives": len(fo),
            "warnings": wa + wf}


# --------------------------------------------------------------------------- search
STOP = set("""a an the and or of to in on for with by is are be this that from as at it its their they them all any
must shall should may has have been not no de la el los las y o en con por para del al un una que se su sus es son
le les des et du au aux""".split())
TAG_TERMS = {
    "climate_weather": "climate change adaptation drought rain weather emissions energy agroforestry",
    "water": "water conservation irrigation wastewater sources contamination",
    "soil_land": "soil fertility erosion fertilizer compost pest integrated management agrochemicals",
    "market_price": "market price quality sales income diversification productivity",
    "labor_migration": "workers labor migrant seasonal recruitment wages housing",
    "financial_capital": "credit loans finance savings premium",
    "education": "training education school children",
    "health": "health safety medical sanitation",
    "infrastructure": "infrastructure facilities equipment",
    "biodiversity_conservation": "biodiversity forest deforestation protected ecosystem habitat waste",
    "social_community": "community needs assessment premium committee women",
}


def tokenize(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    toks = [t for t in re.findall(r"[a-z0-9]+", s) if t not in STOP and len(t) > 2]
    return [t[:-1] if len(t) > 4 and t.endswith("s") else t for t in toks]


class StandardsIndex:
    def __init__(self, clauses: list[dict], k1=1.4, b=0.75):
        self.clauses = clauses
        self.docs = [tokenize(" ".join(filter(None, [c.get("module"), c.get("objective"), c.get("objective"),
                                                      c.get("question"), c.get("question"), c.get("intent"),
                                                      c.get("question_es")]))) for c in clauses]
        self.tf = [Counter(d) for d in self.docs]
        self.avg = sum(map(len, self.docs)) / max(1, len(self.docs))
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    @classmethod
    def load(cls, path):
        return cls([json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()])

    def search(self, query="", tags=(), standard=None, entity_type=None, include_variants=False, k=5):
        q = tokenize(query + " " + " ".join(TAG_TERMS.get(t, "") for t in tags))
        out = []
        for i, c in enumerate(self.clauses):
            if standard and c["standard"] != standard:
                continue
            if entity_type and entity_type not in (c.get("applies_to") or "").split("|"):
                continue
            if c["is_variant"] and not include_variants:
                continue
            tf, dl, s = self.tf[i], len(self.docs[i]), 0.0
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s > 0:
                out.append((c, round(s, 2)))
        return sorted(out, key=lambda x: -x[1])[:k]


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Search standard_clauses.jsonl")
    ap.add_argument("jsonl")
    ap.add_argument("query")
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--entity-type")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args(argv)
    for c, s in StandardsIndex.load(a.jsonl).search(a.query, a.tags, entity_type=a.entity_type, k=a.k):
        print(f"{s:6.2f}  {c['clause_id']:18s} {(c['objective'] or '')[:70]}\n        {c['question'][:150]}")


if __name__ == "__main__":
    main()
