"""Chat with the agent in a terminal: `producer-exchange --producer P-PE-008 --language es`."""

import argparse

from producer_exchange.config import Settings
from producer_exchange.factory import build_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", default="P-PE-008", help="Stands in for the authenticated session's producer")
    parser.add_argument("--language", default=None, help="Defaults to the producer's registered language")
    args = parser.parse_args()

    service = build_service(Settings.from_env())
    started = service.start_exchange(args.producer, args.language)
    print(f"\nagent> {started.greeting}\n(type /memory to inspect working memory, /quit to leave)\n")
    while True:
        message = input("you> ").strip()
        if message in ("/quit", "/exit"):
            return
        if message == "/memory":
            memory = service.get_working_memory(started.exchange_id, args.producer)
            print(memory.model_dump_json(indent=2, exclude={"transcript", "decision_log"}))
            continue
        if not message:
            continue
        response = service.handle_turn(started.exchange_id, args.producer, message)
        stages = " -> ".join(run.phase.value for run in response.stage_runs) or "code only"
        print(f"\nagent> {response.reply}\n[stage now: {response.phase.value} | ran: {stages}]\n")


if __name__ == "__main__":
    main()
