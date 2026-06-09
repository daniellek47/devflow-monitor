# DevFlow Monitor — Claude Code Instructions

## What this project is

A passive Claude Code session health monitor. It hooks into Claude Code's PostToolUse and Stop events, scores five health signals on every tool call, writes health lines to the terminal, and generates a Markdown session report when the session ends.

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
| `devflow/session.py` | Load/save state.json, append events.jsonl, prune old sessions |
| `devflow/output.py` | Writes to /dev/tty (not stderr) so Claude Code TUI doesn't swallow output; also writes to health.log |
| `devflow/reporter.py` | Generates the Markdown report from accumulated state |
| `hooks/post_tool_use.py` | PostToolUse hook — orchestrates signals → scoring → output → state |
| `hooks/stop.py` | Stop hook — generates report, prunes old sessions |
| `install.py` | Registers hooks in Claude Code settings (--global or project-scoped) |

## Signals and weights

| Signal | Weight | Key thresholds |
|--------|--------|----------------|
| context | 35% | OK at 50%, WARN at 75%, CRITICAL at 90% |
| length_trend | 25% | WARN at -25%, CRITICAL at -50% over last 10 turns |
| error_rate | 20% | OK at 10%, WARN at 20%, CRITICAL at 40% |
| overconfidence | 10% | WARN when certainty words > 80% of hedge+certainty vocab |
| repetition | 10% | WARN at 2× same call in 6-call window, CRITICAL at 3× |

Overall: GOOD ≥ 80, WARN 55–79, CRITICAL < 55.

## Token counts

Token counts are NOT in the hook payload. They live in a separate session transcript JSONL at `transcript_path` in the payload. `signals.py` reads that file, matches by `tool_use_id`, and sums three buckets: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.

This was a bug in the first implementation — the code assumed tokens were in the payload and silently got zeros for six turns.

## Running tests

```bash
python3 -m pytest tests/test_scorer.py -v
python3 tests/visualize_scorer.py   # visual calibration, not pytest
```

54 boundary-case unit tests covering scorer.py only. signals.py and the hooks are untested — they require a live Claude Code session or a real transcript file.

## Simulating a hook call

```bash
echo '{"session_id":"test","tool_name":"Bash","tool_input":{"command":"ls"},"tool_response":"","tool_use_id":"","transcript_path":"","duration_ms":500}' \
  | python3 hooks/post_tool_use.py
```

## Output goes to /dev/tty

`output.py` writes to `/dev/tty` directly, not stderr. Claude Code's TUI redraws after each tool call and swallows stderr from hook subprocesses. `/dev/tty` bypasses TUI rendering. Falls back to stderr if /dev/tty is unavailable.

## Session pruning

`session.MAX_SESSIONS = 10` — old session directories beyond this limit are deleted by the Stop hook. Change this constant to keep more or fewer sessions.

## Anomaly storage format

Anomalies are stored as structured dicts (since the educational report update):
```json
{"type": "repetition", "turn": 16, "ts": "16:08:55", "tool_name": "Bash", "tool_input": {...}, "repeat_count": 2, "score": 40}
```
The reporter handles legacy string anomalies (from before this change) by reading `events.jsonl` to enrich them with tool input.

## Known limitations

### Silent tool calls cause false CRITICAL on length trend

Silent bash commands (`mkdir`, `git add`, file writes with no output) produce a 94-character empty JSON wrapper as their tool response. These register as near-zero output tokens and collapse the late-window average dramatically, triggering CRITICAL even during a healthy session:

```python
burst_short = [700, 720, 680, 710, 700, 50, 60, 45, 55, 50]
score_response_length_trend(burst_short)
# → {'score': 20, 'level': 'CRITICAL', 'change_pct': -92.6}
```

The scorer logic is correct. The design assumption is wrong: it assumes all output tokens reflect reasoning quality. The correct fix is filtering the length trend to assistant text turns only, not tool response tokens. Not implemented — would require a meaningful architectural change to how signals are extracted.

### Overconfidence scorer is inactive in code-writing context

The overconfidence scorer returned GOOD(100) on every turn of a real 89-turn session. Claude Code's language is assertive by nature — it writes code and explains decisions without hedging. Words like "definitely" and "obviously" are rare in engineering output. The certainty word list was calibrated for conversational text. Weight kept at 10% intentionally — low enough that miscalibration doesn't distort the overall score. The correct fix is a domain-specific word list calibrated on real Claude Code transcripts.

### Alternating long/short responses do not cause false positives

A predicted failure mode: alternating long responses (code writing) and short ones (confirmations) would produce false WARN/CRITICAL on length trend. Tested:

```python
alternating = [800, 100, 800, 100, 800, 100, 800, 100]
score_response_length_trend(alternating)
# → {'score': 100, 'level': 'GOOD', 'change_pct': 0.0}
```

The early/late window averaging cancels out alternating patterns. The oscillation visible in the session report is caused by the silent tool call issue above, not response rhythm.

## What is intentionally not in scope

- No extra API calls from hooks (heuristics only — no LLM judge)
- No background daemon or web server
- No database — session-only JSON files
- No cross-session analytics
