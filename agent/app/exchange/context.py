"""Trusted context built by the application backend. The model never sees a way to change it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["en", "es"]
Mode = Literal["intake", "guidance", "ask"]


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
    summary_en: str | None = Field(default=None, description="English summary proposal (guidance only).")
    summary_es: str | None = Field(default=None, description="Spanish summary proposal (guidance only).")


class TurnResponse(BaseModel):
    reply: str
    phase: Literal["intake", "playback", "guidance", "answer"]
    playbackSummary: str | None = None
    summaryEn: str | None = None
    summaryEs: str | None = None
    piiFlag: bool = False
    piiTypes: list[str] = []
    evidence: Evidence = Evidence()
    language: Language
