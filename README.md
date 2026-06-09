# DevFlow Monitor

A passive Claude Code session health monitor. It hooks into every tool call, scores five health signals in real time, and writes a session report when you're done — without changing how you work.

## Quick start

```bash
git clone https://github.com/daniellek47/devflow-monitor.git
cd devflow-monitor
python3 install.py --global
```

That's it. Open any Claude Code session anywhere on your machine and monitoring starts automatically.

## What you see

A timestamped health line appears in the terminal after every tool call:

```
[16:03:46] turn=  1  ctx=██░░░░░░░░  18%  tokens=36,412  dur=1204ms  health=GOOD(100)
[16:57:32] turn= 38  ctx=█████░░░░░  56%  tokens=111,676  dur=843ms  health=WARN(71)
[16:57:32] WARN     context window pressure (111,676 tokens / 56%)
[16:57:32] CRITICAL response length trending down (change=-52%)
```

When the session ends, a Markdown report is written to `sessions/<session_id>/report.md` inside the devflow-monitor directory. See [`examples/report_0.md`](examples/report_0.md) for a real session — includes a narrative overview, annotated health timeline, anomaly detail with the exact tool input and resolution status, practical recommendations, and a "What We Can Learn" section.

## What it monitors

| Signal | Weight | What it means |
|--------|--------|---------------|
| Context pressure | 35% | Token usage as a fraction of the 200k limit |
| Response length trend | 25% | Whether output tokens are falling over the last 10 turns |
| Tool error rate | 20% | Fraction of tool calls that returned errors |
| Overconfidence | 10% | Certainty words vs. hedging words in Claude's prose |
| Repetition | 10% | Same tool + input called multiple times in a 6-call window |

Overall health score: **GOOD ≥ 80 · WARN 55–79 · CRITICAL < 55**

## Installation

### Global (recommended) — monitors every Claude Code session

```bash
git clone https://github.com/daniellek47/devflow-monitor.git
cd devflow-monitor
python3 install.py --global
```

Writes hooks into `~/.claude/settings.json`. All Claude Code sessions on this machine are monitored from that point on.

### Project-scoped — monitors only one project

Run from inside the project you want to monitor:

```bash
python3 /path/to/devflow-monitor/install.py
```

Writes hooks into `.claude/settings.json` in the current directory.

### Uninstall

```bash
# global
python3 install.py --global --uninstall

# project-scoped
python3 install.py --uninstall
```

## Where reports are stored

All session data is written to the `sessions/` directory inside the devflow-monitor repo, regardless of which project you're working in:

```
devflow-monitor/
└── sessions/
    └── <session-id>/
        ├── state.json    # live state updated on every tool call
        ├── events.jsonl  # raw event log (one line per tool call)
        └── report.md     # written when the session ends
```

## Requirements

Python 3.8+, standard library only. No packages to install.

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
│   ├── post_tool_use.py   # PostToolUse hook — runs after every tool call
│   └── stop.py            # Stop hook — generates the session report
├── sessions/              # runtime data (gitignored)
├── examples/
│   └── report_0.md        # real session report for reference
├── install.py             # registers hooks in Claude Code settings
└── tests/
    ├── test_scorer.py     # 54 boundary-case unit tests
    └── visualize_scorer.py
```
