# DevFlow Monitor

A passive session health advisor for Claude Code. It hooks into every tool call, scores five health signals in real time, and — when you're done — prints a digest in your terminal, compares the session with your previous one, and writes a full report. Nothing about how you work changes.

It is an advisor, not a linter: the goal is to teach you when to trust the AI's output and when to verify it.

---

## Quick start (new user)

Clone it anywhere on your machine. It is completely independent of the projects you work on.

```bash
git clone https://github.com/daniellek47/devflow-monitor.git ~/devflow-monitor
cd ~/devflow-monitor
python3 install.py --global
```

That's it. No dependencies. Python 3.8+ only.

`--global` registers the hooks in `~/.claude/settings.json` so every Claude Code session on your machine is monitored automatically, regardless of which project you open. It also installs the `/devflow-log` skill globally so you can open a live log window from any session.

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

When you end the session (`/exit` or Ctrl+C), a digest prints right in your terminal — no need to go looking for anything:

```
──────────────────────────────────────────────────────────
 DevFlow Monitor — Session Digest
 Health:    GOOD(80) final · 89 turns · 0 errors
 Context:   peaked 82% (164,173 tokens) · ended 17%
 Anomalies: 1 (repetition ×1) — first at turn 16
 Takeaway:  context was the limiting factor — next time /compact earlier
 Last time: peak context 62%→82% · tool error rate 0%→0% · anomalies 5→1
 Report:    ./show-report   (sessions/latest/report.md)
──────────────────────────────────────────────────────────
```

The `Last time` line compares this session with your previous one — the feedback loop that tells you whether you ran a better session than last time.

To read the full report:

```bash
~/devflow-monitor/show-report
```

The report includes a narrative overview with verdict and forward recommendation, a comparison table against your previous session, a transitions-only health timeline (steady turns are collapsed, so it reads as a story, not a log), full anomaly detail with the exact tool input and resolution status, and a "What We Can Learn" section. See [`examples/report_0.md`](examples/report_0.md) for a real session report.

---

## Watching health from a second terminal

Health lines also write to a plain-text log file (`health.log`) inside the session directory. The easiest way to open a live log window is the `/devflow-log` skill — type it in any Claude Code session:

```
/devflow-log
```

On Windows Terminal (WSL2) this opens a new tab. Inside a tmux session it opens a new window named `devflow`. Both follow the active session automatically.

The live view opens with an intro explaining what the monitor measures — the five signals, their weights and thresholds, and the available commands. You get the full menu on first run and a compact two-line header after that. The end-of-session digest appears here too.

You can also use the `tail-health` script directly from any terminal:

```bash
~/devflow-monitor/tail-health
```

`sessions/latest` is a symlink that always points to the most recently active session, so this script works from anywhere without knowing the session ID. It waits silently if no session has started yet.

To follow a specific session by ID:

```bash
tail -f ~/devflow-monitor/sessions/<session-id>/health.log
```

---

## What it monitors

| Signal | Weight | What triggers a warning |
|--------|--------|------------------------|
| Context pressure | 35% | Token usage above 50% of the 200k limit |
| Response length trend | 25% | Claude's responses shrinking more than 25% over the last 10 turns |
| Tool error rate | 20% | More than 10% of tool calls returning errors |
| Overconfidence | 10% | Certainty words dominating over hedging words in Claude's prose |
| Repetition | 10% | Same tool + input called 2+ times in a 6-call window |

**Overall health: GOOD ≥ 80 · WARN 55–79 · CRITICAL < 55**

The length trend only counts turns where Claude actually wrote text — silent tool calls (`mkdir`, `git add`, …) are excluded, so they can't fake a degradation signal.

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

The last 3 sessions are kept; older ones are deleted automatically when a session ends. The most recent previous session is what the digest and report compare against, so the feedback loop always has data after your first session.

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

The `PostToolUse` hook receives a JSON payload on stdin containing the tool name, input, response, and a path to the session transcript. Token counts are read from the transcript (not the payload directly), summing three buckets: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. The `Stop` hook fires when the session ends: it loads the previous session's state for comparison, generates the report, and prints the digest to the terminal.

---

## Project structure

```
devflow-monitor/
├── devflow/
│   ├── session.py       # per-session state; previous-session loader for comparison
│   ├── signals.py       # extract signals from hook payloads
│   ├── scorer.py        # heuristic scoring engine
│   ├── output.py        # terminal output (writes to /dev/tty)
│   └── reporter.py      # Markdown report, end-of-session digest, session comparison
├── hooks/
│   ├── post_tool_use.py # PostToolUse hook — runs after every tool call
│   └── stop.py          # Stop hook — prints the digest, generates the report
├── .claude/
│   └── skills/
│       └── devflow-log/ # /devflow-log skill (deployed globally by install.py --global)
│           └── SKILL.md
├── sessions/            # runtime data (gitignored); sessions/latest symlinks to active session
├── examples/
│   └── report_0.md      # real session report for reference
├── evals/
│   ├── synthetic_sessions/  # 5 designed test cases
│   ├── golden_outputs/      # analytically-derived expected results
│   └── eval_harness.py      # pipeline eval with regression detection
├── install.py           # registers hooks + deploys skill to ~/.claude/skills/
├── tail-health          # live health log + signals intro, from any directory
├── show-report          # opens the latest session report, from any directory
└── tests/
    ├── test_scorer.py       # 54 boundary-case unit tests
    └── visualize_scorer.py  # visual scorer calibration tool
```
