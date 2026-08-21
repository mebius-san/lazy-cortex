---
name: lazy-obsidian.iconize-sync
description: "Use when a note's or folder's icon is stale and must be re-resolved from the icon-map — after editing `.claude/iconize/obsidian-icon-map.json`, after a bulk frontmatter or stage change, or when files were written via Bash and bypassed the hooks (`reconcile-dirty`). Also invoked non-interactively by the plugin's PostToolUse hook and the `lazy-obsidian.repaint` daemon routine. Writes only `iconize_icon` / `iconize_color` frontmatter — never Iconize's `data.json`."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Write, Agent
argument-hint: "<subcommand> [args] | sync <path> | reconcile [--prefix PATH] | reconcile-plugin <plugin> | reconcile-dirty | check-versions"
execution-discipline-waiver: "thin dispatcher to iconize_sync.py — discipline belongs in the Python worker, not the SKILL.md"
---
# Iconize Sync (Obsidian)

Drives icon resolution for Obsidian vaults that follow a frontmatter-based semantics (role/stage/status/etc.). The worker reads `.claude/iconize/obsidian-icon-map.json` — a local, consumer-owned file that holds the vault's registries and declarative matchers — and writes `iconize_icon` / `iconize_color` keys into each matched note's YAML frontmatter. It never edits Iconize's `data.json`.

Two consumers turn that frontmatter into icons on screen:

- **Iconize plugin** (with `iconInFrontmatterEnabled: true`) reads `iconize_icon` live from any `.md` file's frontmatter and paints the file's tab + title.
- **Iconize Reloader plugin** (bundled by `lazy-obsidian.iconize-install`) watches folder-note frontmatter and bridges it into folder-keyed entries in `.obsidian/plugins/obsidian-icon-folder/data.json`, which Iconize then paints on the folder row in the file-explorer. The reloader is the **sole writer** of `data.json`.

## Prerequisite

Run `lazy-obsidian.iconize-install` first to scaffold the protocol doc, icon-map, and hooks into your vault.

## Subcommands

All subcommands accept `--vault <root>`, `--dry-run`, and `--icon-map <path>` as global flags BEFORE the subcommand.

### `sync <vault-relative-path>`

Resolve one file. Reads its frontmatter, matches against the icon-map, then upserts or clears `iconize_icon` / `iconize_color` in that file's frontmatter.

Invoked by: the PostToolUse hook, or manually.

### `reconcile [--prefix <path>]`

Walk every `.md` file (under `--prefix` if given, else whole vault), compute the desired `iconize_*` frontmatter, and rewrite each file. Files that no longer match a rule have their `iconize_icon` / `iconize_color` keys cleared. Use after bulk frontmatter changes or icon-map edits.

### `reconcile-plugin <plugin>`

Plugin-scoped reconcile. Walks `claude/<plugin>/**/*.md` only, re-resolves icons, rewrites frontmatter where the resolution differs, and reports every rewritten path in its `touched` array. It does not stage: the caller folds `touched` into its own commit pathspec, which is what carries the repaint into the commit.

Use case: invoked by the pre-commit pipeline after bumping `claude/<plugin>/.claude-plugin/plugin.json`. The version delta flips callbacks like `plugin-is-patch-bumped`, so every file under the plugin's subtree whose color depends on those callbacks (folder note, README) repaints in the same commit. The full `reconcile` walk would do the same at vault scope; this one is bounded.

### `reconcile-dirty`

Safety-net for edits that bypass the PostToolUse `Write|Edit` hook (anything written via `Bash`, a shell script, a bulk rename, etc.). Queries `git status` for dirty `.md` files — modified, added, deleted, untracked, and renamed — and reconciles the unique parent directories of those paths in one pass. Silent no-op on a clean tree or a non-git vault.

Invoked by: the operator, manually. No hook drives it — a reconcile over every dirty parent directory is too heavy to run on a tool or turn boundary.

### `check-versions`

Reports the icon-map schema handshake: checks the vault's `obsidian-icon-map.json` `schema_version` against the worker's `SUPPORTED_SCHEMA` set, and verifies `HOOK_VERSION` satisfies the icon-map's optional `min_hook_version`.

Exits 0 when the schema is compatible or merely "missing" (vault not opted in); exits 5 on an incompatible schema. Run after `/plugin update lazycortex-obsidian@lazycortex`.

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
| 5 | Version drift (incompatible icon-map schema) |

## Logging

Log every invocation to `./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Use two separate steps: `Bash(mkdir -p ...)` then `Write`.

## Non-goals

- Editing Iconize's `data.json` (that's the reloader plugin's job).
- Managing the Iconize `rules` array.
- Installing icon packs.
