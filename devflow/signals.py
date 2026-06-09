import json
import sys
from pathlib import Path


def parse_hook_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def extract_post_tool_signals(payload: dict) -> dict:
    tool_use_id = payload.get("tool_use_id", "")
    transcript_path = payload.get("transcript_path", "")

    usage, response_text, model = _read_transcript(transcript_path, tool_use_id)

    # Total context window usage = all token buckets combined (cached + new + cache writes)
    total_input = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )

    return {
        "session_id": payload.get("session_id") or "session_unknown",
        "tool_use_id": tool_use_id,
        "tool_name": payload.get("tool_name", ""),
        "tool_input": payload.get("tool_input", {}),
        "tool_response": payload.get("tool_response", ""),
        "input_tokens": total_input,
        "output_tokens": usage.get("output_tokens", 0),
        "response_text": response_text,
        "model": model,
        "duration_ms": int(payload.get("duration_ms") or 0),
        "is_error": _is_error(payload),
    }


def extract_stop_signals(payload: dict) -> dict:
    return {
        "session_id": payload.get("session_id") or "session_unknown",
        "stop_hook_active": payload.get("stop_hook_active", False),
    }


def _read_transcript(transcript_path: str, tool_use_id: str) -> tuple:
    """Return (usage_dict, response_text, model) from the transcript entry
    whose content contains tool_use_id. Falls back to the last assistant entry."""
    if not transcript_path:
        return {}, "", ""
    path = Path(transcript_path)
    if not path.exists():
        return {}, "", ""

    try:
        last_match = None
        last_assistant = None
        with path.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", {})
                last_assistant = msg
                if tool_use_id and any(
                    b.get("id") == tool_use_id
                    for b in msg.get("content", [])
                    if isinstance(b, dict)
                ):
                    last_match = msg

        msg = last_match or last_assistant or {}
        usage = msg.get("usage", {})
        model = msg.get("model", "")
        text = _extract_text(msg.get("content", []))
        return usage, text, model

    except Exception:
        return {}, "", ""


def _extract_text(content) -> str:
    if not isinstance(content, list):
        return ""
    return " ".join(
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def _is_error(payload: dict) -> bool:
    resp = payload.get("tool_response", "")
    if isinstance(resp, dict):
        return bool(resp.get("is_error"))
    if isinstance(resp, str):
        low = resp.lower()
        return any(kw in low for kw in (
            "error:", "exception:", "traceback (most recent",
            "permission denied", "command not found", "no such file",
        ))
    return False
