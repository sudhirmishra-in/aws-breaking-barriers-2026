"""Trusted context built by the application backend. The model never sees a way to change it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["en", "es", "fr"]
Mode = Literal["intake", "guidance", "ask", "followup"]
ChallengeTag = Literal[
    "climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
    "education", "health", "infrastructure", "biodiversity_conservation", "social_community",
]


class ProducerRef(BaseModel):
    producerId: str
    entityType: str
    location: str
    crop: str
    country: str | None = None  # from the organization record (server side); the tool never has to guess it from a free-text location


class TrustedContext(BaseModel):
    conversationId: str
    language: Language
    mode: Mode
    allowPlayback: bool
    forcePlayback: bool = False  # set by the application after several turns so intake cannot go on indefinitely
    producer: ProducerRef
    confirmedAccount: str | None = None
    # Regional facts the APPLICATION already looked up for the producer's own country (stand-ins removed). The closing turn cites these without having to decide to call a tool.
    externalFacts: list[dict] = Field(default_factory=list, max_length=8)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class TurnRequest(BaseModel):
    context: TrustedContext
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class Evidence(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    note: str = ""


class TurnOutput(BaseModel):
    """Model-proposed turn. The application, not the model, decides workflow transitions."""

    reply: str = Field(description="Message shown to the producer, in the conversation language.")
    phase: Literal["intake", "playback", "guidance", "answer"]
    playback_summary: str | None = Field(
        default=None, description="Short account of what the producer said, only when phase is playback."
    )
    title: str | None = Field(
        default=None,
        description="Only when phase is playback: a neutral title of at most 8 words naming the challenge, in the conversation language.",
    )
    summary_original: str | None = Field(
        default=None, description="Summary proposal in the conversation language (guidance only)."
    )
    summary_en: str | None = Field(default=None, description="The same summary in English (guidance only).")
    challenge_tags: list[ChallengeTag] = Field(
        default_factory=list, description="Guidance only: 1 to 3 challenge tags that best describe the confirmed account."
    )


class TurnResponse(BaseModel):
    reply: str
    phase: Literal["intake", "playback", "guidance", "answer"]
    playbackSummary: str | None = None
    title: str | None = None
    summaryOriginal: str | None = None
    summaryEn: str | None = None
    challengeTags: list[ChallengeTag] = []
    piiFlag: bool = False
    piiTypes: list[str] = []
    evidence: Evidence = Evidence()
    language: Language


# ---- Case matching (separate structured step; the application chooses and projects the candidates, the model only ranks them) ----
class Candidate(BaseModel):
    caseId: str = Field(max_length=120)
    challenge: str = Field(max_length=1200)
    action: str | None = Field(default=None, max_length=700)
    result: str | None = Field(default=None, max_length=700)
    tags: list[str] = Field(default_factory=list, max_length=6)
    sameOrganization: bool = False
    sameCountry: bool = False


class MatchRequest(BaseModel):
    task: Literal["match"]
    language: Language
    producer: ProducerRef
    account: str = Field(max_length=2000, description="The producer's confirmed account of their problem.")
    tags: list[str] = Field(default_factory=list, max_length=6)
    candidates: list[Candidate] = Field(max_length=25)


class Match(BaseModel):
    caseId: str
    fit: Literal["strong", "partial"]
    reason: str = Field(max_length=260, description="One sentence, in the producer's language, saying what makes this case similar to their problem.")


class MatchOutput(BaseModel):
    matches: list[Match] = Field(default_factory=list, max_length=8)


class MatchResponse(BaseModel):
    matches: list[Match]
    considered: int
