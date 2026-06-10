# DevFlow Monitor — AI Session Health Monitor

**Danielle Kreiner** · June 2026
**GitHub:** [github.com/daniellek47/devflow-monitor](https://github.com/daniellek47/devflow-monitor)
**Demo:** [https://www.loom.com/share/b6ced8ce8a084edd9540415527feceef](https://www.loom.com/share/b6ced8ce8a084edd9540415527feceef)

---
# The document's purpose is to document the project, development, testing, and evaluation, and engineering decisions.
# It extends the PDF report submitted by email.

# 1. Executive Summary

## 1.1 Problem Statement

Claude Code sessions degrade in ways that are easy to miss in the moment. The context window fills
up silently. Answers get shorter. The model starts repeating tool calls. A session that felt
productive can, in hindsight, have been producing low-quality output for the last twenty minutes.

There is no built-in signal for this. The developer only finds out after the fact — when they
re-read the output and notice it got thin, or when the next session has to undo what the last one
did. The question DevFlow Monitor tries to answer is: *can you know a session is degrading while it
is still happening, without changing anything about how you work?*

## 1.2 Goals and Scope Constraints

1. Passively observe Claude Code sessions using the existing hook system — no workflow changes.
2. Collect measurable health signals on every tool call: context window pressure, response length
   trend, tool error rate, overconfident language, and stuck-loop repetition.
3. Surface those signals in real time as timestamped lines in the terminal.
4. Generate a structured session report at the end that supports honest retrospective review.

The project was intentionally scoped as a personal learning tool, not a production service. That
constraint drove several key choices: heuristics-only (no extra API calls from hooks), session-only
state (no database), and plain CLI output (no daemon, no web server).

## 1.3 Architecture

DevFlow Monitor is a file-backed state machine that advances one step per tool call.

Claude Code's `PostToolUse` hook invokes a Python script after every tool use. The script reads a
JSON payload from stdin, extracts signals, loads a per-session state file, scores five health
dimensions, emits a status line to the terminal via `/dev/tty`, and writes updated state back to
disk. A second hook fires on `Stop` and generates a Markdown report from the accumulated state.

There is no persistent background process. Each hook invocation is an isolated Python process that
lives for under a second. State persists between calls through a single JSON file at
`sessions/<session_id>/state.json`.

```
        Claude Code session
                │
   ┌────────────┴──────────────────┐
   │ PostToolUse                   │ Stop
   │ (JSON payload on stdin)       │
   ▼                               ▼
hooks/post_tool_use.py        hooks/stop.py
   │                               │
   ├─► devflow/signals.py          ├─► devflow/reporter.py
   │     parses payload; reads     │     renders Markdown report
   │     token counts from the     │     from accumulated state
   │     session transcript JSONL  │
   ├─► devflow/scorer.py           │
   │     five weighted heuristics  │
   │     (pure functions, no I/O)  │
   ├─► devflow/output.py           │
   │     health line → /dev/tty    │
   │     + sessions/<id>/health.log│
   ▼                               ▼
sessions/<id>/                 sessions/<id>/report.md
   state.json   (live state)
   events.jsonl (raw event log)
   health.log   (plain-text health lines)
```

Key architectural decisions:

- **Hooks, not a daemon** — the monitor fires on Claude Code's schedule and exits cleanly; there
  is nothing to start, stop, or crash.
- **`/dev/tty`, not stderr** — Claude Code's TUI redraws after each tool call and swallows stderr
  from hook subprocesses. Writing to `/dev/tty` bypasses the TUI layer (found the hard way; §2.4).
- **File-backed state machine** — each hook invocation is an isolated process; all shared state
  lives in JSON files.
- **No LLM calls in hooks** — heuristics only; no latency or cost added to any tool call.

## 1.4 Signals and Scoring

Scoring combines five weighted heuristics into a 0–100 health score:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Context pressure | 35% | Total tokens (including cache) as a fraction of the 200k limit |
| Response length trend | 25% | Whether Claude's responses are getting shorter over the last 10 turns |
| Tool error rate | 20% | Fraction of tool calls that returned errors |
| Overconfidence | 10% | Ratio of certainty words to hedging words in Claude's prose |
| Repetition | 10% | Same tool + input appearing multiple times within a 6-call window |

A score ≥ 80 is **GOOD**, 55–79 is **WARN**, below 55 is **CRITICAL**.

## 1.5 Outcome

The tool was built and tested in a single Claude Code session — monitored by itself.

The bootstrap session produced 39 tool calls over approximately one hour, reaching 100,565 tokens
(50% of the context limit) with zero tool errors. One anomaly was detected: a repeated Bash call at
turn 16. By the end, the health score had dropped to WARN(71) — driven by context pressure crossing
the 50% threshold and the response-length trend falling to CRITICAL(20) as the session shifted from
writing large files to small focused edits.

That final WARN rating is meaningful: it correctly identified that the session had entered a phase
where Claude's output was getting shorter, even though the work was still accurate. That is
precisely the kind of signal the tool was designed to surface.

A later 89-turn monitored session became the project's main evaluation dataset — it exposed a
false-positive failure mode, confirmed a dead signal, and disproved a predicted one (§3). The full
report from that session is excerpted in Appendix B.

---

# 2. Prompts and Development Process

## 2.1 Prompting Strategy

The project started with a broad, intent-driven description rather than a specification:

> *"I want to check basic things like token count context window usage and model limit, answers
> getting shorter, task completion, finish before time, error events, but also evaluate the answer
> for faults like over confidence."*

Giving the AI the *goal and signal types* rather than a file list or implementation plan forces it
to reason about architecture rather than just generate code. The prompt described what the tool
should observe and why, not how to build it.

## 2.2 Four Design Decisions Before Any Code

Before any code was written, four clarifying questions were posed:

| Decision | Options | Choice made | Why it mattered |
|----------|---------|-------------|-----------------|
| Display format | TUI / web / plain CLI | Plain CLI | No daemon needed, no dependencies, composable |
| Evaluation approach | Heuristics / LLM-judge / both | Heuristics only | No extra API cost or latency per tool call |
| Scope | Personal / portfolio / open source | Personal / learning | No polish overhead; correctness over configurability |
| Persistence | Session-only / local history | Session-only | A JSON file per session; no database |

Each answer directly constrained an architectural decision. The display choice ruled out a
background process. The heuristics choice ruled out calling the Claude API from within a hook.
The session-only choice determined the state model. Getting these settled before writing a line of
code meant the implementation had a clear shape and no contradictions to resolve mid-build.

## 2.3 First Pass: Ten Files, Green Tests — and Why That Meant Little

With the design settled, the full implementation was written in one pass across ten files:
`session.py`, `signals.py`, `scorer.py`, `output.py`, `reporter.py`, two hooks, an installer, a
`.gitignore`, and 21 unit tests. All 21 tests passed.

This is the part of AI-assisted development that is easiest to get wrong. A clean green test run
does not mean the code is correct. It means the tests pass. In this case, the tests only covered
`scorer.py` — the pure scoring logic. The code that actually touched external systems (the hook
payload, the Claude session transcript) was completely untested.

The installer registered the hooks and the response was: *"try it out."*

That single prompt is the most important one in the session.

## 2.4 Iteration Log

Each iteration below is summarized as symptom → triggering prompt → fix. The analysis of what
these bugs reveal about evaluating AI output is in §3.

### Iteration 1 — Token counts were silently zero

**Symptom:** After the hooks went live, every `input_tokens` value in `state.json` was 0. The
monitor was running and counting tool calls, but scoring context pressure as 0%.

**Prompt that triggered discovery:** *"try it out"*

**Root cause:** The generated `signals.py` assumed the hook payload contained a `message.usage`
field with token counts — a reasonable assumption by analogy with the Claude API. It does not.
A one-time debug dump of the raw payload revealed the actual data model: token data lives in a
separate session transcript JSONL at a path provided under `transcript_path`, inside
`assistant`-type entries, split across three buckets that must be summed:
`input_tokens` (often just 1 when caching is active) + `cache_read_input_tokens` +
`cache_creation_input_tokens`.

**Fix:** `signals.py` rewritten to read the transcript file, find the `assistant` entry containing
the matching `tool_use_id`, and sum all three buckets. While reading the real payload, `duration_ms`
(tool execution time) was discovered and added to the status line. After the fix, context tracking
worked: the session showed growth from ~36k tokens at turn 1 to ~100k at the end.

### Iteration 2 — Health lines invisible in the Claude Code terminal

**Symptom:** The hook was demonstrably running (entries accumulating in `events.jsonl`), but the
expected health line never appeared in the terminal.

**Prompts that triggered discovery:**
> *"where the health line should appear? i am having a session with claude code in the powershell..."*
> *"the entries are there. but i dont see the tool using line"*

The second prompt narrowed the problem decisively: the events log proved the hook was not crashing,
so the output path itself had to be the problem.

**Root cause:** The hooks wrote to `sys.stderr`. Claude Code's TUI rerenders the terminal after
every tool call and discards the stderr of hook subprocesses. The output was generated and lost
before any human could read it.

**Fix:** `output.py` rewritten to open `/dev/tty` directly — the terminal device for the current
process — bypassing the TUI layer entirely, with a stderr fallback for environments without a tty:

```python
def _print(text: str) -> None:
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text + "\n")
            tty.flush()
    except Exception:
        print(text, file=sys.stderr, flush=True)
```

### Iteration 3 — health.log never created

**Symptom:** After adding a per-session `health.log` (plain-text copy of health output for
monitoring from a second terminal), the file did not exist after running a session:

```
$ tail -f ~/devflow-monitor/sessions/.../health.log
ls: cannot access '...': No such file or directory
```

**Prompt that triggered discovery:** *"ok now we have a health log. how can i see it in real time
in my other terminal?"* — followed by running the suggested `tail` command and hitting the error.

**Root cause:** The hook called `output.set_log_file(...)` before the session directory existed.
The write failed with `FileNotFoundError`, silently caught by the `_print` exception handler. The
directory was created later (in `session.save_state`) — too late for the first log write.

**Fix:** `session_path.mkdir(parents=True, exist_ok=True)` moved to the earliest point of need,
immediately before `set_log_file` in `post_tool_use.py`.

### Iteration 4 — Hardcoded values in the report narrative

**Symptom:** None visible. The report's "What We Can Learn" section read as data-driven.

**Prompt that triggered discovery:**
> *"The narrative paragraph — is it templated or does it actually use session data? The 'What We
> Can Learn' section — are the arithmetic examples in the report computed from actual session
> values or hardcoded?"*

**Root cause:** Code review revealed three literal values from the development session hardcoded
into the narrative: a timestamp (`"as happened here at 16:57:32"`), a health score (`"health
stayed GOOD(80)"`), and a turn number (`"The repetition anomaly (turn 16)"`). The surrounding
prose used real computed values like `{peak_pct:.0%}`, so the hardcoding was invisible from a
casual read of either the code or the output.

**Fix:** Every literal replaced with a computation from session state — the actual first-WARN
timestamp from `signal_history`, the actual health score at the CRITICAL transition, the actual
turn number from the anomalies list — each with a fallback when the data is absent. The rule
adopted: every number that appears in generated output must trace to a variable, not a literal.

### Iteration 5 — Test expansion and visual calibration

The initial 21 tests were functional but shallow. They were expanded to 54 boundary cases
organized by scorer: every threshold boundary tested at the exact value and one unit above and
below, minimum-data boundaries, zero inputs, over-limit values.

A separate visualization script (`tests/visualize_scorer.py`) renders each scorer's full response
curve in the terminal. Running it caught a bug in the tests themselves: the overconfidence section
showed GOOD(100) for every row, including "max certainty" cases — because every sample text was
under 60 characters, the scorer's minimum length below which it skips analysis. The sample texts
were labels, not prose. The visualization was fixed to use realistic-length texts and to annotate
below-minimum rows explicitly. The scoring logic was correct; the test inputs were unrepresentative.

### Iteration 6 — Eval harness

After the tool stabilized, a gap remained: the 54 unit tests covered individual scorer functions
at threshold boundaries, but nothing verified that correct individual scores combine into the
correct *overall* outcome — or that a future weight change wouldn't silently shift a session that
should be WARN into GOOD. The eval harness (`evals/eval_harness.py`) was added to close this gap.
It is described in full in §4.3.

### Iteration 7 — From monitor to advisor: digest, comparison, and a shorter report

The last iteration was driven by the product vision rather than a bug: DevFlow Monitor is meant to
*teach* engineers when to trust an AI session — and nobody learns from a 143-line report sitting in
a directory they never open. Four changes followed:

- **End-of-session digest** — the Stop hook now prints an 8-line summary to the terminal the
  moment the session ends: final health, peak context, anomalies, a one-line takeaway, and where
  the full report lives. The reflection comes to the engineer, not the other way around.
- **Session-over-session comparison** — the digest and report compare the session against the
  previous one (peak context, error rate, anomalies, time in WARN/CRITICAL) with a one-sentence
  verdict. This closes the feedback loop the educational goal requires: *did I run a better
  session than last time?*
- **Report diet** — the health timeline now shows only transitions and notable turns; runs of
  steady turns collapse into a single marker row. The report reads as a story, not a log.
- **Intro banner** — the live-log view opens with a menu explaining the five signals, weights,
  thresholds, and available commands (full version on first run, compact afterwards).

Implementing the comparison surfaced one latent bug: session pruning iterated over the
`sessions/latest` symlink, and `shutil.rmtree` on a symlink raises — the Stop hook would have
crashed once enough sessions accumulated. The comparison feature depends on pruning working, so
the bug became visible the moment the code around it was read with intent. Fixed by excluding
symlinks from the prune list.

### Iteration 8 — Stop does not mean session end

**Symptom:** The new digest appeared in `health.log` every few minutes during a live session —
one digest reporting "72 turns," then turns 73–77 of ordinary work, then another digest reporting
"77 turns."

**Prompt that triggered discovery:** *"why session digest once every few minutes?"*

**Root cause:** Claude Code's `Stop` hook event fires **every time Claude finishes responding to
a prompt** — not when the session ends. The entire project had been built on the wrong reading of
the event name. The mistake was invisible for the project's whole life because the old Stop output
was a single dim line; the 9-line digest made the actual firing frequency impossible to miss.

This is the same bug class as the token-counting bug: a plausible assumption about an external
system's semantics ("an event called Stop fires when the session stops") that reality disagrees
with — and like that bug, it was caught not by tests but by a human watching real output and
asking why it looked wrong.

**Fix:** Split the lifecycle across the two events Claude Code actually provides. `Stop` now
silently refreshes the report after every response — a hidden benefit of the original mistake,
discovered in the process: `show-report` is always current mid-session. A new `SessionEnd` hook
(actual termination: `/exit`, Ctrl+C, `/clear`) generates the final report and prints the digest —
once. Verified by simulating both hooks: Stop produces no output, SessionEnd prints the digest.

**First real user test, three paper cuts.** Using the tool from a *different* project directory —
the actual deployment scenario — immediately surfaced three issues no amount of testing from the
repo root would have found: the digest's `./show-report` hint only works from the repo root
(fixed: the digest now prints the absolute path); a 1-turn restart session became the comparison
baseline, rendering the comparison meaningless (fixed: sessions under 5 turns are skipped as
baselines); and the new `~/.local/bin` command symlinks broke the scripts' self-location (fixed:
`readlink -f`). The lesson generalizes: test from the user's directory, not the developer's.

---

# 3. Critical Reflection — Evaluating and Improving the AI's Output

## 3.1 The Verification Pattern

The recurring pattern across this project: **the AI wrote plausible code, the code ran without
errors, and it produced wrong values silently.** All 21 initial tests passed while token counts
were zero. The report narrative looked data-driven while three of its numbers were literals from
one specific session. The health lines were being generated, formatted, and discarded.

None of these bugs were caught by the test suite. Every one was caught by running the tool on
real input and reading the output with skepticism:

- The token bug was found by inspecting `state.json` after a two-word prompt: *"try it out."*
- The swallowed-output bug was found by noticing that `events.jsonl` was growing while the
  terminal stayed silent — evidence that isolated the output path as the failure point.
- The hardcoded-values bug was found by directly questioning whether generated output was computed
  or templated. No test covered the reporter; only the question found it.

The conclusion drawn, and applied for the rest of the project: green tests verify the math you
told the code to do; only real data verifies the assumptions the code makes about the world.

## 3.2 Finding 1 — Silent tool calls caused false CRITICAL readings (found, accepted, then fixed)

Running the monitor on a real 89-turn session revealed the length-trend scorer firing CRITICAL
repeatedly during healthy work. Investigation against raw `events.jsonl` identified the cause:
silent bash commands — `mkdir`, `git add`, file writes with no output — produce near-empty
response wrappers (~94 characters). These collapse the late-window average:

```python
burst_short = [700, 720, 680, 710, 700, 50, 60, 45, 55, 50]
score_response_length_trend(burst_short)
# → {'score': 20, 'level': 'CRITICAL', 'change_pct': -92.6}
```

The scorer logic is correct. The design assumption is wrong: it assumed all response text reflects
reasoning quality. A `mkdir` that succeeds silently is not evidence of degradation.

**How it was handled — in three stages:**

1. **Documented as an accepted risk.** At the time of discovery, the fix looked like it required
   separating tool-response tokens from assistant-text tokens — an architectural change out of
   proportion for a prototype. The limitation was written up rather than patched.
2. **Re-scoped after reflection.** Closer inspection showed a much smaller fix was available at
   the hook level: the hook already has the assistant's prose text per turn, so it can simply skip
   length tracking for turns where Claude wrote no text at all.
3. **Fixed.** `hooks/post_tool_use.py` now appends to the length-trend window only when the
   response text is non-empty:

   ```python
   # Only track turns where Claude actually wrote text — silent tool calls
   # (mkdir, git add, etc.) have empty response_text and would collapse the
   # late-window average with near-zero values.
   if sig["response_text"].strip():
       state.setdefault("response_lengths", []).append(len(sig["response_text"]))
   ```

   Silent tool calls can no longer enter the window, so the `burst_short` collapse cannot arise
   from them. The oscillating CRITICAL readings visible in the 89-turn session report
   (Appendix B) date from before this fix and are preserved there as the evidence that motivated it.

This finding is the most instructive artifact in the project: a correctly-implemented scorer
producing wrong conclusions because of a wrong assumption about what the input data represents.
Unit tests could never have caught it — the function behaves exactly as specified. Only running
the system on real session data and questioning a reading that contradicted experience
("the session was healthy; why is this CRITICAL?") exposed it.

## 3.3 Finding 2 — Overconfidence scorer is inactive in this domain (accepted)

The overconfidence scorer returned GOOD(100) on every turn of the real 89-turn session. Testing on
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

Claude Code's language is assertive by nature — it writes code and explains decisions without
hedging. Words like "definitely" and "obviously" are rare in engineering output. The certainty
word list was calibrated for conversational text, not code-writing context.

A second, structural limitation compounds this: the `PostToolUse` hook fires after a tool call,
and the available text is whatever Claude wrote *before* calling the tool — often empty or under
the 60-character minimum, which returns GOOD(100) by default.

**Design response:** The signal's weight was kept at 10% intentionally — low enough that the
miscalibration cannot distort the overall score. The limitation is documented rather than hidden.
The correct fix is a domain-specific word list calibrated on real Claude Code transcripts; that is
future work, not a quick patch, and pretending otherwise would be worse than the honest "this
signal is currently dormant."

## 3.4 Finding 3 — A predicted failure mode didn't materialize (hypothesis rejected)

The oscillating length trend in the live session report led to a hypothesis: alternating
long/short responses — code writing followed by short confirmations — would cause false positives.
Testing disproved it:

```python
alternating = [800, 100, 800, 100, 800, 100, 800, 100]
score_response_length_trend(alternating)
# → {'score': 100, 'level': 'GOOD', 'trend': 'stable', 'change_pct': 0.0}
```

The early/late window averaging cancels alternating patterns — both windows average to the same
value. The oscillation observed in the live report was caused by silent tool calls (Finding 1),
not by response rhythm. The hypothesis was wrong, and discovering that mattered: it redirected the
fix to the actual cause.

A correct evaluation tests hypotheses, not just code. Finding that a predicted failure mode does
not exist is as useful as finding one that does — it updates the model of the system.

## 3.5 What This Changed About Directing the AI

Three working rules came out of this project:

1. **Demand an observable output path before trusting integration code.** The token bug survived
   six turns because nothing made the wrong values visible. The first prompt after any AI-written
   integration code should be "try it out" — run it on real input and read what comes back.
2. **Question every literal in generated output.** The hardcoded-values bug was invisible in both
   the code and the output. The question "is this computed or templated?" is cheap to ask and, in
   this project, found a bug nothing else would have.
3. **When a reading contradicts experience, investigate the reading, not just the code.** Both
   real findings (silent tool calls, dormant overconfidence) came from noticing that the monitor's
   story and the session's reality disagreed — and treating that disagreement as data.

---

# 4. Testing Approach

## 4.1 Strategy: Four Layers

No single validation method was sufficient for this project. Four were used, each covering what
the previous one structurally cannot:

| Layer | Artifact | What it covers |
|-------|----------|----------------|
| Unit tests | `tests/test_scorer.py` (54 tests) | Threshold math in `scorer.py` — exact boundary values, edge cases |
| Visual calibration | `tests/visualize_scorer.py` | The *shape* of each scoring curve — catches miscalibration that point assertions miss |
| Live session testing | Real monitored Claude Code sessions | Assumptions about external data formats; real-world signal behavior |
| Eval harness | `evals/eval_harness.py` (5 synthetic sessions) | The full scoring pipeline — weighted combination, action thresholds, regression detection |

The unit tests anchor the math. The visualization reviews calibration. Live sessions validate the
system against reality. The eval harness freezes correct pipeline behavior and guards it against
future change. §4.2 maps how each layer performed across the project's actual timeline.

## 4.2 Testing and Evaluation Across Project Stages

Different validation methods were used at different stages. This table maps what was used, when,
and what each approach caught — and missed:

| Stage | Method | What it caught | What it missed |
|-------|--------|----------------|----------------|
| 1. Initial implementation | None — code written in one pass | Nothing yet | The token extraction bug, silently accumulating zeros |
| 2. Live session test | Install hooks, run a real session, inspect output | Token counts all zero — wrong assumption about external data. Caught within minutes of the first real run | Nothing structural — the observable output made the bug obvious |
| 3. Unit tests + visualization | 54 boundary tests; full-curve rendering | Unrepresentative test inputs (60-char guard neutralizing every overconfidence sample) | Everything outside `scorer.py` |
| 4. Live session analysis | 89-turn session; manual inspection of `events.jsonl` and `health.log` | Silent-tool-call false CRITICALs; dormant overconfidence signal; rejected the alternating-pattern hypothesis | The hardcoded report values |
| 5. Code review via user question | "Are these values computed or hardcoded?" | Three hardcoded literals in the report narrative — valid Python, no crash, no test coverage | — |
| 6. Eval harness | 5 synthetic sessions vs. analytically-derived goldens | (Guards against) weight/threshold regressions, action boundary errors | Signal extraction, hooks, report correctness; domain calibration |

The pattern across all six stages: **the closer to the system boundary a validation method sits,
the more real bugs it finds — and the harder it is to automate.** The unit tests were easiest to
write and caught the least. The live session test required no test code at all and caught the most
critical bug in the project.

## 4.3 The Eval Harness

The harness (`evals/eval_harness.py`) replays five synthetic session JSON files through
`scorer.py` directly. For each session it computes a final health score, a recommended action
(continue / verify / start_fresh), and an anomaly count, then compares against golden outputs with
tolerances — score ±10, action exact, anomaly count ±1. Before saving results, it loads the
previous run to detect regressions, and exits non-zero on failure so it chains with the unit tests:

```bash
python3 -m pytest tests/test_scorer.py -v && python3 evals/eval_harness.py
```

**Why synthetic sessions, not real ones:** real session data would also work as input, but the
golden values for synthetic sessions are *derived analytically before running the harness* — not
captured from a run and frozen. This means a scorer change that produces a wrong result is
detected even if the harness has never seen "correct" output from the changed code.

**What the five sessions test:**

| Session | Scenario | Expected outcome |
|---------|----------|------------------|
| `healthy_session` | Clean session, no problems | All GOOD — action stays "continue" |
| `context_degraded` | Context, trend, errors, overconfidence all failing | 4 anomalies — "start_fresh" |
| `instruction_drift` | Context and trend both at WARN, no errors | 2 anomalies — "verify" |
| `confident_wrong` | Overconfidence + context + declining output | Score 60 → WARN → "verify", *not* start_fresh — overconfidence carries only 10% weight |
| `silent_failures` | Errors just crossing the CRITICAL threshold | Score 50 → "start_fresh" — 43% error rate at 20% weight tips the total below 55 |

The last two cases are the most diagnostic: they verify that the weighted combination pushes the
score to the correct side of an action threshold, which no single-scorer unit test can check.

**Results (run 2026-06-10):**

```
DevFlow Monitor Eval Harness — 2026-06-10T09:28:47
────────────────────────────────────────────────────
healthy_session        PASS  score:91   action:continue               anomalies:0
context_degraded       PASS  score:24   action:start_fresh            anomalies:4
instruction_drift      PASS  score:66   action:verify                 anomalies:2
confident_wrong        PASS  score:60   action:verify                 anomalies:3
silent_failures        PASS  score:50   action:start_fresh            anomalies:3
────────────────────────────────────────────────────
5/5 passed
```

The 54 unit tests pass alongside (`54 passed in 0.05s`).

## 4.4 What Is NOT Tested, and Why

**`signals.py` — transcript parsing and signal extraction.** Untested — and it is where the only
real production bug occurred. Testing it requires either a mock transcript file (brittle — coupled
to Claude Code's internal JSONL format, which can change without notice) or a live hook invocation
(an integration test that depends on Claude Code running). Neither was implemented in this phase.
**Risk accepted:** if Claude Code changes the transcript structure or renames token buckets,
`signals.py` will silently return zeros again. The events log makes this *detectable* — token
counts dropping to 0 mid-session is observable — but there is no automated check.

**`hooks/post_tool_use.py` — end-to-end orchestration.** Untested. It is the main integration
point. A bug here (e.g., a key error in the state dict) would crash the hook silently — Claude
Code continues working, monitoring stops. **Risk accepted:** monitoring is an observability aid,
not a safety system; a silent monitoring outage costs insight, not correctness of the user's work.

**`reporter.py` — report generation.** Untested. Output is human-readable and easy to check by
eye, but there are no automated assertions on content or structure. This is where the
hardcoded-values bug lived — a direct demonstration of the accepted risk materializing.

**The overconfidence signal at runtime.** Known-dormant in this domain (§3.3). Kept at 10% weight
so its miscalibration cannot distort the overall score.

**The repetition fingerprint truncates at 120 characters.** `score_repetition` matches calls on
tool name + the first 120 chars of the stringified input, so two long commands that differ only
after that point are counted as identical and can trigger a false WARN. Found while extending the
visual calibration tool with boundary cases, and demonstrated there ("Fingerprint collision" row:
two different 153-char commands → WARN, repeat count 2). **Risk accepted:** a longer fingerprint
would weaken detection of near-identical retries — the pattern the signal exists to catch — and at
10% weight a false WARN costs only 6 health points.

## 4.5 Bugs Caught — and What Caught Them

| Bug | Caught by | Could the test suite have caught it? |
|-----|-----------|--------------------------------------|
| Token counts silently zero | Live session + state inspection ("try it out") | No — wrong assumption about external data; `signals.py` untested |
| Health lines swallowed by TUI | Live session + log-vs-terminal discrepancy | No — requires a real terminal and a real TUI |
| health.log never created | Attempting `tail -f` from a second terminal | No — directory-ordering bug in untested hook path |
| Overconfidence samples all under length guard | Visual calibration output | Partially — a unit test on the *samples* would have; none existed |
| Hardcoded values in report narrative | User questioning the output directly | No — reporter untested; values were valid code |
| Silent tool calls → false CRITICAL | Live 89-turn session analysis | No — the scorer behaves exactly as specified; the spec was wrong |

The honest summary: **the unit tests caught none of the significant bugs.** Every one was found by
running the tool against real output and inspecting what came back. The test suite's value is
different — it anchors the scoring math so that calibration and pipeline changes (which the live
findings demanded) could be made without fear of breaking the arithmetic. The eval harness now
extends that guarantee to the pipeline level.

## 4.6 What Remains Unverified

- Behavior when Claude Code restarts mid-session with the same `session_id`
- Whether `duration_ms` accurately reflects slow vs. fast tool calls across tool types
- Whether the 60-character minimum for overconfidence is well-calibrated for real sessions
- Whether the 10-turn window for length trend is right — short sessions hit the 4-turn minimum
  and never generate a meaningful trend signal
- The silent-tool-call fix (§3.2) against a fresh long live session — confirming the false
  CRITICALs are gone in practice is part of the pre-demo checklist

---

# 5. Demo

_\<This section is completed after the recording. Planned content:\>_

The recorded demo shows the monitor working end to end on a live Claude Code session:

1. **Live health lines** — a real session with timestamped health lines appearing on `/dev/tty`
   after every tool call, inside the same terminal Claude Code runs in.
2. **Second-terminal monitoring** — `./tail-health` (or the `/devflow-log` skill) opening with
   the signals intro banner, then streaming `sessions/latest/health.log` in real time.
3. **An anomaly firing** — a deliberately repeated tool call triggering the repetition signal.
4. **Session end → digest** — the Stop hook printing the 8-line digest in the session terminal:
   final health, anomalies, the takeaway, and the comparison with the previous session.
5. **The full report** — `./show-report`: the transitions-only timeline, anomaly detail, the
   previous-session comparison table, and the data-driven "What We Can Learn" section.
6. **The test stack** — `pytest` (54/54) and the eval harness (5/5) run live.

**Recording link:** _\<added after recording\>_

---

# Appendix A — Repository Layout

```
devflow-monitor/
├── devflow/
│   ├── session.py       # per-session state (load/save JSON, prune old sessions)
│   ├── signals.py       # parse hook payload; read token counts from transcript JSONL
│   ├── scorer.py        # pure scoring functions — no I/O
│   ├── output.py        # health lines → /dev/tty + health.log
│   └── reporter.py      # Markdown report generator
├── hooks/
│   ├── post_tool_use.py # PostToolUse hook — signals → scoring → output → state
│   └── stop.py          # Stop hook — generates report, prunes old sessions
├── evals/
│   ├── synthetic_sessions/   # 5 designed test cases
│   ├── golden_outputs/       # analytically-derived expected results
│   └── eval_harness.py       # pipeline eval with regression detection
├── tests/
│   ├── test_scorer.py        # 54 boundary-case unit tests
│   └── visualize_scorer.py   # visual calibration tool
├── examples/
│   └── report_0.md      # real 89-turn session report (pre-fix; evidence for §3.2)
├── sessions/            # runtime data (state.json, events.jsonl, health.log, report.md)
├── install.py           # registers hooks (--global or project); deploys /devflow-log skill
└── tail-health          # live tail of sessions/latest/health.log from any directory
```

# Appendix B — Example Session Report (Excerpt)

From `examples/report_0.md`, generated by the Stop hook after the real 89-turn session
(2026-06-09, 1h 44m). This session predates the silent-tool-call fix; the oscillating length-trend
CRITICALs visible here are the evidence behind Finding 1 (§3.2).

> ## Session Overview
>
> This session dipped to WARN but finished healthy. After 89 turns it ended at GOOD(80) — warning
> signals were transient, not persistent.
>
> **Notable moment (18:07:29):** Health first entered WARN territory (score 71), driven by context
> pressure (OK, score 75) combined with falling response length (CRITICAL, score 20).
>
> | Metric | Value |
> |--------|-------|
> | Turns | 89 |
> | Tool calls | 89 |
> | Tool errors | 0 (0%) |
> | Peak context | 164,173 tokens (82% of limit) |
> | Final context | 34,044 tokens (17%) |
>
> | Time | Health | Context | Trend | Errors | Notes |
> |------|--------|---------|-------|--------|-------|
> | 18:07:27 | **GOOD**(91) | 75 (OK) | 100 | 100 |  |
> | 18:07:29 | **WARN**(71) | 75 (OK) | 20 (CRITICAL) | 100 | responses shortening fast (>50% drop); → first WARN |
> | ... | | | | | |
> | 19:10:44 | **WARN**(66) | 40 (WARN) | 50 (WARN) | 100 | context crossed 75% |
> | ... | | | | | |
> | 19:28:17 | **GOOD**(100) | 100 | 100 | 100 | ← recovered to GOOD |
>
> **The session dipped to WARN but self-corrected.** This is the most common healthy outcome for
> longer sessions: signals briefly enter warning territory as the session shifts task type, then
> recover. The monitor's job here is to confirm the recovery happened — not just flag the dip.
