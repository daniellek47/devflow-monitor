# DevFlow Monitor — Claude Code Instructions

## What this project is

A passive session health advisor for Claude Code — an educational tool, not a linter. It hooks into Claude Code's PostToolUse, Stop, and SessionEnd events, scores five health signals on every tool call, writes health lines to the terminal, and at session end prints a short digest (with a comparison against the previous session) and generates a Markdown report.

Hook event semantics matter here: **Stop fires every time Claude finishes responding to a prompt, NOT at session end.** SessionEnd fires on actual termination (/exit, Ctrl+C, /clear). Getting this wrong originally made the digest print after every response.

This project monitors its own Claude Code sessions — the hooks are installed and active here.

## Architecture

File-backed state machine. No background daemon. Each hook invocation is an isolated Python subprocess that:
1. Reads a JSON payload from stdin (provided by Claude Code)
2. Loads `sessions/<session_id>/state.json`
3. Scores signals, emits output, writes updated state
4. Exits

State files:
- `sessions/<id>/state.json` — live state, updated after every tool call
- `sessions/<id>/events.jsonl` — raw event log, one JSON line per tool call
- `sessions/<id>/health.log` — plain-text health lines (ANSI stripped), for tail -f monitoring
- `sessions/<id>/report.md` — written by the Stop hook when the session ends

## Key files

| File | Role |
|------|------|
| `devflow/signals.py` | Parses hook payload; reads token counts from transcript file |
| `devflow/scorer.py` | Pure scoring functions — no I/O, easy to unit test |
| `devflow/session.py` | Load/save state.json, append events.jsonl, prune old sessions, load previous session for comparison |
| `devflow/output.py` | Writes to /dev/tty (not stderr) so Claude Code TUI doesn't swallow output; also writes to health.log |
| `devflow/reporter.py` | Markdown report, end-of-session digest (`build_digest`), session-over-session comparison |
| `hooks/post_tool_use.py` | PostToolUse hook — orchestrates signals → scoring → output → state |
| `hooks/stop.py` | Stop hook — fires after every Claude response; silently refreshes the report so show-report is always current |
| `hooks/session_end.py` | SessionEnd hook — fires on actual session termination; generates final report, prints the digest, prunes |
| `install.py` | Registers hooks in Claude Code settings (--global or project-scoped); deploys /devflow-log skill; on --global also symlinks show-report and tail-health into ~/.local/bin |
| `tail-health` | Live tail of sessions/latest/health.log; prints the signals intro banner first (full on first run, compact after — marker: `sessions/.intro_shown`) |
| `show-report` | Opens sessions/latest/report.md from any directory (glow if available, else $PAGER) |
| `evals/eval_harness.py` | Replays synthetic sessions through scorer.py, compares against golden outputs |

## Signals and weights

| Signal | Weight | Key thresholds |
|--------|--------|----------------|
| context | 35% | OK at 50%, WARN at 75%, CRITICAL at 90% |
| length_trend | 25% | WARN at -25%, CRITICAL at -50% over last 10 turns |
| error_rate | 20% | OK at 10%, WARN at 20%, CRITICAL at 40% |
| overconfidence | 10% | WARN when certainty words > 80% of hedge+certainty vocab |
| repetition | 10% | WARN at 2× same call in 6-call window, CRITICAL at 3× |

Overall: GOOD ≥ 80, WARN 55–79, CRITICAL < 55.

length_trend only tracks turns where Claude wrote non-empty text — silent tool calls (mkdir, git add) are filtered out in `post_tool_use.py` so their near-zero responses can't collapse the late-window average into a false CRITICAL.

## Token counts

Token counts are NOT in the hook payload. They live in a separate session transcript JSONL at `transcript_path` in the payload. `signals.py` reads that file, matches by `tool_use_id`, and sums three buckets: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.

This was a bug in the first implementation — the code assumed tokens were in the payload and silently got zeros for six turns.

## Running tests

```bash
python3 -m pytest tests/test_scorer.py -v
python3 tests/visualize_scorer.py   # visual calibration, not pytest
python3 evals/eval_harness.py       # pipeline eval across 5 synthetic sessions
```

54 boundary-case unit tests covering scorer.py only. The eval harness replays synthetic sessions through the full scoring pipeline and compares against golden outputs — run it whenever scorer.py changes. signals.py and the hooks are untested — they require a live Claude Code session or a real transcript file.

