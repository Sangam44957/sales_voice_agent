"""Type-to-chat with the agent in the terminal (no voice needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import agent, config, db  # noqa: E402


def main() -> None:
    config.setup_logging()
    db.init_db()
    s = agent.start_session()
    print("AGENT:", config.CONSENT_GREETING, "\n(type 'quit' to end)")
    while (text := input("YOU: ").strip()) and text.lower() != "quit":
        r = agent.run_turn(s.id, text)
        print(f"AGENT: {r['reply']}\n   [sentiment={r['sentiment']} intent={r['intent']} score={r['score']} tools={r['tools_used']} sources={r['sources']}]")
    print(agent.summarize(s.id))


if __name__ == "__main__":
    main()
