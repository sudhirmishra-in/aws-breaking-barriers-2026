"""Live end-to-end demonstration against Amazon Bedrock, using only the synthetic sample data.

It plays a scripted producer through two exchanges and shows how memory is read and written:

  A. A multi-turn Spanish exchange from the open question to a draft, with a correction during playback.
  B. Durable commit: the profile update stays invisible to a new exchange until a person reviews it.
  C. A return visit after review: the agent starts from the updated profile and the past issue, and a new
     member count supersedes the old one without deleting it.

A new service object is built for every turn, so all continuity has to come from the memory store.
Run it with: python scripts/smoke_test.py [--store sqlite|dynamodb] [--output report.md] [--trace trace.json]
"""

import argparse
import json
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from producer_exchange.agent.context import build_system_prompt
from producer_exchange.agent.phases import PHASE_SPECS
from producer_exchange.agent.runner import StageTrace
from producer_exchange.config import Settings
from producer_exchange.factory import build_service
from producer_exchange.memory.models import EventType, Phase, ProfileField, ReviewStatus, WorkingMemory
from producer_exchange.memory.profile import ProfileRepository
from producer_exchange.memory.store import DocumentStore, SqliteDocumentStore
from producer_exchange.service import ExchangeNotFound, ExchangeService, TurnResponse
from producer_exchange.sources.sample import SampleDataset

PRODUCER = "P-PE-008"
MAX_TURNS = 14

FIRST_VISIT = [
    "La lluvia ha sido muy irregular y la última cosecha de banano bajó mucho.",
    "Por cierto, ¿nuestra última auditoría de certificación salió bien?",
    (
        "Entiendo. Lo de la lluvia empezó hace dos temporadas y perdimos como un 30% de la cosecha. "
        "Hemos probado regar a mano, pero no alcanza el agua. El comité de agua ya le pidió ayuda a la municipalidad. "
        "Nuestro técnico Carlos Ramírez, 312 555 0199, también lo vio."
    ),
    "Sí, estamos en Piura y somos una asociación de pequeños productores.",
]
RETURN_VISIT = [
    (
        "Hola de nuevo. Seguimos con problemas de agua: este año la quebrada se secó en agosto y perdimos otro 20% "
        "de la cosecha. Probamos con un reservorio pequeño, pero no alcanzó."
    ),
    "Sí, seguimos en Piura y seguimos siendo cooperativa, pero ya somos 360 familias.",
]
FILLER = "Es todo lo que puedo decirle por ahora."
PLAYBACK_CORRECTION = "Casi. Desde este año ya no somos asociación, somos una cooperativa de unas 350 familias."
PLAYBACK_CONFIRMATION = "Sí, ahora es correcto."
RETURN_CONFIRMATION = "Sí, es correcto."
DRAFT_FOLLOW_UP = "¿Cuánto ha bajado la lluvia en nuestra zona?"


