import sys
from datetime import datetime

_COLORS = {
    "GOOD":     "\033[32m",
    "OK":       "\033[33m",
    "WARN":     "\033[33m",
    "CRITICAL": "\033[31m",
    "RESET":    "\033[0m",
    "DIM":      "\033[2m",
}


def emit_status(turn: int, input_tokens: int, health: dict) -> None:
    ratio = input_tokens / 200_000
    ts = _ts()
    color = _COLORS.get(health["level"], "")
    reset = _COLORS["RESET"]
    bar = _bar(ratio)
    print(
        f"[{ts}] turn={turn:3d}  ctx={bar}{ratio:4.0%}  "
        f"tokens={input_tokens:,}  "
        f"health={color}{health['level']}({health['score']}){reset}",
        file=sys.stderr, flush=True,
    )


def emit(level: str, message: str, detail: str = "") -> None:
    ts = _ts()
    color = _COLORS.get(level, "")
    reset = _COLORS["RESET"]
    suffix = f" ({detail})" if detail else ""
    print(
        f"[{ts}] {color}{level:<8}{reset} {message}{suffix}",
        file=sys.stderr, flush=True,
    )


def emit_report_path(path: str) -> None:
    dim = _COLORS["DIM"]
    reset = _COLORS["RESET"]
    print(
        f"[{_ts()}] {'REPORT':<8} {dim}{path}{reset}",
        file=sys.stderr, flush=True,
    )


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _bar(ratio: float, width: int = 10) -> str:
    filled = min(int(ratio * width), width)
    return "█" * filled + "░" * (width - filled)
