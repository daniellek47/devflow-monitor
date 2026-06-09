import json
from datetime import datetime
from pathlib import Path

MODEL_CONTEXT_LIMIT = 200_000

# Discrete score → level for backward compat (legacy signal_history stores plain ints)
_SCORE_TO_LEVEL = {
    "context":        {100: "GOOD", 75: "OK", 40: "WARN", 10: "CRITICAL"},
    "length_trend":   {100: "GOOD", 75: "OK", 50: "WARN", 20: "CRITICAL"},
    "error_rate":     {100: "GOOD", 75: "OK", 50: "WARN", 15: "CRITICAL"},
    "overconfidence": {100: "GOOD", 70: "OK", 30: "WARN"},
    "repetition":     {100: "GOOD", 40: "WARN", 10: "CRITICAL"},
}

# Ordered high-to-low so the first matching threshold is the right bucket
_CONTEXT_GUIDANCE = [
    (0.90, (
        "**Context critical (90%+).** Claude may silently drop early context in its responses. "
        "Start a new session or run `/compact` immediately before continuing."
    )),
    (0.75, (
        "**Context high (75%+).** Quality may start to degrade on complex tasks. "
        "Run `/compact` now and avoid starting new workstreams in this session."
    )),
    (0.50, (
        "**Context above 50%.** Claude is still operating well here, but this is the point where "
        "degradation can start on long sessions. If you're starting a new major task, consider "
        "running `/compact` to summarize history and reclaim space first. "
        "If responses start feeling incomplete, that is the signal to act."
    )),
]

_TREND_GUIDANCE = {
    "falling_fast": (
        "Output length dropped by more than 50% compared to earlier in the session window. "
        "This often means Claude shifted to smaller focused tasks — which is normal for late-session edits — "
        "or is starting to truncate answers due to context pressure. "
        "Review recent responses for completeness. If they feel cut off, try: "
        "'Continue from where you left off' or re-ask with a narrower scope."
    ),
    "falling": (
        "Output length is shorter in the second half of the session window. "
        "This is normal when a session shifts from exploration to execution (writing files → making edits). "
        "It becomes a concern only if response quality also drops."
    ),
}

_REPETITION_GUIDANCE = (
    "A repeated tool call can mean different things:\n\n"
    "- **Intentional retry** — Claude ran the same command again because the first "
    "result was incomplete or needed verification.\n"
    "- **Stuck loop** — Claude is re-running a failing command without changing its "
    "approach. If you see the same error twice, interrupt: "
    "'You've run this command twice — what's blocking you?'\n"
    "- **Coincidence** — the same command was legitimately needed at two different "
    "points in the work.\n\n"
    "The score returned to GOOD(100) the next turn, which means the pattern did not continue."
)


def generate_report(session_id: str, state: dict, session_path: Path) -> Path:
    events = _load_events(session_path)
    report_path = session_path / "report.md"
    report_path.write_text(_render(session_id, state, events))
    return report_path


def _load_events(session_path: Path) -> list:
    events_path = session_path / "events.jsonl"
    if not events_path.exists():
        return []
    events = []
    with events_path.open() as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except Exception:
                pass
    return events


def _render(session_id: str, state: dict, events: list = None) -> str:
    if events is None:
        events = []
    facts = _derive_facts(state)
    sections = [
        _section_header(session_id, state),
        _section_overview(state, facts),
        "---\n",
        _section_summary(state, facts),
        _section_health_timeline(state),
        _section_anomaly_detail(state, facts, events),
        _section_recommendations(state, facts),
        _section_learnings(state, facts),
    ]
    return "\n".join(s for s in sections if s)


# ── derived facts ─────────────────────────────────────────────────────────────

