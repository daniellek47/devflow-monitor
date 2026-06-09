# DevFlow Monitor

A passive Claude Code session health monitor. It hooks into every tool call, scores five health signals in real time, and writes a session report when you're done — without changing how you work.

---

## Quick start (new user)

Clone it anywhere on your machine. It is completely independent of the projects you work on.

```bash
git clone https://github.com/daniellek47/devflow-monitor.git ~/devflow-monitor
cd ~/devflow-monitor
python3 install.py --global
```

That's it. No dependencies. Python 3.8+ only.

`--global` registers the hooks in `~/.claude/settings.json` so every Claude Code session on your machine is monitored automatically, regardless of which project you open.

---

## Use

Open a Claude Code session in any project directory — devflow-monitor does not need to be anywhere near it:

```bash
cd ~/projects/my-app
claude
```

After every tool call, a health line appears in the Claude Code terminal:

```
[16:03:46] turn=  1  ctx=██░░░░░░░░  18%  tokens=36,412  dur=340ms  health=GOOD(100)
[16:57:32] turn= 38  ctx=█████░░░░░  56%  tokens=111,676  dur=512ms  health=WARN(71)
[16:57:32] WARN     context window pressure (111,676 tokens / 56%)
[16:57:32] CRITICAL response length trending down (change=-52%)
```

- **turn** — number of tool calls so far in this session
- **ctx** — context window usage as a bar and percentage of the 200k token limit; at 90%+ Claude starts dropping early context

When you end the session (`/exit` or Ctrl+C), the full report is written automatically:

```
[17:18:30] REPORT   ~/devflow-monitor/sessions/<session-id>/report.md
```

To read it:

```bash
cat ~/devflow-monitor/sessions/<session-id>/report.md
```

See [`examples/report_0.md`](examples/report_0.md) for a real session report — includes a narrative overview with verdict and forward recommendation, an annotated health timeline explaining every score change, full anomaly detail with the exact tool input and resolution status, practical guidance per signal, and a "What We Can Learn" section.

---

## Watching health from a second terminal

Health lines also write to a plain-text log file (`health.log`) inside the session directory. Open a second terminal and run:

```bash
cd ~/devflow-monitor
tail -f sessions/$(ls -t sessions/ | head -1)/health.log
```

This follows the most recent session in real time, no ANSI codes, no TUI. Useful when the Claude Code terminal is in another window or when you want to share the stream with someone watching over your shoulder.

To follow a specific session by ID:

```bash
tail -f ~/devflow-monitor/sessions/<session-id>/health.log
```

---

## What it monitors

| Signal | Weight | What triggers a warning |
|--------|--------|------------------------|
| Context pressure | 35% | Token usage above 50% of the 200k limit |
| Response length trend | 25% | Output tokens falling more than 25% over the last 10 turns |
| Tool error rate | 20% | More than 10% of tool calls returning errors |
| Overconfidence | 10% | Certainty words dominating over hedging words in Claude's prose |
| Repetition | 10% | Same tool + input called 2+ times in a 6-call window |

**Overall health: GOOD ≥ 80 · WARN 55–79 · CRITICAL < 55**

---

## Session data

All data is written to `~/devflow-monitor/sessions/`, regardless of which project you are working in:

```
~/devflow-monitor/sessions/<session-id>/
├── state.json    # live state, updated after every tool call
├── events.jsonl  # raw event log, one JSON line per tool call
├── health.log    # plain-text health lines (tail -f this)
└── report.md     # full report, written when the session ends
```

The last 10 sessions are kept. Older ones are deleted automatically when a session ends.

---

## Compatibility

**Plans and context window:** The 200k token limit applies to all current Claude plans (Free, Pro, Max, Team, Enterprise) — it is a model property, not a subscription feature. The monitor works identically across plans. If you ever need to adjust the limit (e.g., for a different model), change `MODEL_CONTEXT_LIMIT` in `devflow/scorer.py` line 3.

**Operating system:**
- **Linux / macOS / WSL2**: fully supported. Health lines write to `/dev/tty` and appear live in the Claude Code terminal.
- **Windows (native, no WSL)**: health lines fall back to stderr, which Claude Code's TUI discards. The `health.log` file and session report still work — but you won't see live output inside the Claude Code terminal. Use WSL2 for the full experience.

**Python:** 3.8+, standard library only. No pip install needed.

---

## Uninstall

```bash
cd ~/devflow-monitor
python3 install.py --global --uninstall
```

---

## Project-scoped install (optional)

To monitor only one specific project instead of all sessions:

```bash
cd ~/projects/my-app
python3 ~/devflow-monitor/install.py
```

This writes the hooks into `.claude/settings.json` in that project directory only.

---

## How it works

Claude Code calls the hooks as subprocesses after every tool use. There is no background daemon — each invocation is an isolated Python process that runs for under a second.

The `PostToolUse` hook receives a JSON payload on stdin containing the tool name, input, response, and a path to the session transcript. Token counts are read from the transcript (not the payload directly), summing three buckets: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. The `Stop` hook fires when the session ends and generates the report from accumulated state.

---

## Project structure

```
devflow-monitor/
├── devflow/
│   ├── session.py       # per-session state (read/write JSON)
│   ├── signals.py       # extract signals from hook payloads
│   ├── scorer.py        # heuristic scoring engine
│   ├── output.py        # terminal output (writes to /dev/tty)
│   └── reporter.py      # Markdown report generator
├── hooks/
│   ├── post_tool_use.py # PostToolUse hook — runs after every tool call
│   └── stop.py          # Stop hook — generates the session report
├── sessions/            # runtime data (gitignored)
├── examples/
│   └── report_0.md      # real session report for reference
├── install.py           # registers hooks in Claude Code settings
└── tests/
    ├── test_scorer.py       # 54 boundary-case unit tests
    └── visualize_scorer.py  # visual scorer calibration tool
```
