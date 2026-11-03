"""PII is flagged, never redacted: the guardrail PII filters run in detect mode (action NONE)."""

from __future__ import annotations


def detected_pii_types(apply_guardrail_response: dict) -> list[str]:
    """Return only entity TYPE names (never matched text) from an ApplyGuardrail response."""
    types: list[str] = []
    for assessment in apply_guardrail_response.get("assessments", []):
        for entity in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            t = entity.get("type")
            if t and t not in types:
                types.append(t)
    return types


def check_pii(client, guardrail_id: str, guardrail_version: str, text: str) -> list[str]:
    resp = client.apply_guardrail(
        guardrailIdentifier=guardrail_id,
        guardrailVersion=guardrail_version,
        source="INPUT",
        content=[{"text": {"text": text}}],
    )
    return detected_pii_types(resp)
