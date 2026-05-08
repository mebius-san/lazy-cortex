---
name: lazy-obsidian.iconize-sync
description: "Resolve Obsidian file/folder icons from a declarative icon-map and write the result into each note's `iconize_icon` / `iconize_color` frontmatter keys. The worker never touches `.obsidian/plugins/obsidian-icon-folder/data.json` — Iconize itself paints non-folder-note icons live from frontmatter, and the bundled `iconize-reloader` plugin bridges folder-note frontmatter into folder-keyed `data.json` entries. Driven by `.claude/iconize/obsidian-icon-map.json`. Subcommands: `sync`, `sync-staged`, `reconcile`, `reconcile-plugin`, `reconcile-dirty`, `install-hooks`, `check-versions`. Callable from `.githooks/pre-commit`, Claude Code's PostToolUse hook, and Claude Code's Stop hook."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Write
argument-hint: "<subcommand> [args] | sync <path> | sync-staged | reconcile [--prefix PATH] | reconcile-plugin <plugin> | reconcile-dirty | install-hooks | check-versions"
execution-discipline-waiver: "thin dispatcher to iconize_sync.py — discipline belongs in the Python worker, not the SKILL.md"
---
# Iconize Sync (Obsidian)

Drives icon resolution for Obsidian vaults that follow a frontmatter-based
semantics (role/stage/status/etc.). The worker reads
`.claude/iconize/obsidian-icon-map.json` — a local, consumer-owned file that
holds the vault's registries and declarative matchers — and writes
`iconize_icon` / `iconize_color` keys into each matched note's YAML
frontmatter. It never edits Iconize's `data.json`.

Two consumers turn that frontmatter into icons on screen:

- **Iconize plugin** (with `iconInFrontmatterEnabled: true`) reads `iconize_icon`
  live from any `.md` file's frontmatter and paints the file's tab + title.
- **Iconize Reloader plugin** (bundled by `lazy-obsidian.iconize-install`)
  watches folder-note frontmatter and bridges it into folder-keyed entries in
  `.obsidian/plugins/obsidian-icon-folder/data.json`, which Iconize then paints
  on the folder row in the file-explorer. The reloader is the **sole writer**
  of `data.json`.

## Prerequisite

Run `lazy-obsidian.iconize-install` first to scaffold the protocol doc,
icon-map, and hooks into your vault.

## Subcommands

All subcommands accept `--vault <root>`, `--dry-run`, and
`--icon-map <path>` as global flags BEFORE the subcommand.

### `sync <vault-relative-path>`

Resolve one file. Reads its frontmatter, matches against the icon-map, then
upserts or clears `iconize_icon` / `iconize_color` in that file's frontmatter.

Invoked by: the PostToolUse hook, or manually.

### `sync-staged`

Iterate `git diff --cached --name-only --diff-filter=ACMR -- '*.md'`, resolve
each, batch-rewrite, then re-stage every modified `.md` so the frontmatter
update lands in the same commit.

Invoked by: `.githooks/pre-commit`.

### `reconcile [--prefix <path>]`

Walk every `.md` file (under `--prefix` if given, else whole vault), compute
the desired `iconize_*` frontmatter, and rewrite each file. Files that no
longer match a rule have their `iconize_icon` / `iconize_color` keys cleared.
Use after bulk frontmatter changes or icon-map edits.

### `reconcile-plugin <plugin>`

Plugin-scoped reconcile + auto-stage. Walks `claude/<plugin>/**/*.md` only,
re-resolves icons, rewrites frontmatter where the resolution differs, and
re-stages touched files so they ride the caller's pending commit.

Use case: invoked by the pre-commit pipeline after bumping `claude/<plugin>/.claude-plugin/plugin.json`.
The version delta flips callbacks like `plugin-is-patch-bumped`, so every file
under the plugin's subtree whose color depends on those callbacks (folder
note, README) repaints in the same commit. The full `reconcile` walk would
do the same at vault scope; this one is bounded.

### `reconcile-dirty`

Safety-net for edits that bypass the PostToolUse `Write|Edit` hook (anything
written via `Bash`, a shell script, a bulk rename, etc.). Queries `git status`
for dirty `.md` files — modified, added, deleted, untracked, and renamed — and
reconciles the unique parent directories of those paths in one pass. Silent
no-op on a clean tree or a non-git vault.

Invoked by: Claude Code's `Stop` hook (fires at the end of every agent turn).

### `install-hooks`

Write `.githooks/pre-commit` (shim that runtime-resolves the plugin's
`iconize_sync.py` at exec time, carrying a `HOOK_VERSION` marker). Does **not**
touch consumer `.claude/settings.json` — the PostToolUse hook is shipped by
the plugin itself via `hooks/hooks.json` and is auto-loaded when the plugin
is enabled. Idempotent.

### `check-versions`

Reports two independent drift axes:

- **Shim** — compares the installed `.githooks/pre-commit` `HOOK_VERSION`
  marker vs the worker's current `HOOK_VERSION`.
- **Icon-map schema** — checks the vault's `obsidian-icon-map.json` `schema_version`
  against the worker's `SUPPORTED_SCHEMA` set, and verifies `HOOK_VERSION`
  satisfies the icon-map's optional `min_hook_version`.

Exits 0 when both are ok or schema is merely "missing" (vault not opted in);
exits 5 on shim MAJOR drift, shim missing, or schema incompatible. Run after
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
| 4 | Target path missing (strict mode only) |
| 5 | Hook version drift (MAJOR mismatch) |

## Logging

Log every invocation to `./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md`
per `lazy-log.logging`. Use two separate steps: `Bash(mkdir -p ...)` then `Write`.

## Non-goals

- Editing Iconize's `data.json` (that's the reloader plugin's job).
- Managing the Iconize `rules` array.
- Installing icon packs.
