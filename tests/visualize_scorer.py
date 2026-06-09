#!/usr/bin/env python3
"""
Visual walkthrough of all scorer heuristics.
Run: python3 tests/visualize_scorer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from devflow.scorer import (
    score_context_pressure,
    score_response_length_trend,
    score_error_rate,
    score_overconfidence,
    score_repetition,
    overall_health,
    MODEL_CONTEXT_LIMIT,
)

# ── ANSI helpers ──────────────────────────────────────────────────────────────

G  = "\033[32m"   # green
Y  = "\033[33m"   # yellow
R  = "\033[31m"   # red
B  = "\033[1m"    # bold
DIM = "\033[2m"
RST = "\033[0m"

def color(level):
    return {"GOOD": G, "OK": Y, "WARN": Y, "CRITICAL": R}.get(level, "")

def badge(level, score):
    c = color(level)
    return f"{c}{level}({score:3d}){RST}"

def bar(ratio, width=20):
    filled = min(int(ratio * width), width)
    c = R if ratio >= 0.9 else Y if ratio >= 0.75 else G
    return f"{c}{'█' * filled}{'░' * (width - filled)}{RST}"

def section(title):
    print(f"\n{B}{'─' * 60}{RST}")
    print(f"{B}  {title}{RST}")
    print(f"{B}{'─' * 60}{RST}")

def row(label, result, extra=""):
    b = badge(result["level"], result["score"])
    print(f"  {label:<35} {b}  {DIM}{extra}{RST}")


# ── 1. Context pressure ───────────────────────────────────────────────────────

section("1. Context Pressure  (limit = 200,000 tokens)")
print(f"  {'Input tokens':<35} {'Health':<20}  {'Bar'}")
print(f"  {'─'*35} {'─'*20}  {'─'*22}")

cases = [0, 40_000, 100_000, 130_000, 150_000, 170_000, 180_000, 200_000, 250_000]
for tokens in cases:
    r = score_context_pressure(tokens)
    b = badge(r["level"], r["score"])
    pct = r["ratio"] * 100
    print(f"  {tokens:>10,} tokens  ({pct:5.1f}%)        {b}  {bar(r['ratio'])}")


# ── 2. Response length trend ──────────────────────────────────────────────────

section("2. Response Length Trend  (last 10 turns, split in half)")
print(f"  {'Scenario':<38} {'Health':<20}  change%")
print(f"  {'─'*38} {'─'*20}  {'─'*10}")

trend_cases = [
    ("Fewer than 4 turns",          [500, 400, 300]),
    ("Exactly 4 — stable",          [200, 200, 200, 200]),
    ("Slight decline  (~-11%)",      [100]*5 + [89]*5),
    ("Moderate decline (~-26%)",     [100]*5 + [74]*5),
    ("Fast decline    (~-60%)",      [500]*5 + [200]*5),
    ("Critical drop   (~-80%)",      [500]*5 + [100]*5),
    ("Rising trend    (+100%)",      [100]*5 + [200]*5),
    ("Old bad, recent stable",       [50]*5 + [50]*5 + [200]*5),
    ("Zero early avg  (no crash)",   [0]*5   + [100]*5),
    ("Over limit only last 10 seen", [1]*50  + [500]*5 + [500]*5),
]

for label, history in trend_cases:
    r = score_response_length_trend(history)
    chg = f"{r['change_pct']:+.1f}%" if r["trend"] != "insufficient_data" else "n/a"
    print(f"  {label:<38} {badge(r['level'], r['score'])}  {chg}  {DIM}{r['trend']}{RST}")


# ── 3. Error rate ─────────────────────────────────────────────────────────────

section("3. Error Rate  (errors / total calls)")
print(f"  {'errors / total':<20} {'rate':>6}   {'Health'}")
print(f"  {'─'*20} {'─'*6}   {'─'*20}")

error_cases = [
    (0, 0), (0, 20), (1, 20), (2, 20), (3, 20), (4, 10), (5, 10), (10, 10),
]
for errors, total in error_cases:
    r = score_error_rate(errors, total)
    label = f"{errors} / {total}"
    print(f"  {label:<20} {r['rate']:>6.0%}   {badge(r['level'], r['score'])}")


# ── 4. Overconfidence ─────────────────────────────────────────────────────────

section("4. Overconfidence  (certainty vs hedging word ratio)")
print(f"  {DIM}Min length to analyze: 60 chars. Shorter text skips analysis entirely.{RST}\n")
print(f"  {'Text sample':<45} {'chars':>5}  {'Health':<20}  c_ratio")
print(f"  {'─'*45} {'─'*5}  {'─'*20}  {'─'*7}")

conf_cases = [
    # (text, label)
    ("",
     "empty string"),
    ("a" * 59,
     "59 chars — below minimum, skipped"),
    ("a" * 60,
     "60 chars, no signal words"),
    ("The function reads the file and returns the parsed result from disk.",
     "neutral prose (no signal words)"),
    ("I think this might work but we should probably verify the output before committing.",
     "hedging language only"),
    ("This will definitely fix the issue. Obviously the right approach here.",
     "mix: 2 certainty, 0 hedging"),
    ("This will definitely fix it. Obviously correct. Simply run the command and it will work.",
     "certainty heavy (3 signals)"),
    ("Definitely absolutely certainly always obviously clearly undoubtedly guaranteed.",
     "max certainty — all signal words"),
    ("might could probably possibly perhaps i think i believe it seems likely worth checking",
     "max hedging — all hedge words"),
    ("Definitely the right call, though I think we should probably verify. Certainly worth checking.",
     "mixed: certainty + hedging"),
]

for text, label in conf_cases:
    r = score_overconfidence(text)
    preview = f'"{label}"'
    note = f"{DIM}← below min{RST}" if len(text) < 60 else ""
    print(f"  {preview:<45} {len(text):>5}  {badge(r['level'], r['score'])}  {r['certainty_ratio']:.2f}  {note}")


# ── 5. Repetition ─────────────────────────────────────────────────────────────

section("5. Repetition  (same tool+input in last 6 calls)")
print(f"  {'Scenario':<42} {'Health':<20}  repeats")
print(f"  {'─'*42} {'─'*20}  {'─'*7}")

def mk(name="Bash", cmd="ls"):
    return {"tool_name": name, "tool_input": {"command": cmd}}

rep_cases = [
    ("No history",                   [],                          mk()),
    ("1 prior match",                [mk()],                      mk()),
    ("2 prior matches (boundary)",   [mk(), mk()],                mk()),
    ("3 prior matches",              [mk(), mk(), mk()],          mk()),
    ("Different input — no flag",    [mk(cmd="pwd")]*3,           mk(cmd="ls")),
    ("Different tool — no flag",     [mk("Read")]*3,              mk("Bash")),
    ("10 matches outside window",    [mk()]*10 + [mk("Read")]*6,  mk()),
]

for label, history, new_call in rep_cases:
    r = score_repetition(history, new_call)
    print(f"  {label:<42} {badge(r['level'], r['score'])}  {r['repeat_count']}")


# ── 6. Overall health aggregation ────────────────────────────────────────────

section("6. Overall Health  (weighted sum of all 5 signals)")
print(f"  Weights: context=35%  length=25%  errors=20%  confidence=10%  repetition=10%\n")
print(f"  {'Scenario':<45} {'Health':<20}  score")
print(f"  {'─'*45} {'─'*20}  {'─'*5}")

def scores_from(**kwargs):
    base = {k: {"score": 100} for k in
            ("context", "length_trend", "error_rate", "overconfidence", "repetition")}
    for k, v in kwargs.items():
        base[k] = {"score": v}
    return base

health_cases = [
    ("All GOOD (100)",                  scores_from()),
    ("All CRITICAL (0)",                scores_from(**{k: 0 for k in
                                            ("context","length_trend","error_rate","overconfidence","repetition")})),
    ("Context=CRITICAL, rest GOOD",     scores_from(context=10)),
    ("Length=CRITICAL, rest GOOD",      scores_from(length_trend=10)),
    ("Error=CRITICAL, rest GOOD",       scores_from(error_rate=10)),
    ("Context+Length CRITICAL",         scores_from(context=10, length_trend=10)),
    ("All signals at WARN (score=40)",  scores_from(**{k: 40 for k in
                                            ("context","length_trend","error_rate","overconfidence","repetition")})),
    ("All signals at 60",               scores_from(**{k: 60 for k in
                                            ("context","length_trend","error_rate","overconfidence","repetition")})),
]

for label, s in health_cases:
    h = overall_health(s)
    per = "  ".join(
        f"{k[:3]}={s[k]['score']}"
        for k in ("context","length_trend","error_rate","overconfidence","repetition")
    )
    print(f"  {label:<45} {badge(h['level'], h['score'])}  {DIM}{per}{RST}")

print(f"\n{DIM}  Thresholds: GOOD ≥ 80   WARN 55–79   CRITICAL < 55{RST}\n")
