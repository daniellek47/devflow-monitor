---
description: Open a live tail of the current Claude Code session's DevFlow Monitor health log in a new terminal window or tmux pane.
---

Open the DevFlow Monitor health log for the current session as a live window.

## Steps

Run this exact bash command:

```bash
SCRIPT="$HOME/projects/drivenets-assignment/devflow-monitor/tail-health"

if [ -n "$TMUX" ]; then
    tmux new-window -n devflow "bash '$SCRIPT'"
    echo "OPENED_TMUX"
elif command -v wt.exe &>/dev/null; then
    wt.exe new-tab -- wsl.exe bash "$SCRIPT"
    echo "OPENED_WT"
else
    echo "NO_WINDOW"
fi
```

Then tell the user:
- `OPENED_TMUX` → "Opened a new tmux window named 'devflow'."
- `OPENED_WT` → "Opened a new Windows Terminal tab with the live health log."
- `NO_WINDOW` → tell them to run: `bash ~/projects/drivenets-assignment/devflow-monitor/tail-health`

Do not do anything else.
