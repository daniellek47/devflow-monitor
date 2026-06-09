# Development Process & Testing Approach — DevFlow Monitor

## Prompting Strategy

The project started with a broad, intent-driven description rather than a specification:

> *"I want to check basic things like token count context window usage and model limit, answers
> getting shorter, task completion, finish before time, error events, but also evaluate the answer
> for faults like over confidence."*

This is a good way to start an AI-assisted project. Giving the AI the *goal and signal types* rather
than a file list or implementation plan forces it to reason about architecture rather than just
generate code. The prompt described what the tool should observe and why, not how to build it.

Before any code was written, four clarifying questions were posed:

| Decision | Options | Choice made | Why it mattered |
|----------|---------|-------------|-----------------|
| Display format | TUI / web / plain CLI | Plain CLI (stderr) | No daemon needed, no dependencies, composable |
| Evaluation approach | Heuristics / LLM-judge / both | Heuristics only | No extra API cost or latency per tool call |
| Scope | Personal / portfolio / open source | Personal / learning | No polish overhead; correctness over configurability |
| Persistence | Session-only / local history | Session-only | A JSON file per session; no database |

Each answer directly constrained an architectural decision. The display choice ruled out a
background process. The heuristics choice ruled out calling the Claude API from within a hook.
The session-only choice determined the state model. Getting these settled before writing a line of
code meant the implementation had a clear shape and no contradictions to resolve mid-build.

---

## Implementation — First Pass

With the design settled, the full implementation was written in one pass across ten files:
`session.py`, `signals.py`, `scorer.py`, `output.py`, `reporter.py`, two hooks, an installer, a
`.gitignore`, and 21 unit tests. The AI proposed the structure, wrote all the code, and ran the
tests — all 21 passed.

This is the part of AI-assisted development that is easiest to get wrong. A clean green test run
does not mean the code is correct. It means the tests pass. In this case, the tests only covered
`scorer.py` — the pure scoring logic. The code that actually touched external systems (the hook
payload, the Claude session transcript) was completely untested.

The installer registered the hooks and the response was: *"try it out."*

That single prompt is the most important one in the session.

---

## The Bug — What "Try It Out" Found

After the hooks were live, inspecting `sessions/<id>/state.json` showed every `input_tokens` value
was 0. The monitor was running, counting tool calls, but scoring context pressure as 0% because it
had no token data.

The initial implementation in `signals.py` assumed the hook payload contained a `message.usage`
field with token counts — a reasonable assumption based on how Claude's API typically works. It
does not. The hook payload contains no token data at all.

To find the real structure, a one-time debug dump was added to the hook to write the raw payload
to disk. The actual payload revealed two things:

1. Token data lives in a separate session transcript file at a path provided under `transcript_path`
2. The transcript is a JSONL file where `assistant`-type entries contain `message.usage`
3. Token counts come in three buckets that must be summed: `input_tokens` (often just 1 when
   caching is active) + `cache_read_input_tokens` + `cache_creation_input_tokens`

The fix required understanding Claude Code's actual data model — something the original
implementation had gotten wrong by analogy with the API. The corrected `signals.py` reads the
transcript file on every hook call, finds the `assistant` entry whose content contains the matching
`tool_use_id`, and sums all three token buckets to get true context window usage.

**Prompt that triggered the discovery:**

> *"try it out"*

That single prompt — after the installer registered the hooks — is what revealed the bug. Without
running a live session and inspecting the output, the silently-zero token counts would have been
invisible indefinitely.

**This is the pattern the requirements are asking about.** The AI wrote plausible code, the code
ran without errors, and it produced wrong values silently. The bug was only found by running the
tool against real output and inspecting the data. No amount of unit testing would have caught it
because no unit test covered `signals.py` or the transcript parsing.

---

## Iteration — Token Fix + Duration Signal

With the real payload structure understood, two changes were made:

- `signals.py` rewritten to read from `transcript_path` and sum all three token buckets
- `duration_ms` (tool execution time, present in the payload) added as a visible field in the
  status line — a small improvement noticed while reading the real payload structure

After the fix, token counts appeared correctly. The final session shows context growing from ~36k
tokens at turn 1 to ~100k at the end, crossing the 50% threshold and contributing to a WARN(71)
health score in the last turn.

---

## Iteration — Test Expansion and Visualization

The initial 21 tests were functional but shallow. The next iteration expanded them to 54 boundary
cases organized by scorer, structured as test classes. Each scorer now has tests at every threshold
boundary (e.g., exactly 50%, 75%, 90% for context pressure), at the minimum-data boundary (e.g.,
3 items vs. 4 items for trend), and for edge cases like zero inputs and over-limit values.

