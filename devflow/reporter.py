from datetime import datetime
from pathlib import Path


MODEL_CONTEXT_LIMIT = 200_000


def generate_report(session_id: str, state: dict, session_path: Path) -> Path:
    report_path = session_path / "report.md"
    report_path.write_text(_render(session_id, state))
    return report_path


def _render(session_id: str, state: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    started = state.get("started_at", "unknown")
    turn_count = state.get("turn_count", 0)
    tool_total = state.get("tool_total", 0)
    tool_errors = state.get("tool_errors", 0)
    token_history = state.get("token_history", [])
    last_input = state.get("last_input_tokens", 0)

    peak_ctx = max((t.get("input_tokens", 0) for t in token_history), default=0)
    avg_out = _avg([t.get("output_tokens", 0) for t in token_history])
    error_pct = f"{tool_errors/tool_total:.0%}" if tool_total else "0%"

    sections = [
        "# DevFlow Monitor — Session Report",
        "",
        f"**Session ID:** `{session_id}`  ",
        f"**Started:** {started}  ",
        f"**Ended:** {now}  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Turns | {turn_count} |",
        f"| Tool calls | {tool_total} |",
        f"| Tool errors | {tool_errors} ({error_pct}) |",
        f"| Peak context | {peak_ctx:,} tokens ({peak_ctx/MODEL_CONTEXT_LIMIT:.0%} of limit) |",
        f"| Final context | {last_input:,} tokens ({last_input/MODEL_CONTEXT_LIMIT:.0%}) |",
        f"| Avg output tokens / turn | {avg_out:.0f} |",
        "",
        "## Health Over Time",
        "",
        *_render_signal_history(state.get("signal_history", [])),
        "",
        "## Anomalies",
        "",
        *_render_anomalies(state.get("anomalies", [])),
        "",
        "## Recommendations",
        "",
        *_render_recommendations(state),
    ]
    return "\n".join(sections)


def _render_signal_history(history: list) -> list:
    if not history:
        return ["_No signal history recorded._"]
    lines = ["| Time | Health | Score | Context | Length Trend | Errors |",
             "|------|--------|-------|---------|--------------|--------|"]
    for entry in history:
        ts = entry.get("ts", "")
        h = entry.get("health", {})
        s = entry.get("scores", {})
        lines.append(
            f"| {ts} | **{h.get('level','?')}** | {h.get('score',0)} "
            f"| {s.get('context','?')} | {s.get('length_trend','?')} "
            f"| {s.get('error_rate','?')} |"
        )
    return lines


def _render_anomalies(anomalies: list) -> list:
    if not anomalies:
        return ["_No anomalies detected._"]
    return [f"- {a}" for a in anomalies]


def _render_recommendations(state: dict) -> list:
    recs = []
    last_input = state.get("last_input_tokens", 0)
    tool_errors = state.get("tool_errors", 0)
    tool_total = state.get("tool_total", 0)
    token_history = state.get("token_history", [])

    ctx_ratio = last_input / MODEL_CONTEXT_LIMIT
    if ctx_ratio >= 0.90:
        recs.append("**Context critical** — over 90% full. Start a new session or run `/compact` immediately.")
    elif ctx_ratio >= 0.75:
        recs.append("**Context pressure** — over 75% full. Consider `/compact` or wrapping up soon.")

    if tool_total and tool_errors / tool_total >= 0.20:
        recs.append("**High error rate** — review recent tool failures and clarify instructions.")

    if len(token_history) >= 6:
        early = _avg([t["output_tokens"] for t in token_history[:3]])
        late  = _avg([t["output_tokens"] for t in token_history[-3:]])
        if early > 0 and (late - early) / early < -0.40:
            recs.append("**Shrinking responses** — output length dropped >40%. Claude may be losing context or truncating answers.")

    if state.get("anomalies"):
        recs.append("**Anomalies were detected** — check the anomalies section above for details.")

    if not recs:
        recs.append("Session looks healthy. No actions required.")

    return [f"- {r}" for r in recs]


def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0.0
