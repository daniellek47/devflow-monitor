#!/usr/bin/env python3
"""
Register DevFlow Monitor hooks in a Claude Code settings.json.

Global install (monitors every Claude Code session on this machine):
    python3 install.py --global

Project install (monitors only sessions started from the current directory):
    python3 install.py

Uninstall:
    python3 install.py --uninstall
    python3 install.py --global --uninstall
"""
import json
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).parent / "hooks"
PYTHON = sys.executable


def main() -> None:
    args = set(sys.argv[1:])
    global_install = "--global" in args
    uninstall = "--uninstall" in args

    if global_install:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path(__file__).parent / ".claude" / "settings.json"

    post_tool_hook = str(HOOKS_DIR / "post_tool_use.py")
    stop_hook = str(HOOKS_DIR / "stop.py")

    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse {settings_path}, overwriting.")

    if uninstall:
        hooks = existing.get("hooks", {})
        hooks.pop("PostToolUse", None)
        hooks.pop("Stop", None)
        existing["hooks"] = hooks
        settings_path.write_text(json.dumps(existing, indent=2))
        print(f"Hooks removed from {settings_path}")
        return

    existing.setdefault("hooks", {}).update({
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
    })
    settings_path.write_text(json.dumps(existing, indent=2))

    scope = "global (all projects)" if global_install else "project-scoped"
    print(f"DevFlow Monitor installed [{scope}]")
    print(f"  Settings: {settings_path}")
    print(f"  Reports will be written to: {Path(__file__).parent / 'sessions'}")


if __name__ == "__main__":
    main()
