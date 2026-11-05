"""Trusted context built by the application backend. The model never sees a way to change it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["en", "es", "fr"]
Mode = Literal["intake", "guidance", "ask"]
ChallengeTag = Literal[
    "climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
    "education", "health", "infrastructure", "biodiversity_conservation", "social_community",
]


class ProducerRef(BaseModel):
    producerId: str
    entityType: str
    location: str
    crop: str


class TrustedContext(BaseModel):
    conversationId: str
    language: Language
    mode: Mode
    allowPlayback: bool
    producer: ProducerRef
    confirmedAccount: str | None = None


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
