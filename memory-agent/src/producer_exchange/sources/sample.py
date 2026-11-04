"""Adapter for the synthetic sample dataset in `data/sample`."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from producer_exchange.memory.models import ChallengeTag
from producer_exchange.sources.base import (
    DataSources,
    PeerCase,
    PeerQuery,
    PremiumProject,
    ProducerRecord,
    RegionalFact,
    StandardClause,
    SurveySummary,
)

_GLOBAL_REGION = "*"
_SURVEY_METRICS = ("avg_income_change_pct", "share_reporting_lower_yield_pct")


def _load(data_dir: Path, name: str) -> list[dict[str, Any]]:
    return json.loads((data_dir / f"{name}.json").read_text(encoding="utf-8"))


def _peer_case_id(project_id: str) -> str:
    """An opaque ID: the sample's project IDs embed the owning producer's ID."""
    return "PC-" + hashlib.sha256(project_id.encode()).hexdigest()[:10]


class SampleDataset:
    """Implements all four source protocols over one small in-memory dataset."""

    def __init__(self, data_dir: Path) -> None:
        self._producers = {
            row["producer_id"]: ProducerRecord(
                producer_id=row["producer_id"],
                display_name=row["org_name"],
                country=row["country"],
                region=row["region"],
                region_id=row["region_id"],
                crops=[row["crop"]],
                entity_type=row["entity_type"],
                member_count=row["members"],
                language=row["language"],
            )
            for row in _load(data_dir, "producers")
        }
        self._projects = [PremiumProject.model_validate(row) for row in _load(data_dir, "projects")]
        self._surveys = {
            row["producer_id"]: SurveySummary(
                survey_id=row["survey_id"],
                producer_id=row["producer_id"],
                year=row["year"],
                respondents=row["respondents"],
                top_reported_challenges=list(dict.fromkeys(row["top_reported_challenges"])),
                metrics={metric: row[metric] for metric in _SURVEY_METRICS},
            )
            for row in _load(data_dir, "surveys")
        }
        self._regional = _load(data_dir, "regional")
        with (data_dir / "standards.sample.csv").open(encoding="utf-8", newline="") as handle:
            self._clauses = [
                StandardClause(
                    clause_id=row["clause_id"],
                    standard=row["standard"],
                    section=row["section"],
                    text=row["text"],
                    tags=[ChallengeTag(tag) for tag in row["tags"].split("|") if tag],
                )
                for row in csv.DictReader(handle)
            ]

    def as_sources(self) -> DataSources:
        return DataSources(
            producers=_Producers(self),
            regional=_Regional(self),
            peers=_Peers(self),
            standards=_Standards(self),
        )


class _Producers:
    def __init__(self, dataset: SampleDataset) -> None:
        self._dataset = dataset

    def get(self, producer_id: str) -> ProducerRecord | None:
        return self._dataset._producers.get(producer_id)

    def projects(self, producer_id: str) -> list[PremiumProject]:
        return [project for project in self._dataset._projects if project.producer_id == producer_id]

    def survey(self, producer_id: str) -> SurveySummary | None:
        return self._dataset._surveys.get(producer_id)


class _Regional:
    def __init__(self, dataset: SampleDataset) -> None:
        self._dataset = dataset

    def facts(self, region_id: str | None, crops: list[str], tags: list[ChallengeTag]) -> list[RegionalFact]:
        wanted = set(tags)
        facts = []
        for row in self._dataset._regional:
            in_region = row["region_id"] == region_id
            is_global_for_crop = row["region_id"] == _GLOBAL_REGION and row.get("crop") in crops
            row_tags = {ChallengeTag(tag) for tag in row["tags"]}
            if (in_region or is_global_for_crop) and row_tags & wanted:
                facts.append(
                    RegionalFact(
                        source_id=row["source_id"],
                        dataset=row["dataset"],
                        metric=row["metric"],
                        value=row["value"],
                        tags=sorted(row_tags),
                    )
                )
        return facts


class _Peers:
    def __init__(self, dataset: SampleDataset) -> None:
        self._dataset = dataset

    def search(self, query: PeerQuery) -> list[PeerCase]:
        wanted = set(query.tags)
        excluded_titles = {title.casefold() for title in query.exclude_titles}
        scored: list[tuple[int, PeerCase]] = []
        for project in self._dataset._projects:
            if project.producer_id == query.exclude_producer_id or project.title.casefold() in excluded_titles:
                continue
            if not wanted & set(project.tags):
                continue
            owner = self._dataset._producers[project.producer_id]
            score = (
                2 * bool(set(owner.crops) & set(query.crops))
                + (owner.country == query.country)
                + (owner.entity_type == query.entity_type)
            )
            scored.append(
                (
                    score,
                    PeerCase(
                        case_id=_peer_case_id(project.project_id),
                        organization_label=owner.display_name,
                        entity_type=owner.entity_type,
                        country=owner.country,
                        crops=owner.crops,
                        year=project.year,
                        title=project.title,
                        description=project.description,
                        status=project.status,
                        amount_usd=project.amount_usd,
                        outcome_note=project.outcome_note,
                        tags=project.tags,
                    ),
                )
            )
        scored.sort(key=lambda entry: (-entry[0], entry[1].case_id))
        return [case for _, case in scored[: query.limit]]


class _Standards:
    def __init__(self, dataset: SampleDataset) -> None:
        self._dataset = dataset

    def search(self, tags: list[ChallengeTag], limit: int = 5) -> list[StandardClause]:
        wanted = set(tags)
        scored = [(len(wanted & set(clause.tags)), clause) for clause in self._dataset._clauses]
        scored = [entry for entry in scored if entry[0] > 0]
        scored.sort(key=lambda entry: (-entry[0], entry[1].clause_id))
        return [clause for _, clause in scored[:limit]]
