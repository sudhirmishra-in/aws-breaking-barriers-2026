"""Turn the smoke test's trace into the scenes of the memory replay page. Nothing here is invented: prompts,
memory, tool calls and log entries come from the trace. Only narration and English glosses are written by hand."""

import json
import re
import sys
from pathlib import Path

TRACE, TEMPLATE, OUTPUT = map(Path, sys.argv[1:4])
events = json.loads(TRACE.read_text(encoding="utf-8"))

SECTIONS = ["policy", "stage", "profile", "past", "working", "evidence", "draft", "transcript"]
SECTION_LABEL = {"stage": "stage", "profile": "profile", "past": "past exchanges", "working": "working memory", "evidence": "evidence", "draft": "draft", "transcript": "transcript"}
TAGS = {"profile": "producer_profile", "past": "past_reviewed_exchanges", "working": "working_memory", "evidence": "evidence", "draft": "draft"}
SOURCE_NODE = {"stage": "mem-stage", "profile": "l1-registered", "past": "l1-reviewed", "working": "mem-understanding", "evidence": "mem-evidence", "draft": "mem-draft", "transcript": "log-box"}
TOOL_TARGET = {
    "record_understanding": "mem-understanding",
    "confirm_understanding": "mem-playback",
    "submit_guidance": "mem-draft",
    "get_producer_record": "mem-evidence",
    "get_regional_context": "mem-evidence",
    "search_peer_examples": "mem-evidence",
    "retrieve_standards": "mem-evidence",
}
DATA_TOOLS = {"get_producer_record", "get_regional_context", "search_peer_examples", "retrieve_standards"}
SOURCE_GROUP = {"producer_record": "Own record", "regional": "Regional", "peer_case": "Peers", "standard": "Standards"}
KIND_LABEL = {
    "arrive": "Message in, prompt compiled",
    "write": "Model writes to memory",
    "write+rebuild": "Model writes, prompt rebuilt",
    "reply": "Reply and atomic save",
    "commit": "Durable commit",
    "preview": "What a new exchange would get",
    "review": "Human review",
}


def text_of(message):
    return "\n".join(block["text"] for block in message["content"] if "text" in block)


