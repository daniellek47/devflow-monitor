from typing import List

MODEL_CONTEXT_LIMIT = 200_000

# Words that signal high certainty — a proxy for potential overconfidence
_CERTAINTY = frozenset({
    "definitely", "absolutely", "certainly", "always", "never", "obviously",
    "clearly", "undoubtedly", "guaranteed", "for sure", "of course",
    "trivially", "simply just", "100%", "without a doubt",
})

# Words that signal appropriate epistemic humility
_HEDGING = frozenset({
    "might", "could", "probably", "possibly", "perhaps", "i think",
    "i believe", "it seems", "likely", "unlikely", "not sure", "uncertain",
    "may ", "worth checking", "double-check", "should verify", "let me verify",
    "i'm not certain", "double check",
})


# --- individual signal scorers ---

def score_context_pressure(input_tokens: int) -> dict:
    ratio = input_tokens / MODEL_CONTEXT_LIMIT
    if ratio >= 0.90:
        return {"score": 10, "level": "CRITICAL", "ratio": ratio}
    if ratio >= 0.75:
        return {"score": 40, "level": "WARN", "ratio": ratio}
    if ratio >= 0.50:
        return {"score": 75, "level": "OK", "ratio": ratio}
    return {"score": 100, "level": "GOOD", "ratio": ratio}

def score_response_length_trend(output_token_history: List[int]) -> dict:
    if len(output_token_history) < 4:
        return {"score": 100, "level": "GOOD", "trend": "insufficient_data", "change_pct": 0.0}

    window = output_token_history[-10:]
    mid = len(window) // 2
    early_avg = sum(window[:mid]) / mid
    late_avg = sum(window[mid:]) / (len(window) - mid)

    if early_avg == 0:
        return {"score": 100, "level": "GOOD", "trend": "stable", "change_pct": 0.0}

    change = (late_avg - early_avg) / early_avg

    if change < -0.50:
        return {"score": 20, "level": "CRITICAL", "trend": "falling_fast", "change_pct": round(change * 100, 1)}
    if change < -0.25:
        return {"score": 50, "level": "WARN", "trend": "falling", "change_pct": round(change * 100, 1)}
    if change < -0.10:
        return {"score": 75, "level": "OK", "trend": "slight_decline", "change_pct": round(change * 100, 1)}
    return {"score": 100, "level": "GOOD", "trend": "stable", "change_pct": round(change * 100, 1)}

# NOTE: This is a heuristic, not a reliable signal.
# Documented limitation: certainty vocabulary varies by task type.
# A refactoring task produces fewer hedges than an analysis task by nature.
# Weight kept low (10%) intentionally. See PDF section 4.

def score_error_rate(errors: int, total: int) -> dict:
    if total == 0:
        return {"score": 100, "level": "GOOD", "rate": 0.0}
    rate = errors / total
    if rate >= 0.40:
        return {"score": 15, "level": "CRITICAL", "rate": round(rate, 2)}
    if rate >= 0.20:
        return {"score": 50, "level": "WARN", "rate": round(rate, 2)}
    if rate >= 0.10:
        return {"score": 75, "level": "OK", "rate": round(rate, 2)}
    return {"score": 100, "level": "GOOD", "rate": round(rate, 2)}


def score_overconfidence(text: str) -> dict:
    if not text or len(text) < 60:
        return {"score": 100, "level": "GOOD", "certainty_ratio": 0.0}

    low = text.lower()
    certainty_hits = sum(1 for w in _CERTAINTY if w in low)
    hedging_hits = sum(1 for w in _HEDGING if w in low)
    total = certainty_hits + hedging_hits

    if total == 0:
        return {"score": 100, "level": "GOOD", "certainty_ratio": 0.0}

    ratio = certainty_hits / total
    if ratio >= 0.80:
        return {"score": 30, "level": "WARN", "certainty_ratio": round(ratio, 2)}
    if ratio >= 0.60:
        return {"score": 70, "level": "OK", "certainty_ratio": round(ratio, 2)}
    return {"score": 100, "level": "GOOD", "certainty_ratio": round(ratio, 2)}


def score_repetition(recent_calls: list, new_call: dict) -> dict:
    # Compare tool name + first 120 chars of stringified input
    def sig(c):
        return (c.get("tool_name", ""), str(c.get("tool_input", ""))[:120])

    new_sig = sig(new_call)
    matches = sum(1 for c in recent_calls[-6:] if sig(c) == new_sig)

    if matches >= 3:
        return {"score": 10, "level": "CRITICAL", "repeat_count": matches}
    if matches >= 2:
        return {"score": 40, "level": "WARN", "repeat_count": matches}
    return {"score": 100, "level": "GOOD", "repeat_count": matches}


# --- aggregate ---

def overall_health(scores: dict) -> dict:
    weights = {
        "context":       0.35,
        "length_trend":  0.25,
        "error_rate":    0.20,
        "overconfidence":0.10,
        "repetition":    0.10,
    }
    total = sum(
        scores[k]["score"] * w
        for k, w in weights.items()
        if k in scores
    )
    score = round(total)
    if score >= 80:
        level = "GOOD"
    elif score >= 55:
        level = "WARN"
    else:
        level = "CRITICAL"
    return {"score": score, "level": level}