A separate visualization script (`tests/visualize_scorer.py`) was written to render each scorer's
full response curve in the terminal. The visualization itself caught a second bug:

**Section 4 (Overconfidence) showed GOOD(100) for every row, including "max certainty" cases.**

**Prompt that triggered the discovery:**

> *"python3 tests/visualize_scorer.py"*

Running the visualization was the test. The output showed a flat GOOD(100) column for every
overconfidence row — which looked wrong on inspection.

The cause: every sample text in the visualization was under 60 characters — the minimum length
below which the scorer skips analysis to avoid false positives on short acknowledgments. The sample
texts were all labels like *"max certainty"* rather than actual prose. The visualization was fixed
to use realistic-length texts and to annotate below-minimum rows explicitly.

This is a different kind of bug from the token issue — not a wrong assumption about external data,
but a test that tested the wrong thing. The certainty-scoring logic was correct; the test inputs
were not representative.

---

## Testing Approach

### What is tested and why

**`scorer.py` — 54 unit tests** (`tests/test_scorer.py`)

The scorer is pure Python with no external dependencies — a function that takes numbers and returns
numbers. This is the right layer for unit testing. Every threshold boundary is tested explicitly:
the test does not just check that a low value returns GOOD and a high value returns CRITICAL; it
checks the exact value at the boundary and one unit above and below it. This matters because
off-by-one errors at threshold boundaries cause quiet scoring discontinuities.

Specific boundary tests added:
- Context over 100% (ratio > 1.0) — should not crash, should stay CRITICAL
- Response trend with exactly 3 items vs. 4 (minimum for analysis)
- Window behavior: 15-item history where the first 5 are catastrophic but the last 10 are stable
- Zero early average in trend (division-by-zero guard)
- Overconfidence on texts shorter than 60 chars (length guard)
- Repetition matching using truncated 120-char input fingerprint
- Overall health with a missing key in the scores dict (partial input robustness)

**`tests/visualize_scorer.py` — visual verification**

Not a test in the pytest sense, but a diagnostic that renders the full scoring curve for each
dimension. Useful for reviewing calibration — e.g., confirming that the overconfidence threshold
actually requires both certainty words AND enough text length to be meaningful, not just any mention
of "definitely."

### What is not tested and why

**`signals.py` — transcript parsing and signal extraction**

This module is untested. It is also where the only real production bug occurred. Testing it
requires either a mock transcript file (brittle — tied to Claude Code's internal JSONL format,
which could change) or a live hook invocation (an integration test that depends on Claude Code
being running). Neither was implemented in this phase.

The risk accepted: if Claude Code changes the structure of `assistant` entries in the transcript
JSONL, or if token buckets are renamed, `signals.py` will silently return zeros again. The events
log (`events.jsonl`) would make this detectable — token counts dropping to 0 mid-session is
observable — but there is no automated check.

**`hooks/post_tool_use.py` — end-to-end orchestration**

The hook itself is untested. It is the main integration point: it calls signals, session, scorer,
and output in sequence and handles anomaly recording. A bug here (e.g., a key error in the state
dict) would cause the hook to crash silently — Claude Code would continue working, but monitoring
would stop. No test currently covers this path.

**`reporter.py` — report generation**

The Markdown report is untested. The output is human-readable, so correctness is easy to check by
eye, but there is no automated assertion on the report's content or structure.

**The overconfidence signal at runtime**

In practice, Claude Code's `PostToolUse` hook fires *after* a tool call. The text content in the
message is whatever Claude wrote as prose *before* calling the tool. In many turns — especially
when Claude makes a tool call without preamble — this text is empty or very short. The overconfidence
signal runs, finds text below 60 chars, and returns GOOD(100) by default. The signal is currently
more useful as a flag for verbose turns than as a session-wide health indicator. This is a known
limitation, not a bug.

---

## Iteration — Health Lines Not Visible in Claude Code Terminal

After installing the hooks and running a real session, the health output was confirmed to be
reaching `events.jsonl` (the hook was running), but nothing appeared in the Claude Code terminal
where it was expected.

**The bug:** The hooks wrote to `sys.stderr`. Claude Code's TUI rerenders the terminal after every
tool call and discards the stderr of hook subprocesses in the process. The hook output was
generated and lost before any human could read it.

**Prompts that triggered the discovery:**

> *"where the health line should appear? i am having a session with claude code in the powershell..."*

