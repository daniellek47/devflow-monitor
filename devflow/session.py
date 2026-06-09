import json
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


def get_session_path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def load_state(session_id: str) -> dict:
    path = get_session_path(session_id) / "state.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return _initial_state(session_id)


def save_state(session_id: str, state: dict) -> None:
    path = get_session_path(session_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "state.json").write_text(json.dumps(state, indent=2))


def append_event(session_id: str, event: dict) -> None:
    path = get_session_path(session_id)
    path.mkdir(parents=True, exist_ok=True)
    with (path / "events.jsonl").open("a") as f:
        f.write(json.dumps(event) + "\n")


def _initial_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "turn_count": 0,
        "tool_total": 0,
        "tool_errors": 0,
        "last_input_tokens": 0,
        "last_analyzed_message_id": None,
        "token_history": [],       # [{turn, input_tokens, output_tokens}]
        "last_tool_calls": [],     # rolling window of last 20 calls
        "anomalies": [],           # list of strings
        "signal_history": [],      # [{ts, health, scores}]
    }
