---
name: obsidian-cli
description: Interact with Obsidian vaults using the Obsidian CLI to read, create, search, and manage notes, tasks, properties, and more. Also supports plugin and theme development with commands to reload plugins, run JavaScript, capture errors, take screenshots, and inspect the DOM. Use when the user asks to interact with their Obsidian vault, manage notes, search vault content, perform vault operations from the command line, or develop and debug Obsidian plugins and themes.
---

# Obsidian CLI

Use the `obsidian` CLI to interact with a running Obsidian instance. Requires Obsidian to be open.

If your goal is to save or read a full Markdown note from BiliBrain, prefer the dedicated tools `obsidian_write_note` and `obsidian_read_note` instead of composing CLI write commands manually. This skill is mainly for direct CLI usage, inspection, debugging, and power-user operations.

## Critical Windows rule

For tiny one-line content, `obsidian create name="My Note" content="Hello world"` is acceptable.

For full Markdown notes, summaries, exported documents, or anything larger than a few lines, **do not use `content=` as the transport channel**.

Reason:

- shell quoting can break on quotes and newlines
- Windows native command-line length is limited
- Obsidian CLI forwards arguments into the app process; large Markdown payloads are prone to truncation, malformed JSON, silent no-op, or “only title saved”

### Universal rule for full-note writes

When the goal is “save a complete note into Obsidian Vault”, always use this pipeline:

1. Use Obsidian CLI only to get the active vault path:
   `obsidian vault info=path`
2. Compute an exact vault-relative file path such as `folder/note.md`
3. Use `run_command` with `script_shell="powershell"` and `script_body` to write the Markdown directly to the absolute vault path
4. Verify using exact `path=` commands:
   - `obsidian file path=<relative-path>`
   - `obsidian read path=<relative-path>`

This is the default, stable, high-volume-safe solution.

### Unsafe pattern

```bash
obsidian create name="My Note" content="---\ntitle: ...\n## Body\ntext with \"quotes\""
```

### Preferred Windows pattern for full notes

```json
{
  "command": "write obsidian note via filesystem",
  "cwd": ".",
  "timeout_seconds": 60,
  "script_shell": "powershell",
  "script_body": "$vaultPath = (obsidian vault info=path).Trim()\n$relativePath = 'Notes/My Note.md'\n$target = Join-Path $vaultPath $relativePath\nNew-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null\n$content = @'\n---\ntitle: My Note\ndate: 2026-01-04\n---\n\n## Body\n正文内容\n'@\n[System.IO.File]::WriteAllText($target, $content, [System.Text.UTF8Encoding]::new($true))\nobsidian file (\"path=$relativePath\")\nobsidian read (\"path=$relativePath\")"
}
```

## Command reference

Run `obsidian help` to see all available commands. This is always up to date. Full docs: https://help.obsidian.md/cli

## Syntax

**Parameters** take a value with `=`. Quote values with spaces:

```bash
obsidian create name="My Note" content="Hello world"
```

**Flags** are boolean switches with no value:

```bash
obsidian create name="My Note" silent overwrite
```

For short single-line content, `content="Hello world"` is fine.

For multiline content on Windows:

- if it is a tiny snippet, `\n` escaping may work
- if it is a real note, summary, export, or generated document, do not pass it through `content=` at all; write the file directly into the vault

## File targeting

Many commands accept `file` or `path` to target a file. Without either, the active file is used.

- `file=<name>` — resolves like a wikilink (name only, no path or extension needed)
- `path=<path>` — exact path from vault root, e.g. `folder/note.md`

## Vault targeting

Commands target the most recently focused vault by default. Use `vault=<name>` as the first parameter to target a specific vault:

```bash
obsidian vault="My Vault" search query="test"
```

## Common patterns

```bash
obsidian read file="My Note"
obsidian create name="New Note" content="# Hello" template="Template" silent
obsidian append file="My Note" content="New line"
obsidian search query="search term" limit=10
obsidian daily:read
obsidian daily:append content="- [ ] New task"
obsidian property:set name="status" value="done" file="My Note"
obsidian tasks daily todo
obsidian tags sort=count counts
obsidian backlinks file="My Note"
```

Windows-safe full-note write + verify:

```powershell
$vaultPath = (obsidian vault info=path).Trim()
$relativePath = 'Notes/New Note.md'
$target = Join-Path $vaultPath $relativePath
New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
$content = @'
---
title: New Note
date: 2026-01-04
---

## Hello
正文内容
'@
[System.IO.File]::WriteAllText($target, $content, [System.Text.UTF8Encoding]::new($true))
obsidian file ("path=$relativePath")
obsidian read ("path=$relativePath")
```

Use `--copy` on any command to copy output to clipboard. Use `silent` to prevent files from opening. Use `total` on list commands to get a count.

## Plugin development

### Develop/test cycle

After making code changes to a plugin or theme, follow this workflow:

1. **Reload** the plugin to pick up changes:
   ```bash
   obsidian plugin:reload id=my-plugin
   ```
2. **Check for errors** — if errors appear, fix and repeat from step 1:
   ```bash
   obsidian dev:errors
   ```
3. **Verify visually** with a screenshot or DOM inspection:
   ```bash
   obsidian dev:screenshot path=screenshot.png
   obsidian dev:dom selector=".workspace-leaf" text
   ```
4. **Check console output** for warnings or unexpected logs:
   ```bash
   obsidian dev:console level=error
   ```

### Additional developer commands

Run JavaScript in the app context:

```bash
obsidian eval code="app.vault.getFiles().length"
```

Inspect CSS values:

```bash
obsidian dev:css selector=".workspace-leaf" prop=background-color
```

Toggle mobile emulation:

```bash
obsidian dev:mobile on
```

Run `obsidian help` to see additional developer commands including CDP and debugger controls.
