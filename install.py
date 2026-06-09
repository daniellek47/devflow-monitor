#!/usr/bin/env python3
"""
Register DevFlow Monitor hooks in .claude/settings.json (project-scoped).

Run once from the devflow-monitor directory:
    python3 install.py
"""
import json
import sys
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / ".claude" / "settings.json"
HOOKS_DIR = Path(__file__).parent / "hooks"
PYTHON = sys.executable


def main() -> None:
    post_tool_hook = str(HOOKS_DIR / "post_tool_use.py")
    stop_hook = str(HOOKS_DIR / "stop.py")

    new_hooks = {
        "PostToolUse": [
            {
                "matcher": ".*",
                "hooks": [{"type": "command", "command": f"{PYTHON} {post_tool_hook}"}],
            }
        ],
        "Stop": [
            {
                "hooks": [{"type": "command", "command": f"{PYTHON} {stop_hook}"}]
            }
        ],
    }

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if SETTINGS_PATH.exists():
        try:
            existing = json.loads(SETTINGS_PATH.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse existing {SETTINGS_PATH}, overwriting.")

    existing.setdefault("hooks", {}).update(new_hooks)
    SETTINGS_PATH.write_text(json.dumps(existing, indent=2))

    print(f"Hooks registered in {SETTINGS_PATH}")
    print(f"  PostToolUse → {post_tool_hook}")
    print(f"  Stop        → {stop_hook}")


if __name__ == "__main__":
    main()
