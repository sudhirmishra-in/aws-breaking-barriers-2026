"""Assign the 11 challenge tags to Premium projects.

Layer 1  sub-category rule (config.SUBCATEGORY_TAGS)
Layer 2  keyword rules on translated text (config.KEYWORD_TAGS) add secondary tags,
         and pick the primary tag when the sub-category gives none
Layer 3  optional: Claude on Amazon Bedrock for rows layers 1-2 could not tag
         confidently (or all rows with --llm-all). Results cached in out/cache/.

Every row gets tag_source and a human-readable tag_reason, so each decision
is logged with its reasoning.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .config import CHALLENGE_TAGS, KEYWORD_TAGS, MAX_TAGS, SUBCATEGORY_TAGS
from .projects import text_of

_KW = {t: re.compile(p, re.I) for t, p in KEYWORD_TAGS.items()}


def keyword_hits(text: str) -> dict[str, list[str]]:
    hits = {}
    for t, rx in _KW.items():
        found = sorted({m.group(0).lower() for m in rx.finditer(text)})
        if found:
            hits[t] = found
    return hits


def rule_tags(row) -> dict:
    sub = row.get("subcategory") if isinstance(row.get("subcategory"), str) else None
    text = text_of(row)
    hits = keyword_hits(text)
    name_hits = keyword_hits(str(row.get("name") or ""))  # a keyword in the project name counts double
    score = {t: len(hits[t]) + len(name_hits.get(t, [])) for t in hits}
    ranked = sorted(hits, key=lambda t: (-score[t], CHALLENGE_TAGS.index(t)))
    base, pending = SUBCATEGORY_TAGS.get(sub, ([], False)) if sub else ([], False)
    reasons = []
    if base:
        tags, source = list(base), "subcategory_rule"
        reasons.append(f"subcategory '{sub}' -> {', '.join(base)}")
    elif ranked and score[ranked[0]] >= 2:
        tags, source = [ranked[0]], "keyword"
        reasons.append(f"no usable subcategory ({sub or 'blank'}); strongest keywords {hits[ranked[0]]} -> {ranked[0]}")
    else:
        tags, source = [], "none"
        reasons.append(f"no usable subcategory ({sub or 'blank'}) and weak keyword evidence")
    for t in ranked:  # secondary tags need >= 2 distinct keyword hits
        if len(tags) >= MAX_TAGS:
            break
        if t not in tags and len(hits[t]) >= 2 and source != "none":
            tags.append(t)
            reasons.append(f"keywords {hits[t][:4]} -> {t}")
    return dict(challenge_tags="|".join(tags), primary_tag=tags[0] if tags else None, tag_source=source,
                tag_reason="; ".join(reasons), tag_pending_confirmation=bool(pending))


# ---------------------------------------------------------------- optional Bedrock layer
PROMPT = """You label Fair Trade Premium projects with challenge tags.
Tags (use only these ids): {tags}
Return JSON only: {{"tags": [1-3 tag ids, most important first], "reason": "<one sentence>"}}

Project name: {name}
Description: {description}
Need / reason: {reason}
Primary goal: {goal}"""


def llm_tags(df: pd.DataFrame, model_id: str, cache_dir: Path, region: str | None = None, rows=None) -> pd.DataFrame:
    """Re-tag `rows` (index labels) with Claude via the Bedrock Converse API. Requires boto3 + AWS credentials."""
    import boto3

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_f = cache_dir / "llm_tags.jsonl"
    cache = {}
    if cache_f.exists():
        for line in cache_f.read_text().splitlines():
            r = json.loads(line)
            cache[r["project_id"]] = r
    client = boto3.client("bedrock-runtime", region_name=region)
    df = df.copy()
    rows = df.index if rows is None else rows
    with open(cache_f, "a") as fh:
        for i in rows:
            r = df.loc[i]
            if r.project_id not in cache:
                prompt = PROMPT.format(tags=", ".join(CHALLENGE_TAGS), name=r["name"], description=r.description,
                                       reason=r.reason, goal=r.primary_goal)
                resp = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                                       inferenceConfig={"maxTokens": 300, "temperature": 0})
                txt = resp["output"]["message"]["content"][0]["text"]
                m = re.search(r"\{.*\}", txt, re.S)
                try:
                    parsed = json.loads(m.group(0)) if m else {}
                except json.JSONDecodeError:
                    parsed = {}
                tags = [t for t in parsed.get("tags", []) if t in CHALLENGE_TAGS][:MAX_TAGS]
                cache[r.project_id] = {"project_id": r.project_id, "tags": tags, "reason": parsed.get("reason", ""),
                                       "model_id": model_id}
                fh.write(json.dumps(cache[r.project_id]) + "\n")
            c = cache[r.project_id]
            if c["tags"]:
                df.at[i, "challenge_tags"] = "|".join(c["tags"])
                df.at[i, "primary_tag"] = c["tags"][0]
                df.at[i, "tag_source"] = "llm"
                df.at[i, "tag_reason"] = f"LLM ({c['model_id']}): {c['reason']} | rules said: {df.at[i, 'tag_reason']}"
    return df


def apply(projects: pd.DataFrame, model_id: str | None = None, llm_all: bool = False, cache_dir: Path | None = None,
          region: str | None = None) -> pd.DataFrame:
    tagged = pd.concat([projects.reset_index(drop=True),
                        pd.DataFrame([rule_tags(r) for r in projects.to_dict("records")])], axis=1)
    if model_id:
        rows = tagged.index if llm_all else tagged.index[tagged.tag_source.isin(["none", "keyword"])]
        tagged = llm_tags(tagged, model_id, cache_dir or Path("out/cache"), region, rows)
    return tagged


def labeling_sample(projects: pd.DataFrame, n: int = 40, seed: int = 7) -> pd.DataFrame:
    """Stratified sample for human labeling (spreadsheet: fill human_tags, then run evaluate_tags)."""
    parts = []
    for src, g in projects.groupby("tag_source"):
        k = max(1, round(n * len(g) / len(projects)))
        parts.append(g.sample(min(k, len(g)), random_state=seed))
    s = pd.concat(parts).head(n)
    return s[["project_id", "subcategory", "name", "description", "reason", "challenge_tags", "tag_source"]].assign(
        human_tags="", labeler="", notes="").rename(columns={"challenge_tags": "predicted_tags"})


def evaluate(sample_csv: Path) -> dict:
    s = pd.read_csv(sample_csv, dtype=str).fillna("")
    s = s[s.human_tags.str.strip() != ""]
    if s.empty:
        return {"n": 0}
    P = s.predicted_tags.str.split("|").map(lambda x: {t for t in x if t})
    H = s.human_tags.str.replace(",", "|").str.split("|").map(lambda x: {t.strip() for t in x if t.strip()})
    primary = [p.split("|")[0] == h.replace(",", "|").split("|")[0].strip() for p, h in zip(s.predicted_tags, s.human_tags)]
    jacc = [len(p & h) / len(p | h) if p | h else 1.0 for p, h in zip(P, H)]
    return {"n": len(s), "primary_agreement": round(sum(primary) / len(s), 3),
            "any_overlap": round(sum(bool(p & h) for p, h in zip(P, H)) / len(s), 3),
            "mean_jaccard": round(sum(jacc) / len(s), 3)}
