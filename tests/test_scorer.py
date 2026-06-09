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


# ── context pressure ──────────────────────────────────────────────────────────

class TestContextPressure:
    def test_zero_tokens(self):
        r = score_context_pressure(0)
        assert r["level"] == "GOOD" and r["score"] == 100

    def test_just_below_50pct(self):
        r = score_context_pressure(99_999)
        assert r["level"] == "GOOD"

    def test_exactly_50pct(self):
        r = score_context_pressure(100_000)
        assert r["level"] == "OK" and r["score"] == 75

    def test_just_below_75pct(self):
        r = score_context_pressure(149_999)
        assert r["level"] == "OK"

    def test_exactly_75pct(self):
        r = score_context_pressure(150_000)
        assert r["level"] == "WARN" and r["score"] == 40

    def test_just_below_90pct(self):
        r = score_context_pressure(179_999)
        assert r["level"] == "WARN"

    def test_exactly_90pct(self):
        r = score_context_pressure(180_000)
        assert r["level"] == "CRITICAL" and r["score"] == 10

    def test_at_limit(self):
        r = score_context_pressure(200_000)
        assert r["level"] == "CRITICAL"
        assert abs(r["ratio"] - 1.0) < 0.001

    def test_over_limit(self):
        # Should not crash — ratio > 1.0 is still CRITICAL
        r = score_context_pressure(250_000)
        assert r["level"] == "CRITICAL"
        assert r["ratio"] > 1.0

    def test_ratio_field_accuracy(self):
        r = score_context_pressure(100_000)
        assert abs(r["ratio"] - 0.5) < 0.001


# ── response length trend ─────────────────────────────────────────────────────

class TestResponseLengthTrend:
    def test_empty(self):
        r = score_response_length_trend([])
        assert r["trend"] == "insufficient_data" and r["score"] == 100

    def test_one_item(self):
        r = score_response_length_trend([500])
        assert r["trend"] == "insufficient_data"

    def test_three_items(self):
        # Boundary: 4 is the minimum — 3 should still be insufficient
        r = score_response_length_trend([500, 400, 300])
        assert r["trend"] == "insufficient_data"

    def test_exactly_four_items_stable(self):
        r = score_response_length_trend([200, 200, 200, 200])
        assert r["level"] == "GOOD"

    def test_exactly_four_items_falling_fast(self):
        # First half avg=500, second half avg=100 → change=-80%
        r = score_response_length_trend([500, 500, 100, 100])
        assert r["level"] == "CRITICAL"

    def test_window_uses_only_last_10(self):
        # First 5 entries are catastrophic; last 10 are stable.
        # Scorer should ignore the first 5 and report GOOD.
        old_bad = [1000] * 5 + [50] * 5     # turns 1-10: massive drop
        recent_stable = [200, 210, 205, 195, 210]  # turns 11-15
        history = old_bad + recent_stable
        # Window = last 10 = [50]*5 + [200..210]*5
        # early avg ~50, late avg ~204 → rising trend → GOOD
        r = score_response_length_trend(history)
        assert r["level"] == "GOOD"

    def test_slight_decline_boundary(self):
        # Change just under -10% → OK, not WARN
        history = [100, 100, 100, 100, 100, 89, 89, 89, 89, 89]
        r = score_response_length_trend(history)
        assert r["level"] == "OK"

    def test_warn_boundary(self):
        # Change around -26% → WARN
        history = [100, 100, 100, 100, 100, 74, 74, 74, 74, 74]
        r = score_response_length_trend(history)
        assert r["level"] == "WARN"

    def test_critical_boundary(self):
        history = [500] * 5 + [100] * 5
        r = score_response_length_trend(history)
        assert r["level"] == "CRITICAL"
        assert r["change_pct"] <= -50.0

    def test_zero_early_avg_no_crash(self):
        # If early turns had 0 output tokens, should not divide by zero
        r = score_response_length_trend([0, 0, 0, 0, 100, 100])
        assert r["level"] == "GOOD"

    def test_rising_trend_still_good(self):
        history = [100, 100, 100, 100, 100, 200, 200, 200, 200, 200]
        r = score_response_length_trend(history)
        assert r["level"] == "GOOD"


# ── error rate ────────────────────────────────────────────────────────────────

class TestErrorRate:
    def test_no_calls(self):
        r = score_error_rate(0, 0)
        assert r["level"] == "GOOD" and r["rate"] == 0.0

    def test_no_errors(self):
        r = score_error_rate(0, 50)
        assert r["level"] == "GOOD"

    def test_just_below_10pct(self):
        r = score_error_rate(1, 11)     # ~9.1%
        assert r["level"] == "GOOD"

    def test_exactly_10pct(self):
        r = score_error_rate(1, 10)
        assert r["level"] == "OK" and r["score"] == 75

    def test_just_below_20pct(self):
        r = score_error_rate(19, 100)   # 19%
        assert r["level"] == "OK"

    def test_exactly_20pct(self):
        r = score_error_rate(2, 10)
        assert r["level"] == "WARN" and r["score"] == 50

    def test_just_below_40pct(self):
        r = score_error_rate(39, 100)
        assert r["level"] == "WARN"

    def test_exactly_40pct(self):
        r = score_error_rate(4, 10)
        assert r["level"] == "CRITICAL" and r["score"] == 15

    def test_all_errors(self):
        r = score_error_rate(10, 10)
        assert r["level"] == "CRITICAL" and r["rate"] == 1.0


# ── overconfidence ────────────────────────────────────────────────────────────