class TraceRecorder:
    """Keeps a machine-readable record of the run for the animated walkthrough."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def on_stage_run(self, trace: StageTrace) -> None:
        self.events.append(
            {
                "type": "stage_run",
                "stage": trace.stage_run.phase.value,
                "tools_called": list(trace.stage_run.tools_called),
                "input_tokens": trace.stage_run.input_tokens,
                "output_tokens": trace.stage_run.output_tokens,
                "seconds": trace.stage_run.seconds,
                "stop_reason": trace.stage_run.stop_reason,
                "system_prompt": trace.system_prompt,
                "tool_names": list(trace.tool_names),
                "request_messages": trace.request_messages,
                "run_messages": [_without_thinking(message) for message in trace.run_messages],
                "memory_before": trace.memory_before,
                "memory_after": trace.memory_after,
            }
        )

    def add(self, event_type: str, **fields) -> None:
        self.events.append({"type": event_type, **fields})

    def add_memory(self, event_type: str, memory: WorkingMemory, **fields) -> None:
        self.add(event_type, memory=memory.snapshot(), events=_log_without_prompts(memory), **fields)

    def add_profile(self, service: ExchangeService, profiles: ProfileRepository, label: str) -> None:
        self.add(
            "profile",
            label=label,
            view=service.get_profile(PRODUCER).model_dump(mode="json"),
            facts=[fact.model_dump(mode="json") for fact in profiles.list_facts(PRODUCER)],
            episodes=[episode.model_dump(mode="json") for episode in profiles.list_episodes(PRODUCER)],
        )


def _without_thinking(message: dict) -> dict:
    return {**message, "content": [block for block in message["content"] if "reasoningContent" not in block]}


def _log_without_prompts(memory: WorkingMemory) -> list[dict]:
    log = [event.model_dump(mode="json") for event in memory.events]
    for event in log:
        event["data"].pop("system_prompt", None)
    return log


class Report:
    """Prints as it goes and keeps a Markdown copy to share with the team."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.checks: list[tuple[bool, str]] = []

    def write(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def check(self, passed: bool, description: str) -> None:
        self.checks.append((passed, description))
        self.write(f"- {'PASS' if passed else 'FAIL'}: {description}")

    def quoted(self, speaker: str, text: str) -> None:
        self.write(f"**{speaker}:**")
        self.write()
        self.write("\n".join(f"> {line}" for line in text.splitlines()))
        self.write()

    def block(self, text: str, language: str = "text") -> None:
        self.write(f"```{language}\n{text}\n```")
        self.write()

    def turn(self, response: TurnResponse, memory: WorkingMemory) -> None:
        for run in response.stage_runs:
            self.input_tokens += run.input_tokens
            self.output_tokens += run.output_tokens
        stages = " → ".join(
            f"{run.phase.value}[{', '.join(run.tools_called) or 'text'}]" for run in response.stage_runs
        )
        understanding = memory.understanding
        self.write(
            "Memory after this turn: "
            f"stage `{response.phase.value}` · understanding v{understanding.version} · "
            f"missing {understanding.missing_slots() or 'nothing'} · "
            f"confirmed {memory.is_confirmed} · evidence {len(memory.evidence)} · "
            f"notes {len(understanding.notes)} · log {len(memory.events)} events · "
            f"staged facts {[(fact.field.value, fact.value) for fact in understanding.profile_facts]} · "
            f"PII {[flag.entity_types for flag in memory.pii_flags]}"
        )
        self.write()
        self.write(f"Model runs: {stages or 'none'}")
        self.write()


def memory_blocks(store: DocumentStore, settings: Settings, memory: WorkingMemory) -> str:
    """Show what the model is given from memory for the first stage of an exchange."""
    sources = SampleDataset(settings.data_dir).as_sources()
    view = ProfileRepository(store, sources.producers).load_view(memory.producer_id, memory.confirmed_facts())
    prompt = build_system_prompt(PHASE_SPECS[Phase.CLARIFY], memory, view)
    return prompt.split("</stage>\n\n", 1)[1]


def run_exchange(
    make: "ServiceFactory",
    report: Report,
    trace: TraceRecorder,
    label: str,
    answers: list[str],
    playback_answers: list[str],
    follow_up: str | None = None,
) -> str:
    """Play a scripted producer who answers whatever the current stage is asking for."""
    started = make().start_exchange(PRODUCER)
    exchange_id = started.exchange_id
    report.quoted("Agent", started.greeting)
    trace.add("exchange_start", exchange=label, greeting=started.greeting)

    remaining, playback_remaining = list(answers), list(playback_answers)
    turn_messages: list[str] = []
    for _ in range(MAX_TURNS):
        service = make()  # Nothing survives between turns except the store.
        memory = service.get_working_memory(exchange_id, PRODUCER)
        if memory.phase == Phase.DRAFTED:
            break
        if memory.phase == Phase.PLAYBACK and playback_remaining:
            message = playback_remaining.pop(0)
        else:
            message = remaining.pop(0) if remaining else FILLER
        turn_messages.append(message)
        _play_turn(service, exchange_id, memory.turn + 1, message, report, trace, label)

    if follow_up:
        service = make()
        memory = service.get_working_memory(exchange_id, PRODUCER)
        if memory.phase == Phase.DRAFTED:
            _play_turn(service, exchange_id, memory.turn + 1, follow_up, report, trace, label)
    return exchange_id


def _play_turn(service, exchange_id, turn, message, report, trace, label) -> None:
    report.write(f"### Turn {turn}")
    report.write()
    report.quoted("Producer", message)
    trace.add("turn_start", exchange=label, turn=turn, message=message)
    response = service.handle_turn(exchange_id, PRODUCER, message)
    after = service.get_working_memory(exchange_id, PRODUCER)
    trace.add_memory("turn_end", after, reply=response.reply)
    report.quoted("Agent", response.reply)
    report.turn(response, after)


def check_first_visit(service: ExchangeService, exchange_id: str, report: Report) -> None:
    memory = service.get_working_memory(exchange_id, PRODUCER)
    understanding = memory.understanding
    draft = memory.draft
    transcript = " ".join(entry.text for entry in memory.transcript if entry.role == "user")
    entity_facts = [fact for fact in understanding.profile_facts if fact.field == ProfileField.ENTITY_TYPE]
    log = service.get_event_log(exchange_id, PRODUCER)
    tool_order = [event.data["tool"] for event in log if event.type == EventType.TOOL_CALL]
    stage_runs = [event for event in log if event.type == EventType.STAGE_RUN]
    keys = [" ".join(quote.casefold().strip(" .,").split()) for quote in understanding.producer_quotes]

    report.write("### Checks")
    report.write()
    report.check(memory.phase == Phase.DRAFTED, "the exchange reached the draft stage")
    report.check(understanding.version >= 2, "the correction created a new understanding version")
    report.check(
        bool(entity_facts) and entity_facts[-1].value.casefold() == "cooperative",
        "the corrected entity type is staged as a profile fact",
    )
    report.check(
        bool(entity_facts) and bool(entity_facts[-1].valid_from),
        "the fact records when it became true, as the producer said it",
    )
    report.check(
        memory.confirmed_version == understanding.version,
        "the final version, not the first one, is what the producer confirmed",
    )
    report.check(
        tool_order.index("confirm_understanding") < tool_order.index("get_producer_record"),
        "nothing was retrieved before the producer confirmed",
    )
    report.check(draft is not None and any(claim.kind == "insight" for claim in draft.claims), "the draft has an insight")
    report.check(draft is not None and any(claim.kind == "peer_example" for claim in draft.claims), "the draft has a peer example")
    report.check(
        draft is not None
        and all(evidence_id in memory.evidence for claim in draft.claims for evidence_id in claim.evidence_ids),
        "every citation resolves to this session's evidence ledger",
    )
    report.check(
        any({"NAME", "PHONE"} & set(flag.entity_types) for flag in memory.pii_flags),
        "the named person and phone number raised a PII flag",
    )
    report.check("Carlos Ramírez" in transcript and "312 555 0199" in transcript, "the producer's words were not redacted")
    report.check(bool(understanding.notes), "a detail that fits no slot was kept as a session note")
    report.check(len(keys) == len(set(keys)), "no near-duplicate quotes were saved")
    remembered = understanding.model_dump_json().casefold()
    report.check("auditor" not in remembered, "the out-of-scope audit question stayed out of structured memory")
    report.check(
        bool(stage_runs) and all(event.data["system_prompt"] for event in stage_runs) and len(tool_order) >= 6,
        "the event log holds every tool call and each run's exact prompt",
    )
    report.check(
        service.get_profile(PRODUCER).current(ProfileField.ENTITY_TYPE) == "small producer association",
        "no durable profile write happened during the conversation",
    )
    report.write()


def run_commit_and_review(
    make: "ServiceFactory", store, settings: Settings, exchange_id: str, report: Report, trace: TraceRecorder
) -> None:
    report.write("## B. Durable commit, then human review")
    report.write()
    report.write(
        "`commit_memory(consent_granted=True)` stands in for the future consent stage. "
        "It writes pending records only."
    )
    report.write()
    service = make()
    sources = SampleDataset(settings.data_dir).as_sources()
    profiles = ProfileRepository(store, sources.producers)
    trace.add_profile(service, profiles, "before_commit")
    result = service.commit_memory(exchange_id, PRODUCER, consent_granted=True)
    trace.add_memory("commit", service.get_working_memory(exchange_id, PRODUCER), label="first")
    trace.add_profile(service, profiles, "after_commit")
    pending_view = service.get_profile(PRODUCER)
    pending = service.start_exchange(PRODUCER)
    pending_memory = service.get_working_memory(pending.exchange_id, PRODUCER)
    preview = memory_blocks(store, settings, pending_memory)
    trace.add("memory_preview", label="pending", text=preview)

    report.write("A new exchange **before review** would be given this memory:")
    report.write()
    report.block(preview)
    report.check(
        pending_view.current(ProfileField.ENTITY_TYPE) == "small producer association",
        "pending facts are invisible to other exchanges",
    )
    report.check(pending_view.reviewed_episodes == [], "the pending episode is not available as evidence")
    report.check(pending_view.pending_review_count == len(result.fact_ids) + 1, "the records wait in the review queue")
    episode = profiles.list_episodes(PRODUCER)[0]
    report.check({"NAME", "PHONE"} & set(episode.pii_entity_types) != set(), "the PII flag travels with the episode to the reviewer")
    report.write()

    report.write("A reviewer now handles the queue:")
    report.write()
    _approve_everything_pending(profiles, report)
    trace.add("review", label="first")
    trace.add_profile(service, profiles, "after_review")
    service.discard_exchange(pending.exchange_id, PRODUCER)


def _approve_everything_pending(profiles: ProfileRepository, report: Report) -> None:
    for fact in profiles.list_facts(PRODUCER):
        if fact.status == ReviewStatus.PENDING:
            since = f", since \"{fact.valid_from}\"" if fact.valid_from else ""
            report.write(f"- approve `{fact.field.value}` = `{fact.value}`{since}, supported by: \"{fact.producer_quote}\"")
            profiles.review_fact(PRODUCER, fact.fact_id, status=ReviewStatus.APPROVED, reviewer="smoke-test reviewer")
    for episode in profiles.list_episodes(PRODUCER):
        if episode.status == ReviewStatus.PENDING:
            report.write(f"- approve the episode ({len(episode.notes)} notes, PII: {episode.pii_entity_types or 'none'})")
            profiles.review_episode(PRODUCER, episode.episode_id, status=ReviewStatus.APPROVED, reviewer="smoke-test reviewer")
    report.write()


def run_return_visit(make: "ServiceFactory", store, settings: Settings, report: Report, trace: TraceRecorder) -> None:
    report.write("## C. A return visit after review")
    report.write()
    service = make()
    sources = SampleDataset(settings.data_dir).as_sources()
    profiles = ProfileRepository(store, sources.producers)
    probe = service.start_exchange(PRODUCER)
    report.write("A new exchange is now given this memory:")
    report.write()
    report.block(memory_blocks(store, settings, service.get_working_memory(probe.exchange_id, PRODUCER)))
    service.discard_exchange(probe.exchange_id, PRODUCER)

    exchange_id = run_exchange(make, report, trace, "C", RETURN_VISIT, [RETURN_CONFIRMATION])

    service = make()
    report.write("### Commit and review")
    report.write()
    result = service.commit_memory(exchange_id, PRODUCER, consent_granted=True)
    trace.add_memory("commit", service.get_working_memory(exchange_id, PRODUCER), label="second")
    trace.add_profile(service, profiles, "after_second_commit")
    _approve_everything_pending(profiles, report)
    trace.add("review", label="second")
    trace.add_profile(service, profiles, "after_second_review")
    probe = service.start_exchange(PRODUCER)
    final_preview = memory_blocks(store, settings, service.get_working_memory(probe.exchange_id, PRODUCER))
    trace.add("memory_preview", label="final", text=final_preview)
    service.discard_exchange(probe.exchange_id, PRODUCER)

    view = service.get_profile(PRODUCER)
    history = service.get_fact_history(PRODUCER, ProfileField.MEMBER_COUNT)
    report.write("### Checks")
    report.write()
    report.check(view.current(ProfileField.ENTITY_TYPE).casefold() == "cooperative", "the approved entity type still applies")
    report.check(view.current(ProfileField.MEMBER_COUNT) == "360", "the newest reviewed member count applies")
    report.check(
        [fact.value for fact in history] == ["350", "360"] and history[0].superseded_by == history[1].fact_id,
        "the older value is kept and marked as superseded",
    )
    report.check(len(view.reviewed_episodes) == 2, "both approved episodes are available to later exchanges")
    report.check(view.registered.entity_type == "small producer association", "the registered source record is unchanged")
    report.check(view.registered.member_count == 330, "the registered member count is unchanged")
    report.check(view.registered.region_id == "PE-PIU", "the location scope is unchanged")

    service.discard_exchange(exchange_id, PRODUCER)
    try:
        service.get_working_memory(exchange_id, PRODUCER)
        discarded = False
    except ExchangeNotFound:
        discarded = True
    report.check(discarded and store.query(f"EXCHANGE#{exchange_id}") == [], "discarding an exchange deletes its state and whole log")
    report.check(result.episode_id in [episode.episode_id for episode in profiles.list_episodes(PRODUCER)], "the reviewed episode survives the discard")
    report.write()


class ServiceFactory:
    def __init__(self, settings: Settings, open_store, trace: TraceRecorder) -> None:
        self._settings = settings
        self._open_store = open_store
        self._trace = trace

    def __call__(self) -> ExchangeService:
        return build_service(self._settings, store=self._open_store(), observer=self._trace.on_stage_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", choices=["sqlite", "dynamodb"], default="sqlite")
    parser.add_argument("--output", type=Path, default=None, help="Also write the report to this Markdown file")
    parser.add_argument("--trace", type=Path, default=None, help="Also write every model run's prompt and memory as JSON")
    args = parser.parse_args()

    settings = Settings.from_env()
    temp_table = None
    with tempfile.TemporaryDirectory() as directory:
        if args.store == "dynamodb":
            from producer_exchange.memory.dynamodb import DynamoDBDocumentStore, create_table

            temp_table = f"px-smoke-{uuid.uuid4().hex[:8]}"
            create_table(temp_table, settings.aws_region)
            open_store = lambda: DynamoDBDocumentStore(temp_table, settings.aws_region)
            settings = replace(settings, store_backend="dynamodb", dynamodb_table=temp_table)
        else:
            path = Path(directory) / "memory.db"
            open_store = lambda: SqliteDocumentStore(path)

        report = Report()
        report.write("# Smoke test: memory and multi-turn agent")
        report.write()
        report.write(
            f"Model `{settings.model_id}` on Amazon Bedrock · store `{args.store}` · producer `{PRODUCER}` · "
            "synthetic sample data only"
        )
        report.write()
        trace = TraceRecorder()
        try:
            make = ServiceFactory(settings, open_store, trace)
            report.write("## A. One exchange, from the open question to a draft")
            report.write()
            exchange_id = run_exchange(
                make, report, trace, "A", FIRST_VISIT, [PLAYBACK_CORRECTION, PLAYBACK_CONFIRMATION], DRAFT_FOLLOW_UP
            )
            check_first_visit(make(), exchange_id, report)
            run_commit_and_review(make, open_store(), settings, exchange_id, report, trace)
            run_return_visit(make, open_store(), settings, report, trace)
        finally:
            if temp_table:
                from producer_exchange.memory.dynamodb import delete_table

                delete_table(temp_table, settings.aws_region)

    passed = sum(1 for ok, _ in report.checks if ok)
    report.write("## Result")
    report.write()
    report.write(f"{passed} of {len(report.checks)} checks passed.")
    report.write(f"Tokens: {report.input_tokens:,} input, {report.output_tokens:,} output.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report.lines) + "\n", encoding="utf-8")
    if args.trace:
        args.trace.parent.mkdir(parents=True, exist_ok=True)
        args.trace.write_text(json.dumps(trace.events, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if passed == len(report.checks) else 1


if __name__ == "__main__":
    sys.exit(main())
