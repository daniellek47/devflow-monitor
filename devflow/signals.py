import json
import sys


def parse_hook_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def extract_post_tool_signals(payload: dict) -> dict:
    message = payload.get("message", {})
    # usage may be nested under message or at top level depending on Claude Code version
    usage = message.get("usage") or payload.get("usage") or {}

    return {
        "session_id": payload.get("session_id") or "session_unknown",
        "message_id": message.get("id", ""),
        "tool_name": payload.get("tool_name", ""),
        "tool_input": payload.get("tool_input", {}),
        "tool_response": payload.get("tool_response", ""),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "response_text": _extract_text_content(message.get("content", [])),
        "is_error": _is_error(payload),
    }


def extract_stop_signals(payload: dict) -> dict:
    return {
        "session_id": payload.get("session_id") or "session_unknown",
        "stop_hook_active": payload.get("stop_hook_active", False),
    }


def _extract_text_content(content) -> str:
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
            "error:", "exception:", "traceback (most recent", "permission denied",
            "command not found", "no such file",
        ))
    return False
