import json
from datetime import datetime
from pathlib import Path
import shutil

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
MAX_SESSIONS = 3


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
    latest = SESSIONS_DIR / "latest"
    if latest.is_symlink():
        latest.unlink()
    latest.symlink_to(session_id)


def append_event(session_id: str, event: dict) -> None:
    path = get_session_path(session_id)
    path.mkdir(parents=True, exist_ok=True)
    with (path / "events.jsonl").open("a") as f:
        f.write(json.dumps(event) + "\n")


def prune_old_sessions(keep: int = MAX_SESSIONS) -> None:
    if not SESSIONS_DIR.exists():
        return
    # Skip the "latest" symlink — rmtree on a symlink raises and would crash the Stop hook
    dirs = sorted(
        (p for p in SESSIONS_DIR.iterdir() if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in dirs[keep:]:
        shutil.rmtree(old)


# Sessions shorter than this are skipped as comparison baselines — a quick
# restart or one-question session would make the next comparison meaningless.
MIN_COMPARISON_TURNS = 5


def load_previous_state(current_session_id: str):
    """State of the most recently active session other than the current one
    that has enough turns to be a meaningful comparison baseline.
    Feeds the end-of-session comparison. Returns None when no qualifying
    session exists (first run, all pruned, or only trivial sessions)."""
    if not SESSIONS_DIR.exists():
        return None
    candidates = [
        p / "state.json"
        for p in SESSIONS_DIR.iterdir()
        if p.is_dir() and not p.is_symlink()
        and p.name != current_session_id
        and (p / "state.json").exists()
    ]
    for f in sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            state = json.loads(f.read_text())
        except Exception:
            continue
        if state.get("turn_count", 0) >= MIN_COMPARISON_TURNS:
            return state
    return None


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
        "response_lengths": [],    # [int] char count of assistant text turns (non-empty only)
        "last_tool_calls": [],     # rolling window of last 20 calls
        "anomalies": [],           # list of strings
        "signal_history": [],      # [{ts, health, scores}]
    }
