import re
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

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_log_path = None


def set_log_file(path) -> None:
    global _log_path
    _log_path = path


def _print(text: str) -> None:
    # Write directly to the terminal device so Claude Code's TUI doesn't swallow the output.
    # Falls back to stderr if /dev/tty is unavailable (e.g. in tests or non-interactive shells).
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text + "\n")
            tty.flush()
    except Exception:
        print(text, file=sys.stderr, flush=True)

    if _log_path:
        try:
            with open(_log_path, "a") as f:
                f.write(_ANSI_RE.sub("", text) + "\n")
        except Exception:
            pass


def emit_status(turn: int, input_tokens: int, health: dict, duration_ms: int = 0) -> None:
    ratio = input_tokens / 200_000
    ts = _ts()
    color = _COLORS.get(health["level"], "")
    reset = _COLORS["RESET"]
    bar = _bar(ratio)
    dur = f"  {duration_ms:,}ms" if duration_ms else ""
    _print(
        f"[{ts}] turn={turn:3d}  ctx={bar}{ratio:4.0%}  "
        f"tokens={input_tokens:,}{dur}  "
        f"health={color}{health['level']}({health['score']}){reset}"
    )


def emit(level: str, message: str, detail: str = "") -> None:
    ts = _ts()
    color = _COLORS.get(level, "")
    reset = _COLORS["RESET"]
    suffix = f" ({detail})" if detail else ""
    _print(f"[{ts}] {color}{level:<8}{reset} {message}{suffix}")


def emit_report_path(path: str) -> None:
    dim = _COLORS["DIM"]
    reset = _COLORS["RESET"]
    _print(f"[{_ts()}] {'REPORT':<8} {dim}{path}{reset}")


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _bar(ratio: float, width: int = 10) -> str:
    filled = min(int(ratio * width), width)
    return "█" * filled + "░" * (width - filled)
