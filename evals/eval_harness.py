#!/usr/bin/env python3
"""
Eval harness: replay synthetic sessions through scorer.py, compare against golden outputs.

Usage:
    python3 evals/eval_harness.py

Exit 0 if all cases pass, exit 1 if any fail (suitable for CI).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from devflow.scorer import (
    score_context_pressure,
    score_response_length_trend,
    score_error_rate,
    score_overconfidence,
    overall_health,
)

EVALS_DIR = Path(__file__).parent
SESSIONS_DIR = EVALS_DIR / "synthetic_sessions"
GOLDEN_DIR = EVALS_DIR / "golden_outputs"
RESULTS_DIR = EVALS_DIR / "results"

CASES = [
    ("healthy_session",   "healthy_session_golden.json"),
    ("context_degraded",  "context_degraded_golden.json"),
    ("instruction_drift", "instruction_drift_golden.json"),
    ("confident_wrong",   "confident_wrong_golden.json"),
    ("silent_failures",   "silent_failures_golden.json"),
]

_DIVIDER = "─" * 52


def _action(health: dict) -> str:
    if health["level"] == "GOOD":
        return "continue"
    if health["level"] == "WARN":
        return "verify"
    return "start_fresh"


def _run_session(interactions: list) -> dict:
    """Replay interactions through scorer functions; return final scored state."""
    total_count = len(interactions)
    error_count = sum(1 for ix in interactions if ix.get("error", False))
    response_lengths = [
        ix["response_length"]
        for ix in interactions
        if ix.get("response_length", 0) > 0
    ]

    last = interactions[-1]
    hedging_text = " ".join(last.get("hedging_phrases", []))

    scores = {
        "context":        score_context_pressure(last.get("tokens_used", 0)),
        "length_trend":   score_response_length_trend(response_lengths),
        "error_rate":     score_error_rate(error_count, total_count),
        "overconfidence": score_overconfidence(hedging_text),
        "repetition":     {"score": 100, "level": "GOOD", "repeat_count": 0},
    }
    health = overall_health(scores)
    anomaly_count = sum(
        1 for s in scores.values() if s["level"] in ("WARN", "CRITICAL")
    )

    return {
        "health":        health,
        "action":        _action(health),
        "anomaly_count": anomaly_count,
        "scores":        scores,
    }


def _compare(actual: dict, golden: dict) -> list:
    """Return list of failure strings; empty means pass."""
    failures = []
    if abs(actual["health"]["score"] - golden["health_score"]) > 10:
        failures.append(
            f"score:{actual['health']['score']} outside ±10 of expected {golden['health_score']}"
        )
    if actual["action"] != golden["recommended_action"]:
        failures.append(
            f"action:{golden['recommended_action']} ← got {actual['action']}"
        )
    if abs(actual["anomaly_count"] - golden["anomaly_count"]) > 1:
        failures.append(
            f"anomalies:{actual['anomaly_count']} outside ±1 of expected {golden['anomaly_count']}"
        )
    return failures


def _load_previous_pass_map() -> dict:
    """Return {case_name: passed} from the most recent results file, or {}."""
    if not RESULTS_DIR.exists():
        return {}
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        return {}
    try:
        data = json.loads(files[-1].read_text())
        return {c["name"]: c["passed"] for c in data.get("cases", [])}
    except Exception:
        return {}


def _fmt_pass(name: str, actual: dict) -> str:
    action_col = f"action:{actual['action']}"
    return (
        f"{name:<22} PASS  score:{actual['health']['score']:<4} "
        f"{action_col:<28}  anomalies:{actual['anomaly_count']}"
    )


def _fmt_fail(name: str, actual: dict, failures: list) -> str:
    action_failure = next((f for f in failures if f.startswith("action:")), None)
    action_col = action_failure if action_failure else f"action:{actual['action']}"
    score_failure = next((f for f in failures if f.startswith("score:")), None)
    score_col = score_failure if score_failure else f"score:{actual['health']['score']}"
    anomaly_failure = next((f for f in failures if f.startswith("anomalies:")), None)
    anomaly_col = anomaly_failure if anomaly_failure else f"anomalies:{actual['anomaly_count']}"
    return f"{name:<22} FAIL  {score_col:<16} {action_col:<32}  {anomaly_col}"


def main() -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"\nLucid Eval Harness — {timestamp}")
    print(_DIVIDER)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    prev_pass = _load_previous_pass_map()

    cases = []
    for session_name, golden_file in CASES:
        session_path = SESSIONS_DIR / f"{session_name}.json"
        golden_path = GOLDEN_DIR / golden_file

        if not session_path.exists():
            print(f"  WARNING: missing session file: {session_path.name}")
            continue
        if not golden_path.exists():
            print(f"  WARNING: missing golden file: {golden_path.name}")
            continue

        try:
            session_data = json.loads(session_path.read_text())
            golden = json.loads(golden_path.read_text())
        except Exception as e:
            print(f"  WARNING: could not parse {session_name}: {e}")
            continue

        interactions = session_data.get("interactions", [])
        if not interactions:
            print(f"  WARNING: {session_name} has no interactions, skipping")
            continue

        actual = _run_session(interactions)
        failures = _compare(actual, golden)
        passed = len(failures) == 0

        if passed:
            print(_fmt_pass(session_name, actual))
        else:
            print(_fmt_fail(session_name, actual, failures))
            if prev_pass.get(session_name) is True:
                print(f"  ⚠ REGRESSION: {session_name} passed in last run, fails now")

        cases.append({
            "name":                  session_name,
            "passed":                passed,
            "expected_score":        golden["health_score"],
            "actual_score":          actual["health"]["score"],
            "expected_action":       golden["recommended_action"],
            "actual_action":         actual["action"],
            "expected_anomaly_count": golden["anomaly_count"],
            "actual_anomaly_count":  actual["anomaly_count"],
            "failures":              failures,
        })

    total = len(cases)
    passed_count = sum(1 for c in cases if c["passed"])
    print(_DIVIDER)
    print(f"{passed_count}/{total} passed\n")

    results = {
        "run_timestamp": timestamp,
        "passed":        passed_count,
        "failed":        total - passed_count,
        "cases":         cases,
    }
    results_file = RESULTS_DIR / f"{timestamp.replace(':', '-')}.json"
    results_file.write_text(json.dumps(results, indent=2))

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
