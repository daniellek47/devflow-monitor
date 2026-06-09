# Executive Summary — DevFlow Monitor

## Problem Statement

Claude Code sessions degrade in ways that are easy to miss in the moment. The context window fills
up silently. Answers get shorter. The model starts repeating tool calls. A session that felt
productive can, in hindsight, have been producing low-quality output for the last twenty minutes.

There is no built-in signal for this. The developer only finds out after the fact — when they
re-read the output and notice it got thin, or when the next session has to undo what the last one
did. The question DevFlow Monitor tries to answer is: *can you know a session is degrading while it
is still happening, without changing anything about how you work?*

## Goals

1. Passively observe Claude Code sessions using the existing hook system — no workflow changes.
2. Collect measurable health signals on every tool call: context window pressure, response length
   trend, tool error rate, overconfident language, and stuck-loop repetition.
3. Surface those signals in real time as timestamped lines in the terminal.
4. Generate a structured session report at the end that supports honest retrospective review.

The project was intentionally scoped as a personal learning tool, not a production service. That
constraint drove several key choices: heuristics-only (no extra API calls), session-only state (no
database), and plain CLI output (no daemon, no web server).

## Architecture

DevFlow Monitor is a file-backed state machine that advances one step per tool call.

Claude Code's `PostToolUse` hook is configured to invoke a Python script after every tool use. The
script reads a JSON payload from stdin, extracts signals, loads a per-session state file, scores
five health dimensions, emits a status line to stderr, and writes updated state back to disk. A
second hook fires on `Stop` and generates a Markdown report from the accumulated state.

There is no persistent background process. Each hook invocation is an isolated Python process that
lives for under a second. State persists between calls through a single JSON file at
`sessions/<session_id>/state.json`.

**Scoring** combines five weighted heuristics into a 0–100 health score:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Context pressure | 35% | Total tokens (including cache) as a fraction of the 200k limit |
| Response length trend | 25% | Whether output tokens are falling over the last 10 turns |
| Tool error rate | 20% | Fraction of tool calls that returned errors |
| Overconfidence | 10% | Ratio of certainty words to hedging words in Claude's prose |
| Repetition | 10% | Same tool + input appearing multiple times within a 6-call window |

A score ≥ 80 is GOOD, 55–79 is WARN, below 55 is CRITICAL.

## Outcome

The tool was built and tested in a single Claude Code session. That session was itself monitored.

**The session produced 39 tool calls over approximately one hour, reaching 100,565 tokens (50% of
the context limit) with zero tool errors.** One anomaly was detected: a repeated Bash call at
turn 16. By the end of the session, the health score had dropped to WARN(71) — driven by the
combination of context pressure crossing the 50% threshold and the response-length trend score
falling to CRITICAL(20) as the session shifted from writing large files to making small focused
edits.

That final WARN rating is meaningful: it correctly identified that the session had entered a phase
where Claude's output was getting shorter, even though the work was still accurate. That is
precisely the kind of signal the tool was designed to surface.

The project also produced one genuine debugging story. The initial implementation assumed token
counts were available directly in the hook payload. They are not — they live in a separate session
transcript file at a path provided by the payload. The code ran silently with zero token counts for
six turns before a live test revealed the issue. Fixing it required reading the actual Claude Code
data model, something the AI-generated code had gotten wrong on the first attempt. That incident
is documented in the development section and in the git history.

## Repository

`https://github.com/daniellek47/devflow-monitor`
