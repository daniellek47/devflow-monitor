#!/usr/bin/env python3
"""Stop hook — fires when a Claude Code session ends. Generates the session report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from devflow import session, signals, reporter, output


def main() -> None:
    payload = signals.parse_hook_payload()
    sig = signals.extract_stop_signals(payload)
    sid = sig["session_id"]

    state = session.load_state(sid)
    if not state.get("turn_count"):
        sys.exit(0)

    session_path = session.get_session_path(sid)
    report_path = reporter.generate_report(sid, state, session_path)

    output.emit("GOOD", "session ended — report written")
    output.emit_report_path(str(report_path))

    session.prune_old_sessions()

    sys.exit(0)


if __name__ == "__main__":
    main()
