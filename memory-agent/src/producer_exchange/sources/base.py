"""Read-only data ports behind the agent's tools.

Tools depend only on these records and protocols. Adding a dataset means writing one adapter that maps
it to these shapes. Fields that not every dataset has are optional, so tools never assume they exist.
Certification status is deliberately absent: the agent must not be able to answer questions about it.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from producer_exchange.memory.models import ChallengeTag


class ProducerRecord(BaseModel):
    """The registered record from the system of record. Agent conversations never change it."""

    producer_id: str
    display_name: str | None = None
    country: str
    region: str | None = None
    region_id: str | None = None
    crops: list[str] = Field(default_factory=list)
    entity_type: str | None = None
    member_count: int | None = None
    language: str | None = None


class PremiumProject(BaseModel):
    project_id: str
    producer_id: str
    year: int | None = None
    title: str
    description: str = ""
    reason: str | None = None
    goal: str | None = None
    tags: list[ChallengeTag] = Field(default_factory=list)
    status: str | None = None
    amount_usd: int | None = None
    outcome_note: str | None = None


class SurveySummary(BaseModel):
    """An aggregate. Row-level survey responses must never reach the agent."""

    survey_id: str
    producer_id: str
    year: int | None = None
    respondents: int | None = None
    top_reported_challenges: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class RegionalFact(BaseModel):
    source_id: str
    dataset: str
    metric: str
    value: str  # Values can be categorical ("medium-high -> high"), so they stay as published.
    period: str | None = None
    as_of: str | None = None
    tags: list[ChallengeTag] = Field(default_factory=list)


class PeerCase(BaseModel):
    """A shareable project description. It has no field that links back to the peer's producer record."""

    case_id: str
    organization_label: str | None = None
    entity_type: str | None = None
    country: str | None = None
    crops: list[str] = Field(default_factory=list)
    year: int | None = None
    title: str
    description: str = ""
    reason: str | None = None
    goal: str | None = None
    status: str | None = None
    amount_usd: int | None = None
    outcome_note: str | None = None
    tags: list[ChallengeTag] = Field(default_factory=list)


class StandardClause(BaseModel):
    clause_id: str
    standard: str
    section: str | None = None
    text: str
    localized_text: dict[str, str] = Field(default_factory=dict)
    tags: list[ChallengeTag] = Field(default_factory=list)


class PeerQuery(BaseModel):
    """Built by the tool from trusted state. The model supplies only `tags`."""

    tags: list[ChallengeTag]
    exclude_producer_id: str
    crops: list[str] = Field(default_factory=list)
    country: str | None = None
    entity_type: str | None = None
    exclude_titles: list[str] = Field(default_factory=list)
    limit: int = 4


class ProducerDirectory(Protocol):
    def get(self, producer_id: str) -> ProducerRecord | None: ...

    def projects(self, producer_id: str) -> list[PremiumProject]: ...

    def survey(self, producer_id: str) -> SurveySummary | None:
        """Optional enrichment: most producers have no linked survey."""
        ...


class RegionalSource(Protocol):
    def facts(
        self, region_id: str | None, crops: list[str], tags: list[ChallengeTag]
    ) -> list[RegionalFact]: ...


class PeerCaseSource(Protocol):
    def search(self, query: PeerQuery) -> list[PeerCase]: ...


class StandardsSource(Protocol):
    def search(self, tags: list[ChallengeTag], limit: int = 5) -> list[StandardClause]: ...


@dataclass(frozen=True)
class DataSources:
    producers: ProducerDirectory
    regional: RegionalSource
    peers: PeerCaseSource
    standards: StandardsSource