> *"the entries are there. but i dont see the tool using line"*

The first prompt named the symptom — output was expected but missing. The second confirmed the
hook was actually running (entries in the log), which narrowed the problem to the output path
rather than the hook registration or execution.

**How it was found:** The user noticed that events were accumulating in `events.jsonl` — meaning
the hook ran successfully — but the expected health line (`[HH:MM:SS] turn=...`) never appeared
in the terminal. The events log proved the hook was not crashing; the output was being swallowed.

**The fix:** `output.py` was rewritten to open `/dev/tty` directly and write there instead of
stderr. `/dev/tty` is the terminal device for the current process — writing to it bypasses the TUI
layer entirely and appears immediately in the terminal regardless of stdout/stderr redirection. A
fallback to stderr was kept for environments where `/dev/tty` is unavailable (e.g., CI).

```python
def _print(text: str) -> None:
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text + "\n")
            tty.flush()
    except Exception:
        print(text, file=sys.stderr, flush=True)
```

After the fix, health lines appeared live in the terminal on every tool call.

---

## Iteration — health.log Not Created

After adding the per-session `health.log` file (plain-text ANSI-stripped copy of health output,
for monitoring from a second terminal), the log file did not appear in the session directory after
running a session.

**The bug:** The `post_tool_use.py` hook called `output.set_log_file(session_path / "health.log")`
before the session directory existed. The write silently failed with a `FileNotFoundError` caught
inside the `_print` exception handler, so no log was written.

**Prompt that triggered the discovery:**

> *"ok now we have a health log. how can i see it in real time in my other terminal?"*

Followed by the user running the suggested command and reporting:

```
$ tail -f ~/devflow-monitor/sessions/.../health.log
ls: cannot access '/home/danielle/devflow-monitor/sessions/': No such file or directory
```

The file simply did not exist. The prompt prompted investigation into why the log was never written.

**How it was found:** The user tried `tail -f sessions/<id>/health.log` and got "No such file or
directory" even after a session had run. Adding a `print` inside the exception handler in `_print`
confirmed the directory was missing when the first write attempted.

**The fix:** Added `session_path.mkdir(parents=True, exist_ok=True)` immediately before the
`set_log_file` call in `post_tool_use.py`:

```python
session_path = session.get_session_path(sid)
session_path.mkdir(parents=True, exist_ok=True)   # ← added
output.set_log_file(session_path / "health.log")
```

The directory was being created later (in `session.save_state`), but `set_log_file` was called
before any state was saved. The fix moved directory creation to the earliest point it was needed.

---

## Iteration — Hardcoded Values in Report "What We Can Learn" Section

After the report was working end-to-end, the user asked:

> *"The narrative paragraph — is it templated or does it actually use session data? The 'What We Can Learn' section — are the arithmetic examples in the report computed from actual session values or hardcoded?"*

**The bug:** Code review revealed that three specific values in `_section_learnings` were
hardcoded to the session used while writing the reporter:

- `"as happened here at 16:57:32"` — a literal timestamp from the demo session, wrong for any
  other session
- `"health stayed GOOD(80)"` — a literal health score from when the demo session's length trend
  went CRITICAL, wrong if a different session had a different score at that moment
- `"The repetition anomaly (turn 16)"` — a literal turn number from the demo session's first
  anomaly, wrong for any other session

The narrative *appeared* data-driven — it used `{peak_pct:.0%}` and `{ts}` for some values —
so the hardcoding was not immediately obvious from reading the code. The bug only surfaced because
the user explicitly questioned whether the output was computed or templated.

**How it was found:** Code review of `reporter.py`, prompted by the user's direct question.
No test existed that would have caught it — the reporter has no automated tests, and the hardcoded
values happen to be valid Python f-string literals rather than obvious string constants.

**The fix:** Each hardcoded value was replaced with a computation from the actual session data:

- Timestamp: `signal_history[facts["first_warn_idx"]].get("ts", "")` — the actual timestamp of
  the first WARN transition; omitted entirely if no WARN occurred
- Health score at CRITICAL: `signal_history[first_critical_idx]["health"]["score"]` and
  `["level"]` — the actual score and level at the moment the length signal went CRITICAL
- Turn number: `anomalies[0].get("turn")` for dict-format anomalies, regex extraction of
  `"turn N"` for legacy string anomalies
- Health drop: `signal_history[turn_num - 2]["health"]["score"]` and
  `signal_history[turn_num - 1]["health"]["score"]` — actual before/after health at the anomaly
  turn, with a "Health dipped slightly" fallback when the turn index cannot be resolved

