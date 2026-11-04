"""PII detection on producer messages. This module only flags. It never alters the producer's words."""

import logging
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from producer_exchange.memory.models import PiiFlag

logger = logging.getLogger(__name__)

_COMPREHEND_LANGUAGES = {"en", "es"}
_MIN_SCORE = 0.5
# Comprehend also reports dates, ages and similar. The Vision document asks for named people and contact details.
_FLAGGED_TYPES = {"NAME", "EMAIL", "PHONE", "ADDRESS", "URL", "USERNAME"}


class PiiDetector(Protocol):
    def scan(self, text: str, language: str, turn: int) -> PiiFlag | None:
        """Return a flag when there is something a reviewer should see, otherwise None."""
        ...


class NoopPiiDetector:
    def scan(self, text: str, language: str, turn: int) -> PiiFlag | None:
        return None


class ComprehendPiiDetector:
    def __init__(self, region: str) -> None:
        self._client = boto3.client("comprehend", region_name=region)

    def scan(self, text: str, language: str, turn: int) -> PiiFlag | None:
        if language not in _COMPREHEND_LANGUAGES:
            return PiiFlag(turn=turn, scan_status="unsupported_language")
        try:
            response = self._client.detect_pii_entities(Text=text, LanguageCode=language)
        except (BotoCoreError, ClientError):
            logger.exception("PII scan failed")
            return PiiFlag(turn=turn, scan_status="failed")
        entity_types = sorted(
            {
                entity["Type"]
                for entity in response["Entities"]
                if entity["Score"] >= _MIN_SCORE
                and entity["Type"] in _FLAGGED_TYPES
                and not _is_bare_place_name(entity, text)
            }
        )
        return PiiFlag(turn=turn, entity_types=entity_types) if entity_types else None


def _is_bare_place_name(entity: dict, text: str) -> bool:
    """Comprehend reports "Piura" as an ADDRESS. Producers name their region all the time, so requiring a
    number keeps street addresses flagged without flagging nearly every conversation."""
    span = text[entity["BeginOffset"] : entity["EndOffset"]]
    return entity["Type"] == "ADDRESS" and not any(character.isdigit() for character in span)
