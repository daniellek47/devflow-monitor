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
)


# --- context pressure ---

def test_context_good():
    r = score_context_pressure(40_000)
    assert r["level"] == "GOOD"
    assert r["score"] == 100

def test_context_ok():
    r = score_context_pressure(110_000)
    assert r["level"] == "OK"

def test_context_warn():
    r = score_context_pressure(160_000)
    assert r["level"] == "WARN"

def test_context_critical():
    r = score_context_pressure(185_000)
    assert r["level"] == "CRITICAL"
    assert r["score"] <= 10


# --- response length trend ---

def test_trend_insufficient_data():
    r = score_response_length_trend([100, 90])
    assert r["trend"] == "insufficient_data"
    assert r["score"] == 100

def test_trend_stable():
    r = score_response_length_trend([200, 210, 195, 205, 200, 210])
    assert r["level"] == "GOOD"

def test_trend_falling_fast():
    r = score_response_length_trend([500, 490, 480, 200, 150, 100, 80, 60])
    assert r["level"] in ("WARN", "CRITICAL")

def test_trend_falling_critical():
    history = [500] * 5 + [100] * 5
    r = score_response_length_trend(history)
    assert r["level"] == "CRITICAL"


# --- error rate ---

def test_error_rate_none():
    r = score_error_rate(0, 0)
    assert r["level"] == "GOOD"
    assert r["score"] == 100

def test_error_rate_good():
    r = score_error_rate(1, 20)
    assert r["level"] == "GOOD"

def test_error_rate_warn():
    r = score_error_rate(3, 10)
    assert r["level"] == "WARN"

def test_error_rate_critical():
    r = score_error_rate(5, 10)
    assert r["level"] == "CRITICAL"


# --- overconfidence ---

def test_overconfidence_clean():
    text = "I think this might work, but you should probably verify the output."
    r = score_overconfidence(text)
    assert r["level"] == "GOOD"

def test_overconfidence_flagged():
    text = (
        "This will definitely work. Obviously the solution is simply to delete "
        "the file. Absolutely no issues with this approach. Certainly correct."
    )
    r = score_overconfidence(text)
    assert r["level"] in ("WARN", "CRITICAL")
    assert r["certainty_ratio"] > 0.5

def test_overconfidence_short_text():
    r = score_overconfidence("ok")
    assert r["level"] == "GOOD"


# --- repetition ---

def test_repetition_none():
    calls = [{"tool_name": "Read", "tool_input": {"path": "/a"}},
             {"tool_name": "Bash", "tool_input": {"command": "ls"}}]
    r = score_repetition(calls, {"tool_name": "Edit", "tool_input": {}})
    assert r["level"] == "GOOD"

def test_repetition_warn():
    call = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    calls = [call, call]
    r = score_repetition(calls, call)
    assert r["level"] == "WARN"

def test_repetition_critical():
    call = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    r = score_repetition([call] * 6, call)
    assert r["level"] == "CRITICAL"


# --- overall health ---

def test_overall_good():
    scores = {
        "context": {"score": 100},
        "length_trend": {"score": 100},
        "error_rate": {"score": 100},
        "overconfidence": {"score": 100},
        "repetition": {"score": 100},
    }
    h = overall_health(scores)
    assert h["level"] == "GOOD"
    assert h["score"] == 100

def test_overall_degraded_by_context():
    scores = {
        "context": {"score": 10},
        "length_trend": {"score": 100},
        "error_rate": {"score": 100},
        "overconfidence": {"score": 100},
        "repetition": {"score": 100},
    }
    h = overall_health(scores)
    assert h["score"] < 80

def test_overall_critical():
    scores = {k: {"score": 10} for k in
              ("context", "length_trend", "error_rate", "overconfidence", "repetition")}
    h = overall_health(scores)
    assert h["level"] == "CRITICAL"