def _derive_facts(state: dict) -> dict:
    token_history = state.get("token_history", [])
    signal_history = state.get("signal_history", [])

    input_series = [t.get("input_tokens", 0) for t in token_history]
    output_series = [t.get("output_tokens", 0) for t in token_history]

    peak_ctx = max(input_series, default=0)
    final_ctx = state.get("last_input_tokens", 0)

    health_levels = [
        e.get("health", {}).get("level", "GOOD")
        if isinstance(e.get("health"), dict) else "GOOD"
        for e in signal_history
    ]
    if "CRITICAL" in health_levels:
        worst_level = "CRITICAL"
    elif "WARN" in health_levels:
        worst_level = "WARN"
    else:
        worst_level = "GOOD"

    final_health = (
        signal_history[-1].get("health", {"score": 100, "level": "GOOD"})
        if signal_history else {"score": 100, "level": "GOOD"}
    )

    # First turn where overall health went WARN or CRITICAL
    first_warn_idx = None
    for i, e in enumerate(signal_history):
        h = e.get("health", {})
        lvl = h.get("level") if isinstance(h, dict) else h
        if lvl in ("WARN", "CRITICAL"):
            first_warn_idx = i
            break

    # First turn where any individual signal went CRITICAL
    first_critical_idx = None
    first_critical_signal = None
    for i, e in enumerate(signal_history):
        for sig, val in e.get("scores", {}).items():
            s = _normalize_score(val)
            if _score_level(s, sig) == "CRITICAL":
                first_critical_idx = i
                first_critical_signal = sig
                break
        if first_critical_idx is not None:
            break

    final_trend_score = None
    if signal_history:
        val = signal_history[-1].get("scores", {}).get("length_trend")
        if val is not None:
            final_trend_score = _normalize_score(val)

    return {
        "peak_ctx": peak_ctx,
        "peak_ctx_pct": peak_ctx / MODEL_CONTEXT_LIMIT,
        "final_ctx": final_ctx,
        "final_ctx_pct": final_ctx / MODEL_CONTEXT_LIMIT,
        "avg_out": _avg(output_series),
        "worst_level": worst_level,
        "final_health": final_health,
        "first_warn_idx": first_warn_idx,
        "first_critical_idx": first_critical_idx,
        "first_critical_signal": first_critical_signal,
        "final_trend_score": final_trend_score,
        "tool_total": state.get("tool_total", 0),
        "tool_errors": state.get("tool_errors", 0),
        "turn_count": state.get("turn_count", 0),
        "has_anomalies": bool(state.get("anomalies")),
    }


# ── section renderers ─────────────────────────────────────────────────────────