## Simulating a hook call

```bash
echo '{"session_id":"test","tool_name":"Bash","tool_input":{"command":"ls"},"tool_response":"","tool_use_id":"","transcript_path":"","duration_ms":500}' \
  | python3 hooks/post_tool_use.py

# Refresh the report silently (fires after every Claude response):
echo '{"session_id":"test"}' | python3 hooks/stop.py

# End the simulated session (prints digest, writes report, prunes):
echo '{"session_id":"test"}' | python3 hooks/session_end.py
```

Warning: the Stop hook prunes real session directories (MAX_SESSIONS=3). Back up `sessions/` before simulating session lifecycles.

## Output goes to /dev/tty

`output.py` writes to `/dev/tty` directly, not stderr. Claude Code's TUI redraws after each tool call and swallows stderr from hook subprocesses. `/dev/tty` bypasses TUI rendering. Falls back to stderr if /dev/tty is unavailable.

## End-of-session digest and comparison

When the session actually terminates, `session_end.py`:
1. Loads the previous session's state via `session.load_previous_state(sid)` — the most recently active session directory other than the current one (by state.json mtime) that has at least `session.MIN_COMPARISON_TURNS` (5) turns; trivial sessions are skipped as baselines
2. Generates `report.md`, including a "Compared With Your Previous Session" table (peak context, error rate, anomalies, turns in WARN/CRITICAL — lower is better for all four) with a one-sentence verdict
3. Prints an 8-line digest via `reporter.build_digest` to /dev/tty and health.log: final health, peak context, anomaly summary, a one-line takeaway, the comparison, and the report path

`stop.py` does steps 1–2 silently after every Claude response — the report is always fresh mid-session, the digest appears only once, at the true end.

The report's health timeline shows only transitions and noted turns; runs of steady turns collapse into `⋯` marker rows.

## Session pruning

`session.MAX_SESSIONS = 3` — old session directories beyond this limit are deleted by the Stop hook. Change this constant to keep more or fewer sessions (the comparison only needs one previous session). A `sessions/latest` symlink is maintained by `save_state` and always points to the most recently active session. Pruning skips symlinks — `shutil.rmtree` on a symlink raises, which used to crash the Stop hook once 4+ entries accumulated.

## Anomaly storage format

Anomalies are stored as structured dicts (since the educational report update):
```json
{"type": "repetition", "turn": 16, "ts": "16:08:55", "tool_name": "Bash", "tool_input": {...}, "repeat_count": 2, "score": 40}
```
The reporter handles legacy string anomalies (from before this change) by reading `events.jsonl` to enrich them with tool input.

## Known limitations

### Overconfidence scorer is inactive in code-writing context

The overconfidence scorer returned GOOD(100) on every turn of a real 89-turn session. Claude Code's language is assertive by nature — it writes code and explains decisions without hedging. Words like "definitely" and "obviously" are rare in engineering output. The certainty word list was calibrated for conversational text. Weight kept at 10% intentionally — low enough that miscalibration doesn't distort the overall score. The correct fix is a domain-specific word list calibrated on real Claude Code transcripts.

### Repetition fingerprint truncates at 120 chars

`score_repetition` matches calls on tool name + the first 120 chars of the stringified input. Two long commands that differ only after that point (e.g., similar `sed`/`curl` invocations with different tails) are counted as the same call and can trigger a false WARN. Demonstrated in `tests/visualize_scorer.py` ("Fingerprint collision"). Accepted: longer fingerprints make near-identical retries (the real signal) harder to catch, and at 10% weight a false WARN costs 6 health points.

### Alternating long/short responses do not cause false positives

A predicted failure mode: alternating long responses (code writing) and short ones (confirmations) would produce false WARN/CRITICAL on length trend. Tested:

```python
alternating = [800, 100, 800, 100, 800, 100, 800, 100]
score_response_length_trend(alternating)
# → {'score': 100, 'level': 'GOOD', 'change_pct': 0.0}
```

The early/late window averaging cancels out alternating patterns.

## What is intentionally not in scope

- No extra API calls from hooks (heuristics only — no LLM judge)
- No background daemon or web server
- No database — session-only JSON files
- No cross-session analytics
