"""Producer-facing text built by code rather than the model."""

from producer_exchange.memory.models import WorkingMemory

_LABELS = {
    "en": {"draft": "Draft, not yet verified", "sources": "Sources", "standards": "Related standards", "gaps": "What the data does not cover"},
    "es": {"draft": "Borrador, aún sin verificar", "sources": "Fuentes", "standards": "Normas relacionadas", "gaps": "Lo que los datos no cubren"},
    "fr": {"draft": "Brouillon, pas encore vérifié", "sources": "Sources", "standards": "Normes associées", "gaps": "Ce que les données ne couvrent pas"},
}

GREETINGS = {
    "en": "Hello, and thank you for your time. I'm the Fair Trade USA Producer Exchange assistant. What has been most difficult for you or your organization recently?",
    "es": "Hola, y gracias por su tiempo. Soy el asistente de Intercambio de Productores de Fair Trade USA. ¿Qué ha sido lo más difícil para usted o su organización últimamente?",
    "fr": "Bonjour, et merci de prendre ce temps. Je suis l'assistant d'échange avec les producteurs de Fair Trade USA. Qu'est-ce qui a été le plus difficile pour vous ou votre organisation récemment ?",
}

SOURCE_NOUNS = {
    "premium": {"en": "Premium project", "es": "Proyecto Premium", "fr": "Projet Prime"},
    "survey": {"en": "Survey", "es": "Encuesta", "fr": "Enquête"},
    "past_exchange": {"en": "Earlier conversation", "es": "Conversación anterior", "fr": "Conversation précédente"},
    "peer": {"en": "A peer organization", "es": "Otra organización", "fr": "Une organisation pair"},
}

FALLBACK_REPLIES = {
    "en": "Sorry, I could not finish that step. Could you send your message again?",
    "es": "Lo siento, no pude completar ese paso. ¿Podría enviar su mensaje de nuevo?",
    "fr": "Désolé, je n'ai pas pu terminer cette étape. Pourriez-vous renvoyer votre message ?",
}


def localized(table: dict[str, str], language: str) -> str:
    return table.get(language, table["en"])


def render_guidance(memory: WorkingMemory) -> str:
    """Render the draft. Source names come from the evidence ledger, so the model cannot invent them."""
    draft = memory.draft
    if draft is None:
        raise ValueError("no draft to render")
    labels = _LABELS.get(memory.language, _LABELS["en"])
    lines = [f"[{labels['draft']}]", "", draft.intro, ""]
    for index, claim in enumerate(draft.claims, start=1):
        lines.append(f"{index}. {claim.text}")
        sources = "; ".join(memory.evidence[evidence_id].source_label for evidence_id in claim.evidence_ids)
        lines.append(f"   {labels['sources']}: {sources}")
        if claim.standard_evidence_ids:
            standards = "; ".join(memory.evidence[evidence_id].source_label for evidence_id in claim.standard_evidence_ids)
            lines.append(f"   {labels['standards']}: {standards}")
    if draft.evidence_gaps:
        lines += ["", f"{labels['gaps']}:"]
        lines += [f"- {gap}" for gap in draft.evidence_gaps]
    lines += ["", draft.closing]
    return "\n".join(lines)
