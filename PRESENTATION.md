# DevFlow Monitor
### AI Project Presentation — Claude Code

**Danielle Kreiner** · June 2026  
GitHub: [github.com/daniellek47/devflow-monitor](https://github.com/daniellek47/devflow-monitor)

---

## Executive Summary

### Problem Statement

Claude Code sessions degrade in ways that are easy to miss in the moment. The context window fills
up silently. Answers get shorter. The model starts repeating tool calls. A session that felt
productive can, in hindsight, have been producing low-quality output for the last twenty minutes.

There is no built-in signal for this. The developer only finds out after the fact — when they
re-read the output and notice it got thin, or when the next session has to undo what the last one
did. The question DevFlow Monitor tries to answer is: *can you know a session is degrading while it
is still happening, without changing anything about how you work?*

### Goals

1. Passively observe Claude Code sessions using the existing hook system — no workflow changes.
2. Collect measurable health signals on every tool call: context window pressure, response length
   trend, tool error rate, overconfident language, and stuck-loop repetition.
3. Surface those signals in real time as timestamped lines in the terminal.
4. Generate a structured session report at the end that supports honest retrospective review.

The project was intentionally scoped as a personal learning tool, not a production service. That
constraint drove several key choices: heuristics-only (no extra API calls), session-only state (no
database), and plain CLI output (no daemon, no web server).

### Architecture

DevFlow Monitor is a file-backed state machine that advances one step per tool call.

Claude Code's `PostToolUse` hook invokes a Python script after every tool use. The script reads a
JSON payload from stdin, extracts signals, loads a per-session state file, scores five health
dimensions, emits a status line to the terminal, and writes updated state back to disk. A second
hook fires on `Stop` and generates a Markdown report from the accumulated state.

There is no persistent background process. Each hook invocation is an isolated Python process that
lives for under a second. State persists between calls through a single JSON file at
`sessions/<session_id>/state.json`.

**Scoring** combines five weighted heuristics into a 0–100 health score:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Context pressure | 35% | Total tokens (including cache) as a fraction of the 200k limit |
| Response length trend | 25% | Whether output is getting shorter over the last 10 turns |
| Tool error rate | 20% | Fraction of tool calls that returned errors |
| Overconfidence | 10% | Ratio of certainty words to hedging words in Claude's prose |
| Repetition | 10% | Same tool + input appearing multiple times within a 6-call window |

A score ≥ 80 is **GOOD**, 55–79 is **WARN**, below 55 is **CRITICAL**.

### Outcome

The tool was built and tested in a single Claude Code session — monitored by itself.

The bootstrap session produced 39 tool calls over approximately one hour, reaching 100,565 tokens
(50% of the context limit) with zero tool errors. One anomaly was detected: a repeated Bash call at
turn 16. By the end, the health score had dropped to WARN(71) — driven by context pressure crossing
the 50% threshold and the response-length trend falling to CRITICAL(20) as the session shifted from
writing large files to small focused edits.

That final WARN rating is meaningful: it correctly identified that the session had entered a phase
where Claude's output was getting shorter, even though the work was still accurate. That is
precisely the kind of signal the tool was designed to surface.

---

## Prompts and Development Process

### Prompting Strategy

The project started with a broad, intent-driven description rather than a specification:

> *"I want to check basic things like token count context window usage and model limit, answers
> getting shorter, task completion, finish before time, error events, but also evaluate the answer
> for faults like over confidence."*

Giving the AI the *goal and signal types* rather than a file list or implementation plan forces it
to reason about architecture rather than just generate code. Before any code was written, four
clarifying questions were posed:

| Decision | Options | Choice made | Why it mattered |
|----------|---------|-------------|-----------------|
| Display format | TUI / web / plain CLI | Plain CLI | No daemon needed, composable |
| Evaluation approach | Heuristics / LLM-judge / both | Heuristics only | No API cost or latency per hook call |
| Scope | Personal / portfolio / open source | Personal / learning | Correctness over configurability |
| Persistence | Session-only / local history | Session-only | A JSON file per session; no database |

Each answer directly constrained an architectural decision. Getting these settled before writing a
line of code meant the implementation had a clear shape and no contradictions to resolve mid-build.

### Implementation — First Pass

With the design settled, the full implementation was written in one pass across ten files:
`session.py`, `signals.py`, `scorer.py`, `output.py`, `reporter.py`, two hooks, an installer, a
`.gitignore`, and 21 unit tests. All 21 tests passed.

This is the part of AI-assisted development that is easiest to get wrong. A clean green test run
does not mean the code is correct. It means the tests pass. In this case, the tests only covered
`scorer.py` — the pure scoring logic. The code that actually touched external systems was
completely untested.

The installer registered the hooks and the response was: *"try it out."*

That single prompt is the most important one in the session.

---

## Critical Reflection — Evaluating and Improving AI Output

### Bug 1 — Token counts were silently zero

After the hooks were live, inspecting `sessions/<id>/state.json` showed every `input_tokens` value
was 0. The monitor was running, counting tool calls, but scoring context pressure as 0%.

The initial implementation assumed the hook payload contained a `message.usage` field with token
counts — a reasonable assumption based on how the Claude API typically works. It does not. Token
data lives in a separate session transcript file at a path provided under `transcript_path`. The
transcript is a JSONL file where `assistant`-type entries contain `message.usage`, split across
three buckets that must be summed: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.

**Prompt that triggered discovery:** *"try it out"*

Running the tool on a real session and inspecting the state file was the test. No unit test would
have caught it — `signals.py` was untested, and the bug was in the wrong assumption about external
data structure, not in the logic.

**Fix:** `signals.py` rewritten to read the transcript file, find the matching `tool_use_id`, and
sum all three token buckets.

---

### Bug 2 — Health output was swallowed by the TUI

After fixing token counts, the health lines never appeared in the terminal.

**Prompts that triggered discovery:**
> *"where the health line should appear? i am having a session with claude code in the powershell..."*  
> *"the entries are there. but i dont see the tool using line"*

The events log confirmed the hook was running. The output was being generated and discarded. Claude
Code's TUI rerenders the terminal after every tool call and discards the stderr of hook
subprocesses.

**Fix:** `output.py` rewritten to open `/dev/tty` directly — this bypasses the TUI entirely and
appears in the terminal regardless of stdout/stderr redirection.

```python
def _print(text: str) -> None:
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text + "\n")
    except Exception:
        print(text, file=sys.stderr, flush=True)
```

---

### Bug 3 — Report narrative had hardcoded values

After the report was working end-to-end:

> *"The narrative paragraph — is it templated or does it actually use session data? The 'What We Can Learn' section — are the arithmetic examples in the report computed from actual session values or hardcoded?"*

Three literal values from the demo session were hardcoded in the explanatory prose:
- `"as happened here at 16:57:32"` — a literal timestamp from the demo session
- `"health stayed GOOD(80)"` — a literal score, wrong for any other session
- `"The repetition anomaly (turn 16)"` — a literal turn number, wrong for any other session

The narrative *appeared* data-driven because other values used `{peak_pct:.0%}` — so the
hardcoding was not immediately visible from reading the code. The bug only surfaced because the user
questioned directly whether the output was computed or templated.

**This is a class of bug that automated tests cannot catch.** The reporter was untested and the
hardcoded values are valid Python f-string literals. A human reading the output with skepticism
found what the test suite missed.

---

### Evaluation Finding — Silent tool calls cause false CRITICAL (accepted, not fixed)

Running the monitor on a real 89-turn session revealed that the length trend scorer fired CRITICAL
repeatedly during healthy work. Investigation against raw `events.jsonl` identified the cause:

Silent bash commands — `mkdir`, `git add`, file writes with no output — produce near-zero response
text. These collapse the late-window average:

```python
burst_short = [700, 720, 680, 710, 700, 50, 60, 45, 55, 50]
score_response_length_trend(burst_short)
# → {'score': 20, 'level': 'CRITICAL', 'change_pct': -92.6}
```

The scorer logic is correct. The design assumption is wrong: it assumed all response text reflects
reasoning quality. A `mkdir` that succeeds silently is not evidence of degradation.

**Why this wasn't fixed:** An evaluation that catches nothing teaches nothing. This is the most
instructive finding in the project. The correct next version filters the length trend to assistant
text turns only. The architectural change required was considered out of scope for this prototype.

*(Note: this limitation was subsequently fixed — `post_tool_use.py` now tracks only turns where
Claude actually wrote text, filtering out silent tool calls.)*

---

### Evaluation Finding — Overconfidence scorer inactive in this domain (accepted)

The overconfidence scorer returned GOOD(100) on every turn of a real 89-turn session. Claude Code's
language is assertive by nature — it writes code and explains decisions without hedging. The
certainty word list was calibrated for conversational text, not code-writing.

**Design response:** Weight kept at 10% intentionally. Low enough that miscalibration doesn't
distort the overall score. The correct fix is a domain-specific word list calibrated on real Claude
Code transcripts.

---

### Evaluation Finding — A predicted failure mode didn't materialize

A hypothesis: alternating long/short responses (code writing then confirmations) would cause false
positives. Testing disproved it:

```python
alternating = [800, 100, 800, 100, 800, 100, 800, 100]
score_response_length_trend(alternating)
# → {'score': 100, 'level': 'GOOD', 'change_pct': 0.0}
```

The early/late window averaging cancels out alternating patterns. The oscillation observed in the
live session report was caused by silent tool calls (Finding 1), not response rhythm.

**A correct evaluation tests hypotheses, not just code.** Finding that a predicted failure mode
doesn't exist is as useful as finding one that does.

---

## Testing Approach

### What is tested and why

**`scorer.py` — 54 unit tests** (`tests/test_scorer.py`)

The scorer is pure Python with no external dependencies. Every threshold boundary is tested
explicitly — not just "low value → GOOD, high value → CRITICAL" but the exact value at the boundary
and one unit above and below. Off-by-one errors at threshold boundaries cause quiet scoring
discontinuities.

Selected boundary tests:
- Context over 100% (ratio > 1.0) — should not crash, should stay CRITICAL
- Response trend with exactly 3 items vs. 4 (minimum for analysis)
- Window: 15-item history where the first 5 are catastrophic but the last 10 are stable
- Zero early average in trend (division-by-zero guard)
- Overconfidence on texts shorter than 60 chars (length guard)
- Repetition matching using truncated 120-char input fingerprint

**`tests/visualize_scorer.py` — visual verification**

Not a pytest test, but a diagnostic that renders the full scoring curve for each dimension. Useful
for reviewing calibration. The visualization itself caught a bug: every sample showed GOOD(100) for
overconfidence because the sample labels ("max certainty") were all under 60 characters — too short
to score. The fix was to use realistic-length sample texts.

### What is not tested and why

**`signals.py`** — untested. This is where the only production bug occurred (zero token counts).
Testing it requires either a mock transcript file (brittle — tied to Claude Code's internal JSONL
format) or a live hook invocation (an integration test depending on Claude Code being running).
**Risk accepted:** if Claude Code changes the transcript format, tokens will silently return zero.
The events log makes this detectable, but there is no automated check.

**`hooks/post_tool_use.py`** — untested. A bug here would cause the hook to crash silently — Claude
Code would continue working, but monitoring would stop.

**`reporter.py`** — untested. Correctness is easy to verify by eye, but there are no automated
assertions on the report's content or structure. This is where Bug 3 (hardcoded values) lived.

### Bugs caught by tests

| How found | Bug |
|-----------|-----|
| Live session + state inspection | Token counts silently zero — wrong assumption about payload structure |
| Visual scoring output | Overconfidence scorer inactive on all samples due to 60-char minimum |
| User questioning AI output | Three hardcoded values in report narrative, passed off as data-driven |
| Live session + events.jsonl analysis | Silent tool calls triggering false CRITICAL on length trend |

The pattern: the unit tests caught nothing. Every significant bug was found by running the tool on
real output and inspecting what came back. The test suite validates the scorer's math; it cannot
validate the system's assumptions about external data.

---

## Demo

The repository includes a `tail-health` script and a `/devflow-log` Claude Code skill.

- **Live log:** running `./tail-health` (or `/devflow-log` from any Claude Code session) opens a
  real-time view of the health log for the current session.
- **Session report:** generated automatically at session end at `sessions/<id>/report.md`.

**GitHub:** [github.com/daniellek47/devflow-monitor](https://github.com/daniellek47/devflow-monitor)
