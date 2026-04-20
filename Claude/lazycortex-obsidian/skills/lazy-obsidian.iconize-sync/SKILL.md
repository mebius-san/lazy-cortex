---
name: lazy-obsidian.iconize-sync
description: "Resolve Obsidian file/folder icons from frontmatter and write them to the Iconize plugin's `data.json`. Driven by a local declarative icon-map (`.claude/obsidian-iconize/icon-map.json`). Subcommands: `sync`, `sync-staged`, `reconcile`, `install-hooks`, `check-versions`. Callable from `.githooks/pre-commit` and Claude Code's PostToolUse hook."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Write
argument-hint: "<subcommand> [args] | sync <path> | sync-staged | reconcile [--prefix PATH] | install-hooks | check-versions"
---

# Iconize Sync (Obsidian)

Drives icon resolution for Obsidian vaults that follow a frontmatter-based
semantics (role/stage/status/etc.). The worker reads
`.claude/obsidian-iconize/icon-map.json` — a local, consumer-owned file that
holds the vault's registries and declarative matchers — and writes path-keyed
entries into `.obsidian/plugins/obsidian-icon-folder/data.json`.

## Prerequisite

Run `lazy-obsidian.iconize-install` first to scaffold the protocol doc,
icon-map, and hooks into your vault.

## Subcommands

All subcommands accept `--vault <root>`, `--dry-run`, and
`--icon-map <path>` as global flags BEFORE the subcommand.

### `sync <vault-relative-path>`

Resolve one file. Reads the file's frontmatter, matches against the icon-map,
writes 0/1/2 `data.json` entries.

Invoked by: the PostToolUse hook, or manually.

### `sync-staged`

Iterate `git diff --cached --name-only --diff-filter=ACMR -- '*.md'`, resolve
each, batch-write. Re-stages `data.json` so the commit includes the write.

Invoked by: `.githooks/pre-commit`.

### `reconcile [--prefix <path>]`

Walk every `.md` file (under `--prefix` if given, else whole vault), compute
desired entries, apply them, drop any stale in-prefix path-keys that aren't
desired anymore. Reserved keys (`settings`, `rules`, `recentlyUsedIcons`) are
never touched. Use after bulk frontmatter changes.

### `install-hooks`

Write `.githooks/pre-commit` (shim that execs the plugin worker, with
`HOOK_VERSION` marker) and merge the PostToolUse entry into
`.claude/settings.json`. Idempotent — removes any prior iconize_sync entries
before re-inserting.

### `check-versions`

Compare installed shim's `HOOK_VERSION` marker vs the worker's current
`HOOK_VERSION`. Exit 0 on MAJOR match, exit 5 on MAJOR drift. Run after
`/plugin update lazycortex-obsidian@lazycortex`.

## How to run

The worker lives at `${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py`. Invoke via:

```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py <subcommand> [flags] [args]
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation error (bad args, bad icon-map, unknown subcommand) |
| 2 | data.json / vault not found |
| 3 | Concurrent-write conflict unresolved after retries |
| 4 | Target path missing (strict mode only) |
| 5 | Hook version drift (MAJOR mismatch) |

## Logging

Log every invocation to `./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md`
per `lazy-log.logging`. Use two separate steps: `Bash(mkdir -p ...)` then `Write`.

## Non-goals

- Managing the Iconize `rules` array.
- Installing icon packs.
- Writing frontmatter (consumer skills own that).
