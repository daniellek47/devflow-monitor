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
SKILL_SRC = Path(__file__).parent / ".claude" / "skills" / "devflow-log" / "SKILL.md"
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
    session_end_hook = str(HOOKS_DIR / "session_end.py")

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
        hooks.pop("SessionEnd", None)
        existing["hooks"] = hooks
        settings_path.write_text(json.dumps(existing, indent=2))
        if global_install:
            _remove_command_links()
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
        "SessionEnd": [
            {
                "hooks": [{"type": "command", "command": f"{PYTHON} {session_end_hook}"}]
            }
        ],
    })
    settings_path.write_text(json.dumps(existing, indent=2))

    if global_install and SKILL_SRC.exists():
        skill_dst = Path.home() / ".claude" / "skills" / "devflow-log" / "SKILL.md"
        skill_dst.parent.mkdir(parents=True, exist_ok=True)
        skill_dst.write_text(SKILL_SRC.read_text())
        print(f"  Skill /devflow-log installed to: {skill_dst}")

    if global_install:
        _create_command_links()

    scope = "global (all projects)" if global_install else "project-scoped"
    print(f"DevFlow Monitor installed [{scope}]")
    print(f"  Settings: {settings_path}")
    print(f"  Reports will be written to: {Path(__file__).parent / 'sessions'}")


COMMANDS = ("show-report", "tail-health")
BIN_DIR = Path.home() / ".local" / "bin"


def _create_command_links() -> None:
    """Symlink the CLI scripts into ~/.local/bin so they work from any
    directory (the digest and docs refer to them by bare name)."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for name in COMMANDS:
        src = Path(__file__).parent / name
        dst = BIN_DIR / name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)
        print(f"  Command linked: {dst} -> {src}")


def _remove_command_links() -> None:
    for name in COMMANDS:
        dst = BIN_DIR / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  Command removed: {dst}")


if __name__ == "__main__":
    main()
