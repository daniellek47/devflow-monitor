#!/usr/bin/env python3
"""SessionEnd hook — fires when the Claude Code session actually terminates
(/exit, Ctrl+C, /clear). Generates the final report and prints the digest.

Not to be confused with the Stop event, which fires every time Claude
finishes responding to a prompt — that one only refreshes the report."""
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
    output.set_log_file(session_path / "health.log")

    prev_state = session.load_previous_state(sid)
    reporter.generate_report(sid, state, session_path, prev_state)

    output.emit_block(reporter.build_digest(state, prev_state))

    session.prune_old_sessions()

    sys.exit(0)


if __name__ == "__main__":
    main()
