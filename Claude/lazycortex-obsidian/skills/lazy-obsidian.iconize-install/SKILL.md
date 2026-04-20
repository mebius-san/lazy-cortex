---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, pre-commit shim, and PostToolUse hook entry. Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans. Re-runnable; idempotent. Must be run from the consumer vault's git root."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), AskUserQuestion
argument-hint: "[--dry-run] — scaffolds into <repo-root>/.claude/ and <repo-root>/.githooks/"
---

# Install iconize-sync (Obsidian)

Scaffolds the iconize-sync system into the **current git repo** so the
plugin's `lazy-obsidian.iconize-sync` skill can start painting icons from
frontmatter. The repo must contain an Obsidian vault (a `.obsidian/`
directory somewhere — typically at repo root).

## Scope

Project-local only. There is no global scope — iconize-sync is inherently
per-vault.

## Artifacts scaffolded

| Artifact | Target path | Source |
|---|---|---|
| Protocol doc | `.claude/protocol/obsidian.iconizeize.md` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/protocol.md` |
| Icon-map | `.claude/obsidian-iconize/icon-map.json` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/icon-map.json` |
| Pre-commit shim | `.githooks/pre-commit` | Rendered from `pre-commit-shim.sh` via the worker's `install-hooks` |
| PostToolUse entry | `.claude/settings.json` | Rendered from `post-tool-use.snippet.json` via the worker's `install-hooks` |
| Callback dir (empty) | `.claude/callbacks/` | Created empty; user drops executables here |

## Step 1 — Locate repo root and vault

- Repo root: `git rev-parse --show-toplevel`.
- Vault: walk from repo root looking for `.obsidian/`. If none found, abort
  with a message telling the user to initialize Obsidian first.

## Step 2 — Scaffold protocol doc (per-file prompt)

State machine (one `AskUserQuestion` per file):

- **New** (target missing) → install / skip.
- **Unchanged** (byte-identical) → no prompt.
- **Drift** (differ) → show unified diff, ask: **overwrite** / **keep-local**.

Apply the same state machine to the icon-map.

Reading source templates: use `Glob` against `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/*`.
Copy with `Read` + `Write` so diffs are visible to the wizard. Create missing
parents with `Bash(mkdir -p ...)`.

## Step 3 — Install hooks

Invoke the plugin worker's `install-hooks` subcommand. This writes the
pre-commit shim and merges the PostToolUse entry into `.claude/settings.json`.

```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py install-hooks
```

If `core.hooksPath` is not set to `.githooks`, ask the user (single
`AskUserQuestion`): **set-hooksPath** / **leave-as-is**. If set, run
`git config core.hooksPath .githooks`.

## Step 4 — Create callbacks dir

```
mkdir -p .claude/callbacks
```

Leave empty; add a `.gitkeep` so the directory is tracked. (Users drop
executable scripts here to implement exotic `callback:` matchers.)

## Step 5 — Verify

Run the worker's `check-versions`. Expect exit 0. Surface any drift.

Then run `reconcile --dry-run` and print the plan so the user can see what a
full sweep would do. Do not apply.

## Step 6 — Report

Summarize:
- Which artifacts were **created**, **updated**, **unchanged**, or **kept-local**.
- Hook versions installed.
- Next steps: "run `lazy-obsidian.iconize-configure` to seed your registries,
  then run `lazy-obsidian.iconize-sync reconcile` for a first full sweep."

## Step 7 — Log the run

Log to `./.logs/claude/lazy-obsidian.iconize-install/YYYY-MM-DD_HH-MM-SS.md`
per the logging rule. Two-step write: `Bash(mkdir -p ...)` then `Write`.

## Idempotency

Safe to re-run. Drift prompts only fire when content actually differs.
Orphan detection: if `.claude/protocol/obsidian.iconizeize.md` exists but the
plugin no longer ships `protocol.md`, offer deletion. Same for
`icon-map.json`.

## Wizard discipline

Every decision point uses `AskUserQuestion`, one question at a time. Never
bundle "install protocol? install icon-map?" into a single multi-select
prompt.