def _section_header(session_id: str, state: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    started = state.get("started_at", "unknown")
    return "\n".join([
        "# DevFlow Monitor — Session Report",
        "",
        f"**Session ID:** `{session_id}`  ",
        f"**Started:** {started}  ",
        f"**Ended:** {now}  ",
        "",
    ])


def _section_overview(state: dict, facts: dict) -> str:
    signal_history = state.get("signal_history", [])
    final = facts["final_health"]
    worst = facts["worst_level"]
    final_score = final.get("score", 100) if isinstance(final, dict) else 100
    final_level = final.get("level", "GOOD") if isinstance(final, dict) else "GOOD"
    turns = facts["turn_count"]

    if worst == "GOOD":
        verdict = (
            f"This was a healthy session. All {turns} turns stayed GOOD "
            f"with no degradation signals triggered."
        )
    elif final_level == "GOOD" and worst == "WARN":
        verdict = (
            f"This session dipped to WARN but finished healthy. "
            f"After {turns} turns it ended at GOOD({final_score}) — "
            f"warning signals were transient, not persistent."
        )
    elif final_level == "WARN":
        verdict = (
            f"This session ended in WARN territory (score {final_score}) after "
            f"{turns} turns. No intervention was taken during the session — "
            f"see Recommendations for next steps."
        )
    else:
        verdict = (
            f"This session ended CRITICAL (score {final_score}) after {turns} turns. "
            f"Session health degraded and was not recovered before the session ended."
        )

    interesting = _find_interesting_event(signal_history, facts)
    fwd = _forward_recommendation(facts)

    lines = ["## Session Overview", "", verdict]
    if interesting:
        lines += ["", interesting]
    if fwd:
        lines += ["", fwd]
    lines += [""]
    return "\n".join(lines)


def _find_interesting_event(signal_history: list, facts: dict) -> str:
    if not signal_history:
        return ""

    # First choice: first time health went WARN — explains why and what drove it
    if facts["first_warn_idx"] is not None:
        idx = facts["first_warn_idx"]
        e = signal_history[idx]
        ts = e.get("ts", "")
        h = e.get("health", {})
        scores = e.get("scores", {})
        health_score = h.get("score", 0) if isinstance(h, dict) else h

        drivers = []
        ctx_score = _normalize_score(scores.get("context", 100))
        lt_score = _normalize_score(scores.get("length_trend", 100))
        if ctx_score < 100:
            drivers.append(f"context pressure ({_score_level(ctx_score, 'context')}, score {ctx_score})")
        if lt_score < 100:
            drivers.append(f"falling response length ({_score_level(lt_score, 'length_trend')}, score {lt_score})")

        driver_text = " combined with ".join(drivers) if drivers else "multiple signals"
        return (
            f"**Notable moment ({ts}):** Health first entered WARN territory (score {health_score}), "
            f"driven by {driver_text}. "
            f"This is the point where the session crossed from normal monitoring into "
            f"action-recommended territory."
        )

    # Second choice: first CRITICAL individual signal (health may still be GOOD due to weighting)
    if facts["first_critical_idx"] is not None:
        idx = facts["first_critical_idx"]
        e = signal_history[idx]
        ts = e.get("ts", "")
        sig = facts["first_critical_signal"] or "unknown"
        weight = {"context": "35%", "length_trend": "25%", "error_rate": "20%",
                  "overconfidence": "10%", "repetition": "10%"}.get(sig, "?")
        return (
            f"**Notable moment ({ts}):** The {sig.replace('_', ' ')} signal hit CRITICAL "
            f"for the first time. Overall health stayed GOOD because this signal carries "
            f"{weight} of the total score — the weighted scoring absorbed the hit. "
            f"This is the system working as designed."
        )

    return ""


def _forward_recommendation(facts: dict) -> str:
    pct = facts["final_ctx_pct"]
    if pct >= 0.90:
        return "**Next step:** Start a new session or run `/compact` immediately — context is critical."
    if pct >= 0.75:
        return "**Next step:** Run `/compact` before continuing — context is high."
    if pct >= 0.50:
        return (
            f"**Next step:** Context is at {pct:.0%}. You can continue, but keep tasks focused. "
            f"For a new major workstream, consider `/compact` first to reclaim space."
        )
    if facts["worst_level"] == "GOOD":
        return "**Next step:** Session was clean — no action needed before continuing."
    return ""


def _section_summary(state: dict, facts: dict) -> str:
    turn_count = facts["turn_count"]
    tool_total = facts["tool_total"]
    tool_errors = facts["tool_errors"]
    peak_ctx = facts["peak_ctx"]
    final_ctx = facts["final_ctx"]
    avg_out = facts["avg_out"]
    error_pct = f"{tool_errors/tool_total:.0%}" if tool_total else "0%"

    return "\n".join([
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Turns | {turn_count} |",
        f"| Tool calls | {tool_total} |",
        f"| Tool errors | {tool_errors} ({error_pct}) |",
        f"| Peak context | {peak_ctx:,} tokens ({peak_ctx/MODEL_CONTEXT_LIMIT:.0%} of limit) |",
        f"| Final context | {final_ctx:,} tokens ({final_ctx/MODEL_CONTEXT_LIMIT:.0%}) |",
        f"| Avg output tokens / turn | {avg_out:.0f} |",
        "",
    ])


def _section_health_timeline(state: dict) -> str:
    history = state.get("signal_history", [])
    if not history:
        return "## Health Over Time\n\n_No signal history recorded._\n"

    lines = [
        "## Health Over Time",
        "",
        "_Scores 0–100. GOOD ≥ 80 · WARN 55–79 · CRITICAL < 55. "
        "Signal weights: Context 35%, Trend 25%, Errors 20%, Confidence 10%, Repetition 10%._",
        "",
        "| Time | Health | Context | Trend | Errors | Notes |",
        "|------|--------|---------|-------|--------|-------|",
    ]

    prev_ctx = 100
    prev_lt = 100
    prev_rep = 100
    prev_health_level = "GOOD"

    for entry in history:
        ts = entry.get("ts", "")
        h = entry.get("health", {})
        scores = entry.get("scores", {})

        ctx_score = _normalize_score(scores.get("context", 100))
        lt_score = _normalize_score(scores.get("length_trend", 100))
        err_score = _normalize_score(scores.get("error_rate", 100))
        rep_score = _normalize_score(scores.get("repetition", 100))
        health_score = h.get("score", 100) if isinstance(h, dict) else int(h)
        health_level = h.get("level", "GOOD") if isinstance(h, dict) else "GOOD"

        # Show level label only when not GOOD
        def cell(score, key):
            lvl = _score_level(score, key)
            return f"{score}" if lvl == "GOOD" else f"{score} ({lvl})"

        note = _timeline_note(
            ctx_score, lt_score, err_score, rep_score,
            prev_ctx, prev_lt, prev_rep, health_level, prev_health_level
        )

        prev_ctx, prev_lt, prev_rep, prev_health_level = ctx_score, lt_score, rep_score, health_level

        lines.append(
            f"| {ts} | **{health_level}**({health_score}) "
            f"| {cell(ctx_score, 'context')} "
            f"| {cell(lt_score, 'length_trend')} "
            f"| {cell(err_score, 'error_rate')} "
            f"| {note} |"
        )

    lines += [""]
    return "\n".join(lines)


def _timeline_note(ctx, lt, err, rep, prev_ctx, prev_lt, prev_rep, health_level, prev_health_level) -> str:
    notes = []

    if rep < prev_rep and rep < 100:
        lvl = _score_level(rep, "repetition")
        notes.append(f"repetition {lvl} ({rep}) — explains health dip")
    elif prev_rep < 100 and rep == 100:
        notes.append("repetition resolved")

    if ctx < prev_ctx:
        if prev_ctx == 100 and ctx == 75:
            notes.append("context crossed 50% threshold")
        elif prev_ctx >= 40 and ctx == 40:
            notes.append("context crossed 75%")
        elif ctx == 10:
            notes.append("context critical (90%+)")

    if lt < prev_lt:
        if lt == 20:
            notes.append("responses shortening fast (>50% drop)")
        elif lt == 50:
            notes.append("response length declining")
    elif lt > prev_lt and prev_lt < 100:
        notes.append("response length recovering")

    if health_level in ("WARN", "CRITICAL") and prev_health_level == "GOOD":
        notes.append(f"→ first {health_level}")
    elif health_level == "GOOD" and prev_health_level in ("WARN", "CRITICAL"):
        notes.append("← recovered to GOOD")

    return "; ".join(notes) if notes else ""


# ── anomaly detail ─────────────────────────────────────────────────────────────

def _section_anomaly_detail(state: dict, facts: dict, events: list) -> str:
    anomalies = state.get("anomalies", [])
    signal_history = state.get("signal_history", [])

    lines = ["## Anomaly Detail", ""]

    if not anomalies:
        lines += ["_No anomalies detected._", ""]
        return "\n".join(lines)

    for anomaly in anomalies:
        if isinstance(anomaly, dict):
            lines += _render_rich_anomaly(anomaly, signal_history)
        else:
            lines += _render_legacy_anomaly(str(anomaly), signal_history, events)
        lines += [""]

    return "\n".join(lines)


def _render_rich_anomaly(a: dict, signal_history: list) -> list:
    atype = a.get("type", "unknown")
    turn = a.get("turn", "?")
    ts = a.get("ts", "")

    if atype == "repetition":
        tool_name = a.get("tool_name", "?")
        tool_input = a.get("tool_input", {})
        repeat_count = a.get("repeat_count", 2)
        score = a.get("score", 40)
        rep_lvl = _score_level(score, "repetition")
        health_cost = round((100 - score) * 0.10)

        input_str = _format_tool_input(tool_name, tool_input)
        resolved, resolved_ts = _check_repetition_resolved(turn, signal_history)

        lines = [
            f"### Repeated tool call — turn {turn} ({ts})",
            "",
            f"**Tool:** `{tool_name}`  ",
            f"**Repeat count:** {repeat_count}× in the last 6 calls  ",
            f"**Repetition score:** {score} ({rep_lvl}) — WARN at 2×, CRITICAL at 3×  ",
            f"**Impact:** reduced overall health by {health_cost} points (repetition weight is 10%)",
            "",
            "**Exact command:**",
            "```",
            input_str[:600],
            "```",
            "",
        ]
        if resolved:
            lines.append(
                f"**Resolution:** Resolved at {resolved_ts} — "
                f"the repetition score returned to GOOD(100) the next turn. "
                f"The command was not repeated again."
            )
        else:
            lines.append("**Resolution:** Not clearly resolved within the session window.")

        lines += ["", "**What this means:**", "", _REPETITION_GUIDANCE]
        return lines

    if atype == "overconfidence":
        certainty_ratio = a.get("certainty_ratio", 0)
        return [
            f"### Overconfidence signal — turn {turn} ({ts})",
            "",
            f"**Certainty ratio:** {certainty_ratio:.0%} of hedge/certainty vocabulary was certainty words  ",
            "_(Threshold: >80% certainty triggers WARN)_",
            "",
            "This means Claude's prose at this turn used more 'definitely / obviously / certainly' "
            "than 'might / probably / worth checking'. Re-read the output from this turn and check "
            "whether the confident assertions were actually correct. A single flag is low signal; "
            "it becomes meaningful if it recurs across multiple turns.",
        ]

    if atype == "tool_error":
        tool_name = a.get("tool_name", "?")
        return [
            f"### Tool error — turn {turn} ({ts})",
            "",
            f"**Tool:** `{tool_name}` returned an error.",
            "",
            "Check `events.jsonl` for the full error message. A one-off error (file not found, "
            "then created) can be ignored. Recurring errors contribute to the error rate score "
            "(threshold: WARN at 10%, CRITICAL at 40%).",
        ]

    return [f"### Anomaly (type: {atype}) — turn {turn}", ""]


def _render_legacy_anomaly(anomaly_str: str, signal_history: list, events: list) -> list:
    """Handle string anomalies from pre-structured sessions, enriched from events.jsonl."""
    import re

    lines = [f"### {anomaly_str}", ""]

    if "repeated tool call" in anomaly_str:
        m_turn = re.search(r"turn (\d+)", anomaly_str)
        m_tool = re.search(r"'([^']+)'", anomaly_str)
        m_count = re.search(r"\((\d+)x", anomaly_str)

        turn = int(m_turn.group(1)) if m_turn else None
        tool_name = m_tool.group(1) if m_tool else "unknown"
        repeat_count = int(m_count.group(1)) if m_count else 2
        score = 40 if repeat_count == 2 else 10
        health_cost = round((100 - score) * 0.10)

        event = events[turn - 1] if events and turn and turn <= len(events) else None
        if event:
            tool_input = event.get("tool_input", {})
            input_str = _format_tool_input(tool_name, tool_input)
            lines += [
                f"**Tool:** `{tool_name}`  ",
                f"**Repeat count:** {repeat_count}× in the last 6 calls  ",
                f"**Repetition score:** {score} (WARN) — WARN triggers at 2×, CRITICAL at 3×  ",
                f"**Impact:** reduced overall health by {health_cost} points (repetition weight is 10%)",
                "",
                "**Exact command:**",
                "```",
                input_str[:600],
                "```",
                "",
            ]
        else:
            lines += [
                f"**Tool:** `{tool_name}`  ",
                f"**Repeat count:** {repeat_count}× in the last 6 calls",
                "",
                "_Tool input not available — check `events.jsonl` for the full command._",
                "",
            ]

        resolved, resolved_ts = _check_repetition_resolved(turn, signal_history)
        if resolved:
            lines.append(
                f"**Resolution:** Resolved at {resolved_ts} — "
                f"repetition score returned to GOOD(100) the next turn. "
                f"The command was not repeated again."
            )
        else:
            lines.append("**Resolution:** Pattern continued or could not be determined from available data.")

        lines += ["", "**What this means:**", "", _REPETITION_GUIDANCE]

    return lines


def _check_repetition_resolved(turn, signal_history: list) -> tuple:
    """Return (resolved, resolved_ts). Resolved = repetition back to 100 in the next turn."""
    if turn is None or not signal_history:
        return False, ""

    # Entries may have explicit "turn" field (new format) or rely on list index (legacy)
    target_idx = None
    for i, e in enumerate(signal_history):
        entry_turn = e.get("turn")
        if entry_turn is not None:
            if entry_turn == turn:
                target_idx = i
                break
        else:
            if i == turn - 1:
                target_idx = i
                break

    if target_idx is None and 0 < turn <= len(signal_history):
        target_idx = turn - 1

    if target_idx is None:
        return False, ""

    next_idx = target_idx + 1
    if next_idx < len(signal_history):
        rep = _normalize_score(signal_history[next_idx].get("scores", {}).get("repetition", 100))
        if rep == 100:
            return True, signal_history[next_idx].get("ts", "next turn")

    return False, ""


def _format_tool_input(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        return f"# {desc}\n{cmd}" if desc else cmd
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path", str(tool_input)[:300])
    return str(tool_input)[:300]


# ── recommendations ───────────────────────────────────────────────────────────

def _section_recommendations(state: dict, facts: dict) -> str:
    recs = []
    final_pct = facts["final_ctx_pct"]

    for threshold, text in _CONTEXT_GUIDANCE:
        if final_pct >= threshold:
            recs.append(text)
            break

    ft = facts["final_trend_score"]
    if ft == 20:
        recs.append(f"**Response length fell sharply.**\n\n  {_TREND_GUIDANCE['falling_fast']}")
    elif ft == 50:
        recs.append(f"**Response length declining.**\n\n  {_TREND_GUIDANCE['falling']}")

    if facts["tool_errors"] and facts["tool_total"]:
        if facts["tool_errors"] / facts["tool_total"] >= 0.20:
            recs.append("**High error rate** — review recent tool failures and clarify instructions.")

    if facts["has_anomalies"]:
        recs.append("**Anomalies were detected** — see Anomaly Detail above for context and guidance.")

    if not recs:
        recs.append("Session looks healthy — no actions required.")

    lines = ["## Recommendations", ""]
    for r in recs:
        lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines)


# ── learnings ─────────────────────────────────────────────────────────────────

def _section_learnings(state: dict, facts: dict) -> str:
    signal_history = state.get("signal_history", [])
    anomalies = state.get("anomalies", [])

    observations = []
    peak_pct = facts["peak_ctx_pct"]

    first_warn_ts = (
        signal_history[facts["first_warn_idx"]].get("ts", "")
        if facts["first_warn_idx"] is not None else ""
    )

    if 0.50 <= peak_pct < 0.75:
        suffix = f" — as happened here at {first_warn_ts}" if first_warn_ts else ""
        observations.append(
            f"**Context usage peaked at {peak_pct:.0%} — the yellow zone.**  \n"
            f"This is the range where Claude still performs well, but the context score drops from "
            f"GOOD(100) to OK(75). At 35% weight, that alone costs 8.75 points off the health score "
            f"(35 × (1 − 75/100) = 8.75). Combined with any other declining signal, "
            f"it's enough to push health out of the top band{suffix}."
        )
    elif peak_pct >= 0.75:
        observations.append(
            f"**Context peaked at {peak_pct:.0%} — significant pressure.**  \n"
            f"Context is the heaviest signal (35% weight). At this level it pulls the health score "
            f"down sharply and makes it harder for other good signals to compensate."
        )

    if facts["first_critical_idx"] is not None and facts["first_critical_signal"] == "length_trend":
        idx = facts["first_critical_idx"]
        ts = signal_history[idx].get("ts", "")
        h = signal_history[idx].get("health", {})
        health_at_critical = h.get("score", 0) if isinstance(h, dict) else int(h)
        health_level_at_critical = h.get("level", "GOOD") if isinstance(h, dict) else "GOOD"
        observations.append(
            f"**Response length went CRITICAL ({ts}) while health stayed {health_level_at_critical}({health_at_critical}).**  \n"
            f"This shows the weighted scoring system working as designed. "
            f"Length trend is 25% weight. At score 20 (CRITICAL), it contributes 20×0.25 = 5 points "
            f"to the weighted sum, versus the maximum of 100×0.25 = 25 — a 20-point drag. "
            f"The other signals held the overall score at {health_at_critical}. "
            f"Only when context pressure was also elevated did the combination push health to WARN."
        )

    if anomalies:
        first = anomalies[0]
        if isinstance(first, dict) and first.get("type") == "repetition":
            turn_num = first.get("turn", "?")
            rep_score = first.get("score", 40)
        else:
            import re
            m = re.search(r"turn (\d+)", str(first))
            turn_num = int(m.group(1)) if m else "?"
            rep_score = 40

        health_cost = round((100 - rep_score) * 0.10)
        # Look up actual health before and at the anomaly turn
        before_health = after_health = None
        if isinstance(turn_num, int) and turn_num <= len(signal_history):
            if turn_num >= 2:
                h = signal_history[turn_num - 2].get("health", {})
                before_health = h.get("score") if isinstance(h, dict) else None
            h = signal_history[turn_num - 1].get("health", {})
            after_health = h.get("score") if isinstance(h, dict) else None

        drop_text = (
            f"Health dropped from {before_health} to {after_health}"
            if before_health is not None and after_health is not None
            else "Health dipped slightly"
        )
        observations.append(
            f"**The repetition anomaly (turn {turn_num}) shows the 10% weight doing its job.**  \n"
            f"A WARN-level repetition (score {rep_score}) at 10% weight costs "
            f"(100−{rep_score})×0.10 = {health_cost} points. "
            f"{drop_text} — visible in the table, but not alarming. "
            f"This is intentional: one repeated command is a flag, not an emergency. "
            f"Three consecutive repeats (score 10, CRITICAL) would cost only 9 points — "
            f"still not a session killer on its own. The signal is designed as a nudge to investigate."
        )

    if facts["worst_level"] == "WARN" and facts["final_health"].get("level") == "GOOD":
        observations.append(
            f"**The session dipped to WARN but self-corrected.**  \n"
            f"This is the most common healthy outcome for longer sessions: signals briefly enter "
            f"warning territory as the session shifts task type, then recover. "
            f"The monitor's job here is to confirm the recovery happened — not just flag the dip. "
            f"If the session had ended at the WARN point instead of continuing, "
            f"the report would look significantly different."
        )

    if not observations:
        observations.append("No significant signals detected in this session.")

    lines = ["---", "", "## What We Can Learn From This Session", ""]
    for obs in observations:
        lines.append(obs)
        lines.append("")
    return "\n".join(lines)


# ── utilities ─────────────────────────────────────────────────────────────────

def _normalize_score(val) -> int:
    if isinstance(val, dict):
        return val.get("score", 100)
    return int(val) if val is not None else 100


def _score_level(score: int, signal_key: str) -> str:
    return _SCORE_TO_LEVEL.get(signal_key, {}).get(score, "GOOD")


def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0.0