This is a class of bug that is easy to introduce when building a report generator against a single
representative session: values that happen to be data-derived in the obvious places but are
accidentally hardcoded in the explanatory prose. The fix is systematic: every number that appears
in the output should trace to a variable, not a literal.

### Bugs caught by tests

**Caught by visualization:** The short-text guard in `score_overconfidence` silently neutralized
every sample in the original visualization because the sample labels ("max certainty", "hedging")
were all under 60 characters. The visualization showed GOOD(100) across the board. Without the
visual output, this would have looked correct.

**Caught by live test (not by unit tests):** The token extraction bug described above. The unit
tests for `scorer.py` all passed. The end-to-end behavior was wrong. Only running the tool on a
real session revealed the issue.

**Caught by code review (user question):** The hardcoded values in `_section_learnings`. No test
would have caught this — the reporter is untested. The bug surfaced because the user asked a direct
question about whether the output was computed from data. The lesson: a human reading the output
with skepticism found what automated tests missed.

---

## Evaluation Findings — Live Session Analysis

After running the monitor on a real 89-turn session, analysis of `events.jsonl` and `health.log`
produced three findings. These are not bugs in the code — the code does what it was designed to do.
They are findings about where the design assumptions break down against real-world data.

---

### Finding 1 — Silent tool calls cause false CRITICAL readings (not fixed)

The length trend scorer fired CRITICAL repeatedly during a healthy 89-turn session. Investigation
against raw `events.jsonl` revealed the cause:

Silent bash commands — `mkdir`, `git add`, file writes with no output — produce 94-character empty
JSON wrappers. These collapse the late-window average dramatically:

```python
burst_short = [700, 720, 680, 710, 700, 50, 60, 45, 55, 50]
score_response_length_trend(burst_short)
# → {'score': 20, 'level': 'CRITICAL', 'change_pct': -92.6}
```

The scorer logic is correct. The design assumption is wrong: it assumes all output tokens reflect
reasoning quality. They don't. A `mkdir` that succeeds silently is not evidence of degradation.

**Accepted risk:** Fixing this requires separating tool response tokens from assistant text tokens
— a meaningful architectural change. For this prototype, the limitation is documented. The correct
next version filters the length trend to assistant text turns only.

**Why this wasn't fixed:** Fixing it would have removed the most instructive finding in the project.
An evaluation that catches nothing teaches nothing.

---

### Finding 2 — Overconfidence scorer is inactive in this domain (accepted)

The overconfidence scorer returned GOOD(100) on every turn of a real 89-turn session. Testing on
actual Claude Code response text confirmed why:

```python
samples = [
    "I'll create the file at the specified path with the correct structure.",
    "The function correctly handles the edge case you described.",
    "This implementation follows the pattern we established earlier.",
    "I've updated the scorer to fix the threshold boundary issue.",
]
# All four → certainty_ratio: 0.0
```

Claude Code's language is assertive by nature — it's writing code and explaining decisions, not
hedging. Words like "definitely" and "obviously" are rare in engineering output. The certainty
word list was calibrated for conversational text, not code-writing context.

**Design response:** Weight kept at 10% intentionally — low enough that a miscalibration doesn't
distort the overall score. The signal is documented as a known limitation. A domain-specific word
list calibrated on Claude Code transcripts would be the correct fix.

---

### Finding 3 — A predicted failure mode didn't materialize (hypothesis rejected)

The oscillating length trend in the session report led to a hypothesis: alternating long/short
responses (code writing followed by confirmations) would cause false positives.

```python
alternating = [800, 100, 800, 100, 800, 100, 800, 100]
score_response_length_trend(alternating)
# → {'score': 100, 'level': 'GOOD', 'trend': 'stable', 'change_pct': 0.0}
```

The hypothesis was wrong. The early/late window averaging smooths out alternating patterns because
the averages cancel. The oscillation in the live report was caused by Finding 1 — silent tool calls
— not by alternating response rhythm.

**Why this belongs in the evaluation:** A correct evaluation tests hypotheses, not just code.
Finding that a predicted failure mode doesn't exist is as useful as finding one that does. It
updates the model of the system.

---

## What remains unverified

- The tool's behavior when Claude Code restarts mid-session with the same `session_id`
- Whether `duration_ms` accurately reflects slow vs. fast tool calls across tool types
- Whether the 60-character minimum for overconfidence is well-calibrated for real sessions
- Whether the 10-turn window for response length trend is the right length — shorter sessions
  will hit the 4-turn minimum and never generate a meaningful trend signal
