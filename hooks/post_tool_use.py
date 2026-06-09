#!/usr/bin/env python3
"""PostToolUse hook — runs after every Claude Code tool call."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from devflow import session, signals, scorer, output


def main() -> None:
    payload = signals.parse_hook_payload()
    if not payload:
        sys.exit(0)

    sig = signals.extract_post_tool_signals(payload)
    sid = sig["session_id"]

    state = session.load_state(sid)
    state["turn_count"] += 1
    state["tool_total"] += 1
    state["last_input_tokens"] = sig["input_tokens"]

    if sig["is_error"]:
        state["tool_errors"] += 1

    state.setdefault("token_history", []).append({
        "turn": state["turn_count"],
        "input_tokens": sig["input_tokens"],
        "output_tokens": sig["output_tokens"],
    })

    state.setdefault("last_tool_calls", []).append({
        "tool_name": sig["tool_name"],
        "tool_input": sig["tool_input"],
    })
    state["last_tool_calls"] = state["last_tool_calls"][-20:]

    # Score all signals
    output_history = [t["output_tokens"] for t in state["token_history"]]
    scores = {
        "context":        scorer.score_context_pressure(sig["input_tokens"]),
        "length_trend":   scorer.score_response_length_trend(output_history),
        "error_rate":     scorer.score_error_rate(state["tool_errors"], state["tool_total"]),
        "overconfidence": _score_text_once(state, sig),
        "repetition":     scorer.score_repetition(
                              state["last_tool_calls"][:-1],
                              {"tool_name": sig["tool_name"], "tool_input": sig["tool_input"]},
                          ),
    }
    health = scorer.overall_health(scores)

    # Record anomalies as structured objects for rich report rendering
    turn_num = state["turn_count"]
    ts_now = datetime.now().strftime("%H:%M:%S")
    if scores["repetition"]["level"] in ("WARN", "CRITICAL"):
        state["anomalies"].append({
            "type": "repetition",
            "turn": turn_num,
            "ts": ts_now,
            "tool_name": sig["tool_name"],
            "tool_input": sig["tool_input"],
            "repeat_count": scores["repetition"]["repeat_count"],
            "score": scores["repetition"]["score"],
        })
    if scores["overconfidence"]["level"] in ("WARN", "CRITICAL"):
        state["anomalies"].append({
            "type": "overconfidence",
            "turn": turn_num,
            "ts": ts_now,
            "certainty_ratio": scores["overconfidence"]["certainty_ratio"],
            "score": scores["overconfidence"]["score"],
        })
    if sig["is_error"]:
        state["anomalies"].append({
            "type": "tool_error",
            "turn": turn_num,
            "ts": ts_now,
            "tool_name": sig["tool_name"],
        })

    state.setdefault("signal_history", []).append({
        "turn": turn_num,
        "ts": ts_now,
        "input_tokens": sig["input_tokens"],
        "health": health,
        "scores": {k: {"score": v["score"], "level": v["level"]} for k, v in scores.items()},
    })

    # Emit live output
    output.emit_status(state["turn_count"], sig["input_tokens"], health, sig["duration_ms"])

    if scores["context"]["level"] in ("WARN", "CRITICAL"):
        output.emit(
            scores["context"]["level"],
            "context window pressure",
            f"{sig['input_tokens']:,} tokens / {scores['context']['ratio']:.0%}",
        )
    if scores["length_trend"]["level"] in ("WARN", "CRITICAL"):
        output.emit(
            scores["length_trend"]["level"],
            "response length trending down",
            f"change={scores['length_trend']['change_pct']}%",
        )
    if scores["error_rate"]["level"] in ("WARN", "CRITICAL"):
        output.emit(
            scores["error_rate"]["level"],
            "high tool error rate",
            f"rate={scores['error_rate']['rate']:.0%}",
        )
    if scores["repetition"]["level"] in ("WARN", "CRITICAL"):
        output.emit(
            scores["repetition"]["level"],
            f"repeated tool call: {sig['tool_name']}",
        )
    if scores["overconfidence"]["level"] in ("WARN", "CRITICAL"):
        output.emit(
            scores["overconfidence"]["level"],
            "overconfidence signal detected",
            f"certainty_ratio={scores['overconfidence']['certainty_ratio']}",
        )

    session.save_state(sid, state)
    session.append_event(sid, {"type": "post_tool_use", "ts": datetime.now().isoformat(), **sig})

    sys.exit(0)


def _score_text_once(state: dict, sig: dict) -> dict:
    """Only score overconfidence once per message to avoid counting the same text multiple times
    when a single message contains several tool calls."""
    mid = sig.get("message_id", "")
    if mid and mid == state.get("last_analyzed_message_id"):
        # Return neutral score — already processed this message's text
        return {"score": 100, "level": "GOOD", "certainty_ratio": 0.0}
    if mid:
        state["last_analyzed_message_id"] = mid
    return scorer.score_overconfidence(sig["response_text"])


if __name__ == "__main__":
    main()
