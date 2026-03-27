---
name: workspace-coding
description: Use when the task requires reading files, editing files, running local project commands, or validating changes inside the current workspace.
allowed-tools: [list_dir, read_file, write_file, append_file, make_dir, run_command]
metadata:
  short-description: Workspace file and command workflow
---

# Workspace Coding

Use this skill when the task is primarily about changing files in the current workspace and validating those changes.

## Workflow

1. Inspect the workspace before editing.
2. Read the exact files you plan to change.
3. Make the smallest viable edit.
4. Run a targeted validation command after the change.
5. Report what changed and how it was verified.

## Guardrails

- Do not run broad destructive commands.
- Prefer targeted validation over full-project commands.
- Keep edits inside the active workspace.
- If a write or command tool requires approval, request it through the normal tool flow.
