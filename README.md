# DevFlow Monitor

A passive Claude Code session health monitor that observes hook events, scores health signals, detects anomalies, and generates a session report — without touching your workflow.

## What it does

DevFlow Monitor hooks into Claude Code's event system and watches each tool call as it happens. It tracks:

- **Context window pressure** — how close you are to the model's token limit
- **Response length trend** — whether answers are getting shorter over time (a sign of context degradation)
- **Tool error rate** — frequency of failed tool calls
- **Overconfidence signals** — heuristic detection of certainty language without hedging
- **Repetition / stuck loops** — same tool being called repeatedly with the same inputs

Every tool call emits a timestamped health line to stderr. When the session ends, a Markdown report is written to `sessions/<session_id>/report.md`.

## How it works

```
Claude Code tool call
        │
        ▼
  PostToolUse hook ──► reads session state
                   ──► scores signals (heuristics only, no extra API calls)
                   ──► emits timestamped line to stderr
                   ──► writes updated state to sessions/<id>/state.json

  Stop hook        ──► reads all state
                   ──► writes sessions/<id>/report.md
```

All signal evaluation is done with local heuristics — no extra API calls, no external services.

## Output

Live output (stderr):

```
[10:32:01] turn=  1  ctx=██░░░░░░░░ 18%  tokens=36,412  health=GOOD(94)
[10:32:15] turn=  2  ctx=███░░░░░░░ 24%  tokens=48,201  health=GOOD(91)
[10:45:03] turn= 12  ctx=████████░░ 78%  tokens=156,882  health=WARN(61)
[10:45:03] WARN     context window pressure (156,882 tokens / 78%)
[10:45:03] WARN     response length trending down (change=-31%)
```

Final report (`sessions/<id>/report.md`): see [`examples/report_0.md`](examples/report_0.md) for a real session — includes a narrative overview, annotated health timeline, anomaly detail with the exact tool input and resolution status, practical recommendations, and a "What We Can Learn" section.

## Setup

Hooks are project-scoped and configured in `.claude/settings.json`. Run the installer to register them:

```bash
python3 install.py
```

This writes the hook commands with absolute paths into `.claude/settings.json`.

## Project structure

```
devflow-monitor/
├── devflow/
│   ├── session.py      # per-session state (read/write JSON)
│   ├── signals.py      # extract signals from hook payloads
│   ├── scorer.py       # heuristic scoring engine
│   ├── output.py       # formatted stderr output
│   └── reporter.py     # Markdown report generator
├── hooks/
│   ├── post_tool_use.py   # PostToolUse hook
│   └── stop.py            # Stop hook → generates report
├── sessions/              # runtime session state + reports (gitignored)
├── install.py             # registers hooks in .claude/settings.json
└── tests/
    └── test_scorer.py
```

## Requirements

Python 3.8+, stdlib only. No dependencies to install.