class TestOverconfidence:
    def test_empty_string(self):
        r = score_overconfidence("")
        assert r["level"] == "GOOD" and r["certainty_ratio"] == 0.0

    def test_exactly_at_min_length_boundary(self):
        # 59 chars → too short, skip analysis
        r = score_overconfidence("a" * 59)
        assert r["level"] == "GOOD"

    def test_exactly_at_min_length(self):
        # 60 chars but no signal words → GOOD
        r = score_overconfidence("a" * 60)
        assert r["level"] == "GOOD"

    def test_no_signal_words(self):
        r = score_overconfidence("The function reads the file and returns the parsed result.")
        assert r["level"] == "GOOD" and r["certainty_ratio"] == 0.0

    def test_only_hedging(self):
        text = "I think this might work, but it could probably fail. Perhaps we should verify."
        r = score_overconfidence(text)
        assert r["level"] == "GOOD"
        assert r["certainty_ratio"] == 0.0

    def test_mixed_leans_hedging(self):
        text = "This will definitely work, but I think we should probably double-check the output."
        r = score_overconfidence(text)
        # 1 certainty ("definitely") vs several hedging → ratio < 0.6 → GOOD
        assert r["level"] == "GOOD"

    def test_high_certainty_flagged(self):
        text = (
            "This will definitely fix the issue. Obviously the problem is simply "
            "the config. Absolutely clear. Never fails. Certainly correct."
        )
        r = score_overconfidence(text)
        assert r["level"] == "WARN"
        assert r["certainty_ratio"] >= 0.8

    def test_certainty_ratio_zero_when_no_words(self):
        r = score_overconfidence("The output confirms the process completed successfully. " * 3)
        assert r["certainty_ratio"] == 0.0

    def test_case_insensitive(self):
        text = "DEFINITELY going to work. OBVIOUSLY the right approach. CERTAINLY correct."
        r = score_overconfidence(text)
        assert r["level"] == "WARN"


# ── repetition ────────────────────────────────────────────────────────────────

class TestRepetition:
    def _call(self, name, cmd="ls"):
        return {"tool_name": name, "tool_input": {"command": cmd}}

    def test_no_history(self):
        r = score_repetition([], self._call("Bash"))
        assert r["level"] == "GOOD" and r["repeat_count"] == 0

    def test_single_occurrence(self):
        r = score_repetition([self._call("Bash")], self._call("Bash"))
        assert r["level"] == "GOOD"

    def test_exactly_two_matches_warn(self):
        call = self._call("Bash")
        r = score_repetition([call, call], call)
        assert r["level"] == "WARN" and r["repeat_count"] == 2

    def test_exactly_three_matches_critical(self):
        call = self._call("Bash")
        r = score_repetition([call, call, call], call)
        assert r["level"] == "CRITICAL"

    def test_different_inputs_not_flagged(self):
        r = score_repetition(
            [self._call("Bash", "ls"), self._call("Bash", "ls")],
            self._call("Bash", "pwd"),
        )
        assert r["level"] == "GOOD"

    def test_same_tool_different_name_not_flagged(self):
        r = score_repetition(
            [self._call("Read"), self._call("Read")],
            self._call("Bash"),
        )
        assert r["level"] == "GOOD"

    def test_only_last_6_considered(self):
        # 10 matching calls outside the window, new call doesn't repeat within last 6
        call = self._call("Bash")
        different = self._call("Read")
        history = [call] * 10 + [different] * 6
        r = score_repetition(history, call)
        assert r["level"] == "GOOD"

    def test_input_truncated_to_120_chars(self):
        long_input = {"command": "x" * 200}
        call = {"tool_name": "Bash", "tool_input": long_input}
        # Two identical long-input calls should still match via truncation
        r = score_repetition([call, call], call)
        assert r["level"] == "WARN"


# ── overall health ────────────────────────────────────────────────────────────

class TestOverallHealth:
    def _scores(self, **overrides):
        base = {k: {"score": 100} for k in
                ("context", "length_trend", "error_rate", "overconfidence", "repetition")}
        for k, v in overrides.items():
            base[k] = {"score": v}
        return base

    def test_all_perfect(self):
        h = overall_health(self._scores())
        assert h["level"] == "GOOD" and h["score"] == 100

    def test_all_zero(self):
        h = overall_health(self._scores(**{k: 0 for k in
            ("context", "length_trend", "error_rate", "overconfidence", "repetition")}))
        assert h["level"] == "CRITICAL" and h["score"] == 0

    def test_context_dominates(self):
        # Context is 35% weight — a score of 10 should drag overall below 80
        h = overall_health(self._scores(context=10))
        assert h["score"] < 80

    def test_good_threshold(self):
        # Score of exactly 80 → GOOD
        # context(35%) + length(25%) + error(20%) + conf(10%) + rep(10%)
        # If context=80, rest=100: 80*0.35 + 100*0.65 = 28+65=93 → GOOD
        h = overall_health(self._scores(context=80))
        assert h["level"] == "GOOD"

    def test_warn_threshold(self):
        # Drive score into WARN band (55–79)
        h = overall_health(self._scores(context=10, length_trend=10))
        assert h["level"] in ("WARN", "CRITICAL")

    def test_missing_key_ignored(self):
        # Partial scores dict should not crash
        partial = {"context": {"score": 100}, "error_rate": {"score": 100}}
        h = overall_health(partial)
        assert "score" in h and "level" in h

    def test_weights_sum_correctly(self):
        # All scores = 60 → weighted sum = 60 regardless of weights
        h = overall_health(self._scores(**{k: 60 for k in
            ("context", "length_trend", "error_rate", "overconfidence", "repetition")}))
        assert h["score"] == 60
