"""Data catalog: load catalog.yaml, render coverage from stats, summarize for the prompt (CAT-1..6)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
DEFAULT_CATALOG = HERE / "catalog.yaml"


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


class Catalog:
    def __init__(self, path: Path = DEFAULT_CATALOG, stats: dict | None = None):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.stats = stats or {}
        self.datasets = {}
        for d in raw["datasets"]:
            d = dict(d)
            d["coverage"] = str(d.get("coverage", "")).format_map(_Safe(self.stats))
            self.datasets[d["name"]] = d

    @classmethod
    def with_stats_file(cls, stats_file: Path, path: Path = DEFAULT_CATALOG):
        stats = json.loads(Path(stats_file).read_text()) if Path(stats_file).exists() else {}
        return cls(path, stats)

    def names(self) -> list[str]:
        return list(self.datasets)

    def describe(self, name: str) -> dict:
        if name not in self.datasets:
            return {"error": "no_such_dataset", "message": f"Unknown dataset {name!r}", "available": self.names()}
        return self.datasets[name]

    def field_names(self, name: str) -> list[str]:
        """Attribute names a dataset promises (keys split on ' / ')."""
        return [f.strip() for k in self.datasets[name]["fields"] for f in k.split("/")]

    def prompt_summary(self) -> str:
        """Condensed catalog for the system prompt (CAT-2). Keep it short; details via describe_dataset."""
        lines = ["Datasets you can use (call describe_dataset(name) for field details):"]
        for d in self.datasets.values():
            lines.append(f"- {d['name']} ({d['grain']}). Answers: {d['answers']}. "
                         f"Cannot answer: {d['cannot_answer']}. Coverage: {d['coverage']}.")
        return "\n".join(lines)