def short(text, limit=96):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_prompt(prompt, messages):
    stage_match = re.search(r"<stage name='(\w+)'>\n(.*?)\n</stage>", prompt, re.S)
    found = {"policy": prompt.split("<stage name=")[0].strip(), "stage": stage_match.group(2)}
    for key, tag in TAGS.items():
        match = re.search(rf"(?:^|\n\n)<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)
        found[key] = match.group(1) if match else None
    found["transcript"] = "\n\n".join(f"{m['role']}: {text_of(m)}" for m in messages) if messages else None
    return found, stage_match.group(1)


def working_state(value):
    return json.loads(value[value.index("{") :])


def profile_lines(value):
    return dict(line.split(": ", 1) for line in value.splitlines() if ": " in line)


def summarize(key, value, stage, messages):
    if value is None:
        return None
    if key == "policy":
        return "Role, tone and limits. Identical in every run."
    if key == "stage":
        return f"{stage}: {short(value.split('. ')[0], 84)}"
    if key == "profile":
        lines = profile_lines(value)
        return " · ".join(f"{name}: {lines[name]}" for name in ("entity_type", "member_count") if name in lines)
    if key == "past":
        items = [line for line in value.splitlines() if line.startswith("- ")]
        return f"{len(items)} reviewed. Latest: {short(items[-1][2:], 70)}" if items else "None"
    if key == "working":
        state = working_state(value)
        missing = ", ".join(state["missing_slots"]) or "nothing"
        return (
            f"v{state['version']} · missing: {missing} · awaiting_confirmation: {str(state['awaiting_confirmation']).lower()}"
            f" · confirmed: {str(state['confirmed']).lower()} · {len(state['producer_quotes'])} quotes · {len(state['notes'])} notes"
        )
    if key == "evidence":
        items = json.loads(value)
        counts = {}
        for item in items:
            counts[SOURCE_GROUP[item["source_type"]]] = counts.get(SOURCE_GROUP[item["source_type"]], 0) + 1
        return f"{len(items)} items: " + ", ".join(f"{count} {name.lower()}" for name, count in counts.items())
    if key == "draft":
        draft = json.loads(value)
        return f"{len(draft['claims'])} claims, {len(draft['evidence_gaps'])} evidence gaps"
    if key == "transcript":
        return f"{len(messages)} messages, text only. Latest: {short(text_of(messages[-1]), 56)}"
    return ""


def section_change(key, old, new, stage_old, stage_new, messages_old, messages_new):
    """Say in a few words how one prompt section differs from the previous prompt."""
    if old == new:
        return None
    if new is None:
        return "removed"
    if old is None:
        return "added"
    if key == "stage":
        return f"{stage_old} → {stage_new}"
    if key == "working":
        before, after = working_state(old), working_state(new)
        parts = []
        if before["version"] != after["version"]:
            parts.append(f"v{before['version']} → v{after['version']}")
        filled = [slot for slot in before["missing_slots"] if slot not in after["missing_slots"]]
        if filled:
            parts.append("filled " + ", ".join(filled))
        if before["awaiting_confirmation"] != after["awaiting_confirmation"]:
            parts.append(f"awaiting_confirmation → {str(after['awaiting_confirmation']).lower()}")
        if before["confirmed"] != after["confirmed"]:
            parts.append(f"confirmed → {str(after['confirmed']).lower()}")
        if len(before["notes"]) != len(after["notes"]):
            parts.append(f"notes +{len(after['notes']) - len(before['notes'])}")
        if len(before["producer_quotes"]) != len(after["producer_quotes"]):
            parts.append(f"quotes +{len(after['producer_quotes']) - len(before['producer_quotes'])}")
        if before["profile_facts"] != after["profile_facts"]:
            parts.append(f"staged facts → {len(after['profile_facts'])}")
        return "; ".join(parts) or "changed"
    if key == "profile":
        before, after = profile_lines(old), profile_lines(new)
        parts = [
            f"{name}: {before.get(name, '').split(' (')[0]} → {after.get(name, '').split(' (')[0]}"
            if before.get(name, "").split(" (")[0] != after.get(name, "").split(" (")[0]
            else f"{name} now from: {after[name].split(' (')[1].rstrip(')')}"
            for name in ("entity_type", "member_count")
            if before.get(name) != after.get(name)
        ]
        return "; ".join(parts) or "changed"
    if key == "transcript":
        return f"{messages_old} → {messages_new} messages" if messages_old != messages_new else f"newest message in, oldest out, still {messages_new}"
    if key == "evidence":
        return f"{len(json.loads(old))} → {len(json.loads(new))} items"
    if key == "past":
        count = lambda text: sum(line.startswith("- ") for line in text.splitlines())
        return f"{count(old)} → {count(new)} reviewed"
    return "changed"


contexts, memories, l1s = [], [], []


def intern(table, value):
    table.append(value)
    return len(table) - 1


def build_context(prompt, messages, tools, previous):
    found, stage = parse_prompt(prompt, messages)
    sections = {}
    for key in SECTIONS:
        value = found.get(key)
        old = previous["sections"][key]["text"] if previous else None
        change = section_change(key, old, value, previous and previous["stage"], stage, previous["messages"] if previous else 0, len(messages)) if previous else ("added" if value is not None else None)
        sections[key] = {"on": value is not None, "text": value, "chars": len(value) if value else 0, "summary": summarize(key, value, stage, messages), "change": change}
    return {"stage": stage, "sections": sections, "tools": list(tools), "messages": len(messages), "total": sum(section["chars"] for section in sections.values())}


SLOTS = ["challenge", "onset", "severity", "actions_tried", "tags", "location_checked", "entity_type_checked"]


def summarize_memory(memory, exchange):
    understanding = memory["understanding"]
    evidence = {}
    for item in memory["evidence"].values():
        evidence.setdefault(SOURCE_GROUP[item["source_type"]], []).append({"id": item["evidence_id"], "label": item["source_label"], "fact": short(item["fact"], 120)})
    draft = memory.get("draft")
    return {
        "exchange": exchange,
        "phase": memory["phase"],
        "version": understanding["version"],
        "slots": {
            "challenge": understanding["challenge"],
            "onset": understanding["onset"],
            "severity": understanding["severity"],
            "actions_tried": ", ".join(understanding["actions_tried"]) if understanding["actions_tried"] is not None else None,
            "tags": ", ".join(understanding["tags"]) if understanding["tags"] else None,
            "location_checked": "yes" if understanding["location_checked"] else None,
            "entity_type_checked": "yes" if understanding["entity_type_checked"] else None,
        },
        "quotes": understanding["producer_quotes"],
        "notes": [note["text"] for note in understanding["notes"]],
        "facts": [{"field": fact["field"], "value": fact["value"], "since": fact.get("valid_from")} for fact in understanding["profile_facts"]],
        "shown": [memory["shown_version"], memory["shown_turn"]],
        "confirmed": memory["confirmed_version"],
        "factsApply": memory["confirmed_version"] is not None and memory["confirmed_version"] == understanding["version"],
        "evidence": evidence,
        "evidenceCount": len(memory["evidence"]),
        "draft": {"claims": len(draft["claims"]), "gaps": len(draft["evidence_gaps"])} if draft else None,
        "events": memory["event_count"],
        "saved": memory["saved_events"],
        "pii": [{"turn": flag["turn"], "types": flag["entity_types"]} for flag in memory["pii_flags"]],
        "rev": memory["rev"],
        "committed": bool(memory.get("committed_at")),
    }


def empty_memory(exchange):
    return {
        "exchange": exchange, "phase": "clarify", "version": 0, "slots": dict.fromkeys(SLOTS), "quotes": [], "notes": [], "facts": [],
        "shown": [None, None], "confirmed": None, "factsApply": False, "evidence": {}, "evidenceCount": 0, "draft": None,
        "events": 0, "saved": 0, "pii": [], "rev": 1, "committed": False,
    }


def build_l1(profile_event):
    view = profile_event["view"]
    registered = view["registered"]
    rows = {
        "entity_type": {"registered": registered["entity_type"], "pending": None, "reviewed": None, "since": None, "superseded": []},
        "member_count": {"registered": str(registered["member_count"]), "pending": None, "reviewed": None, "since": None, "superseded": []},
    }
    for fact in sorted(profile_event["facts"], key=lambda item: item["created_at"]):
        row = rows[fact["field"]]
        if fact["status"] == "pending":
            row["pending"] = fact["value"]
        elif fact["superseded_by"]:
            row["superseded"].append(fact["value"])
        else:
            row["reviewed"], row["since"] = fact["value"], fact["valid_from"]
    episodes = {"pending": [], "reviewed": []}
    for episode in profile_event["episodes"]:
        episodes["pending" if episode["status"] == "pending" else "reviewed"].append(short(episode["challenge"], 44))
    pii = sorted({kind for episode in profile_event["episodes"] for kind in episode["pii_entity_types"]})
    return {
        "location": f"{registered['region']}, {registered['country']}", "crops": ", ".join(registered["crops"]), "org": registered["display_name"],
        "rows": rows, "episodes": episodes, "pii": pii, "pending": view["pending_review_count"],
    }


def memory_delta(old, new):
    parts = []
    if old["phase"] != new["phase"]:
        parts.append(f"stage {old['phase']} → {new['phase']}")
    if old["version"] != new["version"]:
        parts.append(f"understanding v{old['version']} → v{new['version']}")
    filled = [slot for slot in SLOTS if new["slots"][slot] and not old["slots"][slot]]
    if filled:
        parts.append("filled " + ", ".join(filled))
    if len(new["quotes"]) != len(old["quotes"]):
        parts.append(f"quotes +{len(new['quotes']) - len(old['quotes'])}")
    if len(new["notes"]) != len(old["notes"]):
        parts.append(f"notes +{len(new['notes']) - len(old['notes'])}")
    if new["facts"] != old["facts"]:
        parts.append("staged " + ", ".join(f"{fact['field']}={fact['value']}" for fact in new["facts"]))
    if new["pii"] != old["pii"]:
        parts.append("PII flag: " + ", ".join(new["pii"][-1]["types"]))
    if new["shown"] != old["shown"]:
        parts.append(f"v{new['shown'][0]} shown in turn {new['shown'][1]}")
    if new["confirmed"] != old["confirmed"]:
        parts.append(f"v{new['confirmed']} confirmed")
    if new["evidenceCount"] != old["evidenceCount"]:
        parts.append(f"ledger +{new['evidenceCount'] - old['evidenceCount']}")
    if new["draft"] and not old["draft"]:
        parts.append(f"draft stored, {new['draft']['claims']} claims")
    if new["events"] != old["events"]:
        parts.append(f"log +{new['events'] - old['events']}")
    if new["rev"] != old["rev"]:
        parts.append(f"saved as revision {new['rev']}")
    return parts


GLOSS = {
    "greet": "Hello, and thank you for your time. I'm the Fair Trade USA Producer Exchange assistant. What has been most difficult for you or your organization lately?",
    "A1p": "The rain has been very irregular and the last banana harvest fell a lot.",
    "A1a": "I understand. Such irregular rain and a harvest that falls a lot is a hard blow. Since when have you noticed the rain being this irregular? And how much did the last harvest fall compared with a normal one?",
    "A2p": "By the way, did our last certification audit go well?",
    "A2a": "I can't answer that question. This assistant has no access to audit results or certification status. For that, it's best to ask your certification contact directly. Back to the rain and the harvest: since when has the rain been this irregular? And how much did the last harvest fall compared with a normal one?",
    "A3p": "I see. The rain problem started two seasons ago and we lost about 30% of the harvest. We've tried watering by hand, but there isn't enough water. The water committee has already asked the municipality for help. Our technician Carlos Ramírez, 312 555 0199, saw it too.",
    "A3a": "Thank you for telling me all this. Losing 30% of the harvest over two seasons is very hard. It also matters that hand-watering isn't enough and that the water committee has already asked the municipality for help. To look for data and examples that fit your case, I want to confirm two things. Are you still working in Piura, Peru? Is Asociación Valle del Chira still a small producer association with about 330 members?",
    "A4p": "Yes, we're in Piura and we're a small producer association.",
    "A4a": "Thank you. Here's what I understood: for two seasons the rain has been very irregular, and in the last banana harvest you lost about 30%. You tried watering by hand, but there isn't enough water. The water committee has asked the municipality for help, and your technician, Carlos Ramírez, also saw the problem. You're in Piura, Peru, and you're Asociación Valle del Chira, a small producer association. Is this correct, or is there anything you'd like to correct or add?",
    "A5p": "Almost. Since this year we're no longer an association, we're a cooperative of about 350 families.",
    "A5a": "Thanks for the correction. Here is the updated summary: for two seasons the rain has been very irregular. In the last banana harvest you lost about 30%. You tried watering by hand, but there isn't enough water. The water committee has asked the municipality for help, and your technician, Carlos Ramírez, also saw the problem. You're in Piura, Peru. Since this year you're a cooperative of about 350 families. Is it right now?",
    "A6p": "Yes, now it's correct.",
    "A6a": "Summary: a draft, labelled not yet verified. Rain 31% below the 10-year average. Extremely high water stress through 2030. Their own 2025 survey, shade-tree project and credit fund. Two peer rainwater-tank projects. Then what the data does not cover, and a closing line that leaves the decision with the cooperative.",
    "A7p": "How much has the rain dropped in our area?",
    "A7a": "Over the last two seasons, rain in Piura was 31% below the 10-year average. That matches what you lived through: the problem started two seasons ago. This figure covers the Piura region, not just your plots. I don't have month-by-month detail or the exact dates of the seasons measured.",
    "C1p": "Hello again. We still have water problems: this year the stream dried up in August and we lost another 20% of the harvest. We tried a small reservoir, but it wasn't enough.",
    "C1a": "Hello again, thanks for telling us. This year the stream dried up in August, you lost another 20% of the banana harvest and the small reservoir wasn't enough. Before looking at what other producers did, I want to confirm two details. Are you still in Piura, Peru? And are you still a cooperative of 350 members?",
    "C2p": "Yes, we're still in Piura and still a cooperative, but we're now 360 families.",
    "C2a": "Thank you. Let me repeat what I understood, so you can correct me if anything is off. At Asociación Valle del Chira you still have water problems. In August this year the stream dried up and you lost another 20% of the banana harvest. You tried a small reservoir, but it wasn't enough. You're still in Piura, Peru, and still a cooperative, now of 360 families. Is that correct, or would you like to change or add something?",
    "C3p": "Yes, that's correct.",
    "C3a": "Summary: a second draft, labelled not yet verified. The same regional data, their survey and what they told us last time, their shade-tree project, then two peer rainwater-tank projects and what the data does not cover.",
}

NARRATION = {
    "A1.arrive": "Working memory starts empty. The message enters the event log, and code compiles the first prompt: policy, the clarify stage, the registered profile and one message. Only one tool is available.",
    "A1.w1": "The model saves what it heard, and code checks each quote against the producer's words. Understanding reaches v1, so this run ends and the prompt is rebuilt from the new state.",
    "A1.reply": "The model asks about what is still missing. The state and all {log} log entries from this turn are saved in one atomic write.",
    "A2.arrive": "The producer asks about a certification audit. The system prompt is identical to the last run. Only the transcript grew, from {m0} message to {m1}.",
    "A2.reply": "The agent declines and returns to the challenge. No tool ran, so the state did not change. The log still records the run.",
    "A3.arrive": "Comprehend scans the message before the model sees it. It flags a name and a phone number, stores only those types and keeps the words unredacted.",
    "A3.w1": "One write fills onset, severity and what was tried. A detail with no slot goes into notes, with the producer's exact words. Understanding reaches v2.",
    "A3.reply": "Saved quotes and notes now appear in the prompt, so the model has no reason to save them twice. An earlier version wasted a whole run here.",
    "A4.arrive": "The producer confirms both details. They still say association here and will correct it on the next turn.",
    "A4.w1": "The last two slots fill. The stage is derived from memory, so it becomes playback. The instructions and tools change, and confirm_understanding appears.",
    "A4.reply": "The model plays back v3. Code records that v3 was shown in turn 4, so it can only be confirmed from a later turn.",
    "A5.arrive": "A correction: since this year the organization is a cooperative of about 350 families. In this prompt awaiting_confirmation is true, because v3 was shown last turn.",
    "A5.w1": "Two profile facts are staged, with exact words and a start date. Understanding reaches v4, which no longer matches the v3 shown, so awaiting_confirmation flips to false.",
    "A5.reply": "The model has to restate before anything can be confirmed. It plays back v4, now with the cooperative and the 350 families.",
    "A6.arrive": "The producer confirms. Shown v4 matches current v4, and this is a later turn, so the confirmation can be accepted. This one short message will run three stages.",
    "A6.w1": "Code accepts. The staged facts now apply to this exchange only, so the profile block reads cooperative. Nothing durable is written. The stage becomes retrieve, with four different tools.",
    "A6.w2": "Four tools read scoped data. The model passes only tags, and code supplies the producer, region and crop. Each result gets a ledger ID. The evidence block takes the system prompt from {c0} to {c1} characters.",
    "A6.w3": "The model submits a draft with {claims} claims. Code checks that every citation points at this ledger, then stores it.",
    "A6.reply": "No model call here. Code renders the draft and takes source names from the ledger, so the model cannot invent a source. It is labelled unverified.",
    "A7.arrive": "A follow-up about the draft. The working memory block leaves the prompt, the draft block enters, and the model has no tools at all.",
    "A7.reply": "The model answers 31% from the evidence. The state does not change. Only the log grows.",
    "commit1": "This is the only path to durable memory. consent_granted=True stands in for the future consent stage. Two facts and one episode are written as pending, with the PII flag and the note.",
    "preview1": "A new exchange would get this prompt. The profile still says association and 330, with no past exchange. Pending records are invisible.",
    "review1": "A reviewer approves each record, seeing the exact words and the PII flag. The facts become part of the profile. The registered record does not change.",
    "C1.arrive": "A return visit with empty working memory. Compared with the last preview, the prompt now starts from reviewed facts, cooperative and 350 since este año, plus a past exchange block.",
    "C1.w1": "One message fills the challenge, onset, severity and what was tried. This state belongs to the new exchange only.",
    "C1.reply": "The agent checks location and entity type against the reviewed profile, which now says cooperative with 350 members.",
    "C2.arrive": "The organization has grown to 360 families. This is the same field that changed last time.",
    "C2.w1": "A member_count fact of 360 is staged. All slots are filled, so the stage becomes playback.",
    "C2.reply": "The model plays back v2, with 360 families.",
    "C3.arrive": "The producer confirms. The same three stages run again.",
    "C3.w1": "Code accepts v2. For this exchange, member_count now reads 360.",
    "C3.w2": "The tools read scoped data again. This time the ledger also holds the reviewed past conversation as evidence, {evidence} items in all.",
    "C3.w3": "The draft cites that past conversation, including the water committee's request from the first visit. A reviewed episode has become evidence.",
    "C3.reply": "Code renders the draft again. One source now reads Conversación anterior, the earlier conversation.",
    "commit2": "The second commit writes the 360 fact and a second episode as pending. The profile still says 350 until a person approves.",
    "review2": "Approving 360 supersedes 350. The older fact stays in the history, marked with what replaced it. Nothing is deleted.",
    "preview2": "The next exchange would start here: cooperative, 360 and two reviewed past exchanges. The registered record still says association and 330.",
}

state = {"context": None, "memory": None, "l1": None, "conv": "A", "bubbles": 0, "calls": [], "callsRun": None, "run": None, "status": "Waiting for the producer"}
beats, runs, chapters, used = [], [], [], set()
BUBBLES = {"A": [], "C": []}
LOGS = {"A": [], "C": []}
first_profile = next(event for event in events if event["type"] == "profile")
state["l1"] = intern(l1s, build_l1(first_profile))
state["memory"] = intern(memories, empty_memory("A"))


def add_chapter(key, label, group):
    chapters.append({"key": key, "label": label, "group": group, "runs": [], "first": len(beats)})


class Beat:
    def __init__(self, key, kind, **values):
        template = NARRATION[key]
        used.add(key)
        self.key, self.kind, self.narration = key, kind, template
        self.values = values
        self.start = dict(state)
        self.moves = []

    def move(self, flows, **changes):
        state.update(changes)
        self.moves.append({"flows": flows, "set": changes})

    def close(self, status=None):
        if status:
            state["status"] = status
        old_memory, new_memory = memories[self.start["memory"]], memories[state["memory"]]
        old_l1, new_l1 = l1s[self.start["l1"]], l1s[state["l1"]]
        prompt_delta = []
        if self.kind == "preview":
            preview = contexts[state["context"]]["sections"]
            lines = profile_lines(preview["profile"]["text"])
            past = sum(line.startswith("- ") for line in (preview["past"]["text"] or "").splitlines())
            prompt_delta = [
                f"entity_type: {lines['entity_type'].split(' (')[0]}",
                f"member_count: {lines['member_count'].split(' (')[0]}",
                f"past exchanges: {past or 'none'}",
            ]
        elif state["context"] is not None and state["context"] != self.start["context"]:
            context = contexts[state["context"]]
            prompt_delta = [f"{SECTION_LABEL[key]}: {context['sections'][key]['change']}" for key in SECTIONS if key != "policy" and context["sections"][key]["change"]]
            old_tools = contexts[self.start["context"]]["tools"] if self.start["context"] is not None else None
            if old_tools != context["tools"]:
                prompt_delta.append("tools: " + (", ".join(context["tools"]) or "none"))
        memory_changes = memory_delta(old_memory, new_memory) if old_memory["exchange"] == new_memory["exchange"] else []
        l1_changes = []
        for field in ("entity_type", "member_count"):
            before, after = old_l1["rows"][field], new_l1["rows"][field]
            if after["pending"] != before["pending"] and after["pending"]:
                l1_changes.append(f"pending {field}={after['pending']}")
            if after["reviewed"] != before["reviewed"] and after["reviewed"]:
                l1_changes.append(f"reviewed {field}={after['reviewed']}")
            if after["superseded"] != before["superseded"]:
                l1_changes.append(f"superseded {field}={after['superseded'][-1]}")
        if len(new_l1["episodes"]["pending"]) > len(old_l1["episodes"]["pending"]):
            l1_changes.append("pending episode")
        if len(new_l1["episodes"]["reviewed"]) > len(old_l1["episodes"]["reviewed"]):
            l1_changes.append("reviewed episode")
        narration = self.narration.format(**self.values) if "{" in self.narration else self.narration
        beats.append(
            {
                "key": self.key,
                "kind": self.kind,
                "where": KIND_LABEL[self.kind],
                "chapter": len(chapters) - 1,
                "narration": narration,
                "start": self.start,
                "moves": self.moves,
                "final": dict(state),
                "delta": {"prompt": prompt_delta, "memory": memory_changes, "l1": l1_changes},
            }
        )


def compile_flows(context, exchange):
    flows = []
    for name in SECTIONS:
        change = context["sections"][name]["change"]
        if name in SOURCE_NODE and change and change != "removed":
            source = SOURCE_NODE[name]
            if name == "profile":
                text = context["sections"]["profile"]["text"] or ""
                source = "mem-facts" if "confirmed in this exchange" in text else "l1-reviewed" if "(reviewed" in text else "l1-registered"
            flows.append({"from": source, "to": f"ctx-{name}", "kind": "read", "label": SECTION_LABEL[name]})
    return flows


def run_context(event, previous):
    return build_context(event["system_prompt"], event["request_messages"], event["tool_names"], previous)


def tool_calls(event):
    new_messages = event["run_messages"][len(event["request_messages"]) :]
    results = {block["toolResult"]["toolUseId"]: block["toolResult"]["status"] for message in new_messages for block in message["content"] if "toolResult" in block}
    calls = []
    for message in new_messages:
        for block in message["content"]:
            if "toolUse" in block:
                use = block["toolUse"]
                inputs = {key: value for key, value in use["input"].items() if key != "reasoning"}
                if use["name"] == "submit_guidance":
                    draft = inputs.get("draft", {})
                    args = f"draft: {len(draft.get('claims', []))} claims, {len(draft.get('evidence_gaps', []))} gaps"
                else:
                    args = " · ".join(f"{key}: {short(json.dumps(value, ensure_ascii=False), 64)}" for key, value in inputs.items()) or "no arguments"
                calls.append({"name": use["name"], "args": args, "reasoning": short(use["input"].get("reasoning", ""), 120), "status": results.get(use["toolUseId"], "success"), "facts": "profile_facts" in inputs, "notes": "notes" in inputs})
    return calls


def add_run(event, label):
    info = {"n": len(runs) + 1, "stage": event["stage"], "input": event["input_tokens"], "output": event["output_tokens"], "seconds": event["seconds"], "chapter": len(chapters) - 1, "tools": event["tools_called"], "label": label, "beat": len(beats)}
    runs.append(info)
    chapters[-1]["runs"].append(info["n"])
    return info["n"] - 1


def segment_turns():
    """Group the flat trace into turns and the steps between them."""
    index = 0
    while index < len(events):
        event = events[index]
        if event["type"] == "turn_start":
            stage_runs, cursor = [], index + 1
            while events[cursor]["type"] == "stage_run":
                stage_runs.append(events[cursor])
                cursor += 1
            yield ("turn", event, stage_runs, events[cursor])
            index = cursor + 1
        else:
            yield ("other", event, None, None)
            index += 1


commit_count = review_count = preview_count = 0
for segment, event, stage_runs, end in segment_turns():
    if segment == "other":
        kind = event["type"]
        if kind == "exchange_start":
            exchange = event["exchange"]
            BUBBLES[exchange].append({"role": "agent", "text": event["greeting"], "gloss": GLOSS["greet"], "label": "Greeting (fixed text)"})
            state["conv"], state["bubbles"] = exchange, 1
            if exchange == "C":
                state["memory"] = intern(memories, empty_memory("C"))
        elif kind == "commit":
            commit_count += 1
            exchange = "A" if commit_count == 1 else "C"
            LOGS[exchange] = event["events"]
            pending_commit = summarize_memory(event["memory"], exchange)
        elif kind == "profile":
            if event["label"] in ("after_commit", "after_second_commit"):
                number = 1 if event["label"] == "after_commit" else 2
                add_chapter(f"commit{number}", "Commit" if number == 1 else "Commit", "first" if number == 1 else "return")
                beat = Beat(f"commit{number}", "commit")
                beat.move(
                    [
                        {"from": "mem-understanding", "to": "l1-pending", "kind": "write", "label": "episode"},
                        {"from": "mem-facts", "to": "l1-pending", "kind": "write", "label": f"{sum(1 for fact in event['facts'] if fact['status'] == 'pending')} " + ("facts" if number == 1 else "fact")},
                    ],
                    memory=intern(memories, pending_commit),
                    l1=intern(l1s, build_l1(event)),
                    calls=[],
                    run=None,
                )
                beat.close("No model call")
            elif event["label"] in ("after_review", "after_second_review"):
                number = 1 if event["label"] == "after_review" else 2
                add_chapter(f"review{number}", "Review", "first" if number == 1 else "return")
                beat = Beat(f"review{number}", "review")
                beat.move([{"from": "l1-pending", "to": "l1-reviewed", "kind": "person", "label": "approve"}], l1=intern(l1s, build_l1(event)), calls=[], run=None)
                beat.close("No model call")
        elif kind == "memory_preview":
            preview_count += 1
            first_prompt = next(item["system_prompt"] for item in events if item["type"] == "stage_run")
            head = first_prompt.split("</stage>\n\n", 1)[0] + "</stage>\n\n"
            context = build_context(head + event["text"], [], ["record_understanding"], contexts[0])
            context["sections"]["transcript"]["change"] = None
            label = "Preview" if preview_count == 1 else "Next chat"
            if preview_count == 2:
                add_chapter("preview2", label, "return")
            beat = Beat(f"preview{preview_count}", "preview")
            flows = [{"from": "l1-registered" if preview_count == 1 else "l1-reviewed", "to": "ctx-profile", "kind": "read", "label": "profile"}]
            if preview_count == 1:
                flows.append({"from": "l1-pending", "to": "ctx-profile", "kind": "blocked", "label": "pending: blocked", "stop": 0.62})
            else:
                flows.append({"from": "l1-reviewed", "to": "ctx-past", "kind": "read", "label": "past exchanges"})
            beat.move(flows, memory=intern(memories, empty_memory("preview")), context=intern(contexts, context), calls=[], run=None)
            beat.close("No model call. Compiled from L1 and not sent")
        continue

    exchange, turn = event["exchange"], event["turn"]
    group = "first" if exchange == "A" else "return"
    label = f"Turn {turn}" if exchange == "A" else f"Return {turn}"
    add_chapter(f"{exchange}{turn}", label, group)
    LOGS[exchange] = end["events"]
    BUBBLES[exchange].append({"role": "producer", "text": event["message"], "gloss": GLOSS[f"{exchange}{turn}p"]})

    first = stage_runs[0]
    previous_context = contexts[state["context"]] if state["context"] is not None else None
    context = run_context(first, previous_context)
    beat = Beat(f"{exchange}{turn}.arrive", "arrive", m0=previous_context["messages"] if previous_context else 0, m1=context["messages"])
    flows = [{"from": "conv-latest", "to": "log-box", "kind": "write", "label": "user_message"}]
    memory_before = summarize_memory(first["memory_before"], exchange)
    if memory_before["pii"] and memory_before["pii"][-1]["turn"] == turn:
        flows.append({"from": "conv-latest", "to": "mem-pii", "kind": "write", "label": "PII flag"})
    beat.move(flows, conv=exchange, bubbles=len(BUBBLES[exchange]), memory=intern(memories, memory_before), calls=[], run=None)
    run_index = add_run(first, label)
    beat.move(compile_flows(context, exchange), context=intern(contexts, context), run=run_index)
    beat.close("Prompt sent to the model")

    writes = 0
    for position, run_event in enumerate(stage_runs):
        calls = tool_calls(run_event)
        after = summarize_memory(run_event["memory_after"], exchange)
        if calls:
            writes += 1
            has_next = position + 1 < len(stage_runs)
            beat = Beat(
                f"{exchange}{turn}.w{writes}",
                "write+rebuild" if has_next else "write",
                claims=after["draft"]["claims"] if after["draft"] else 0,
                evidence=after["evidenceCount"],
                c0=len(run_event["system_prompt"]),
                c1=len(stage_runs[position + 1]["system_prompt"]) if has_next else 0,
            )
            flows = []
            for call in calls:
                source = "data-sources" if call["name"] in DATA_TOOLS else "ctx-model"
                flows.append({"from": source, "to": TOOL_TARGET[call["name"]], "kind": "write", "label": call["name"]})
                if call["facts"]:
                    flows.append({"from": "ctx-model", "to": "mem-facts", "kind": "write", "label": "staged facts"})
                if call["notes"]:
                    flows.append({"from": "ctx-model", "to": "mem-notes", "kind": "write", "label": "note"})
            flows.append({"from": "ctx-model", "to": "log-box", "kind": "write", "label": f"tool_call ×{len(calls)}" if len(calls) > 1 else "tool_call"})
            beat.move(flows, memory=intern(memories, after), calls=calls, callsRun=state["run"])
            if has_next:
                next_context = run_context(stage_runs[position + 1], contexts[state["context"]])
                next_run = add_run(stage_runs[position + 1], label)
                beat.move(compile_flows(next_context, exchange), context=intern(contexts, next_context), run=next_run, calls=calls)
                beat.close("Memory changed, so the prompt was rebuilt")
            else:
                beat.close("Run ended by the write")
        else:
            state["memory"] = intern(memories, after)

    final = summarize_memory(end["memory"], exchange)
    code_rendered = end["reply"].startswith("[Borrador")
    BUBBLES[exchange].append({"role": "agent", "text": end["reply"], "gloss": GLOSS[f"{exchange}{turn}a"], "label": "Rendered by code" if code_rendered else None, "long": code_rendered})
    turn_start_saved = memory_before["saved"]
    beat = Beat(f"{exchange}{turn}.reply", "reply", log=final["events"] - turn_start_saved)
    beat.move(
        [{"from": "mem-draft" if code_rendered else "ctx-model", "to": "conv-latest", "kind": "read" if code_rendered else "model", "label": "render" if code_rendered else "reply"}],
        bubbles=len(BUBBLES[exchange]),
        calls=[],
        run=None if code_rendered else state["run"],
    )
    beat.move([{"from": "conv-latest", "to": "log-box", "kind": "write", "label": "assistant_message"}], memory=intern(memories, final))
    beat.close("No model call. Code rendered this reply" if code_rendered else "Reply sent and the turn saved")

missing = set(NARRATION) - used
assert not missing, missing

log_rows = {}
for exchange, log in LOGS.items():
    rows = []
    for item in log:
        data, kind = item["data"], item["type"]
        if kind in ("user_message", "assistant_message"):
            detail = short(data["text"], 58)
        elif kind == "tool_call":
            detail = data["tool"] + ("" if data["status"] == "success" else f" ({data['status']})")
        elif kind == "stage_run":
            detail = f"{item['phase']}, {data['input_tokens']:,} tokens in, exact prompt kept"
        elif kind == "pii_flag":
            detail = ", ".join(data["entity_types"]) or data["scan_status"]
        else:
            detail = f"episode and {len(data['fact_ids'])} fact(s) to L1"
        rows.append({"seq": item["seq"], "turn": item["turn"], "type": kind, "detail": detail})
    log_rows[exchange] = rows

data = {
    "beats": beats, "runs": runs, "chapters": chapters, "contexts": contexts, "memories": memories, "l1s": l1s, "bubbles": BUBBLES, "logs": log_rows,
    "model": "us.anthropic.claude-opus-5-5",
    "maxInput": max(run["input"] for run in runs),
    "maxChars": max(section["chars"] for context in contexts for section in context["sections"].values()),
    "totals": {"input": sum(run["input"] for run in runs), "output": sum(run["output"] for run in runs)},
}
html = TEMPLATE.read_text(encoding="utf-8").replace("__REPLAY_DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
OUTPUT.write_text(html, encoding="utf-8")
print(f"{len(beats)} scenes, {len(runs)} model runs, {len(chapters)} chapters, {len(html):,} bytes")
print([chapter["label"] for chapter in chapters])
for beat in beats:
    print(f"{beat['key']:12} {beat['kind']:14} P{beat['delta']['prompt']} M{beat['delta']['memory']} L{beat['delta']['l1']}"[:210])
