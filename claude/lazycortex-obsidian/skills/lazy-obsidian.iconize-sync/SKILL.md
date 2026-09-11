---
name: lazy-obsidian.iconize-sync
description: "Use when a note's or folder's icon is stale and must be re-resolved from the icon-map — after editing `.claude/iconize/obsidian-icon-map.json`, after a bulk frontmatter or stage change, or when files were written via Bash and bypassed the hooks (`reconcile-dirty`). Also invoked non-interactively by the plugin's PostToolUse hook and the `lazy-obsidian.repaint` daemon routine. Writes only `iconize_icon` / `iconize_color` frontmatter — never Iconize's `data.json`."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Write, Agent
argument-hint: "<subcommand> [args] | sync <path> | sync-paths <path>... | reconcile [--prefix PATH] | reconcile-plugin <plugin> | reconcile-dirty | reconcile-commit [<sha>] | check-versions"
execution-discipline-waiver: "thin dispatcher to iconize_sync.py — discipline belongs in the Python worker, not the SKILL.md"
---
# Iconize Sync (Obsidian)

Drives icon resolution for Obsidian vaults that follow a frontmatter-based semantics (role/stage/status/etc.). The worker reads `.claude/iconize/obsidian-icon-map.json` — a local, consumer-owned file that holds the vault's registries and declarative matchers — and writes `iconize_icon` / `iconize_color` keys into each matched note's YAML frontmatter. It never edits Iconize's `data.json`.

Two consumers turn that frontmatter into icons on screen:

- **Iconize plugin** (with `iconInFrontmatterEnabled: true`) reads `iconize_icon` live from any `.md` file's frontmatter and paints the file's tab + title.
- **Iconize Reloader plugin** (bundled by `lazy-obsidian.iconize-install`) watches folder-note frontmatter and bridges it into folder-keyed entries in `.obsidian/plugins/obsidian-icon-folder/data.json`, which Iconize then paints on the folder row in the file-explorer. The reloader is the **only automated writer** of `data.json`; Iconize itself is the other, writing file-keyed entries when the user picks an icon from its right-click menu and rewriting its own reserved blocks on UI interaction. The worker writes it never.

## Prerequisite

Run `lazy-obsidian.iconize-install` first: it scaffolds the icon-map and the callbacks dir into your vault, installs the three hard-dependency vault plugins, and registers the repaint routine. The protocol doc is not scaffolded — its single canonical home is `${CLAUDE_PLUGIN_ROOT}/references/lazy-obsidian.iconize-protocol.md` — and the PostToolUse hook ships with the plugin itself rather than being installed into the vault.

## Subcommands

All subcommands accept `--vault <root>`, `--dry-run`, and `--icon-map <path>` as global flags BEFORE the subcommand.

### `sync <vault-relative-path>`

Resolve one file. Reads its frontmatter, matches against the icon-map, then upserts `iconize_icon` / `iconize_color` in that file's frontmatter where the resolution differs. A note no matcher claims keeps whatever icon keys it already carries — no subcommand ever strips them, so another manager's keys survive a run.

Invoked by: the PostToolUse hook, or manually.

### `sync-paths <vault-relative-path>...`

Resolve the named `.md` paths in one pass and report every rewritten file in a `touched` array. The single-commit door for a sibling plugin's bot routine: run it on the paths the routine is about to commit and fold `touched` into that commit's own pathspec, so the repaint rides inside the same commit instead of arriving as a separate icons commit later. Rewrites the working tree only — it never stages and never commits. A named path that is not markdown, does not exist, or that no matcher claims is skipped.

Invoked by: a sibling plugin's committing primitive, which subprocesses the worker directly — the review plugin's `commit-doc` and the specs coordinator's pen commits both fold the returned `touched` paths into their own pathspec.

### `reconcile [--prefix <path>]`

Walk every `.md` file (under `--prefix` if given, else whole vault), compute the desired `iconize_*` frontmatter, and rewrite each file whose resolution differs. A file no rule claims is left exactly as it stands, icon keys included. Use after bulk frontmatter changes or icon-map edits.

### `reconcile-plugin <plugin>`

Plugin-scoped reconcile. Walks `claude/<plugin>/**/*.md` only, re-resolves icons, rewrites frontmatter where the resolution differs, and reports every rewritten path in its `touched` array. It does not stage: the caller folds `touched` into its own commit pathspec, which is what carries the repaint into the commit.

Use case: invoked by the pre-commit pipeline after bumping `claude/<plugin>/.claude-plugin/plugin.json`. The version delta flips callbacks like `plugin-is-patch-bumped`, so every file under the plugin's subtree whose color depends on those callbacks (folder note, README) repaints in the same commit. The full `reconcile` walk would do the same at vault scope; this one is bounded.

### `reconcile-dirty`

Safety-net for edits that bypass the PostToolUse `Write|Edit` hook (anything written via `Bash`, a shell script, a bulk rename, etc.). Queries `git status` for dirty `.md` files — modified, added, deleted, untracked, and renamed — and reconciles the unique parent directories of those paths in one pass. Silent no-op on a clean tree or a non-git vault.

Invoked by: the operator, manually. No hook drives it — a reconcile over every dirty parent directory is too heavy to run on a tool or turn boundary.

### `reconcile-commit [<sha> | <git-watch item JSON>]`

Repaint every directory one commit touched, then commit the notes whose icons drifted. The unit of work is the whole directory rather than the changed file, because a note's color can depend on its siblings and the triggering commit need not touch a markdown file at all. Only a note whose entire diff against HEAD — staged and unstaged — is confined to its own `iconize_icon` / `iconize_color` lines joins the commit; a note whose divergence reaches any other line, and a note git does not yet track, is left uncommitted and untouched, so an operator gesture or another writer's payload never rides a bot commit. Exits 6 when the repaint commit does not land.

Invoked by: the `lazy-obsidian.repaint` daemon routine, which passes the git-watch item.

### `check-versions`

Reports the icon-map schema handshake: checks the vault's `obsidian-icon-map.json` `schema_version` against the worker's `SUPPORTED_SCHEMA` set, and verifies `HOOK_VERSION` satisfies the icon-map's optional `min_hook_version`.

Exits 0 when the schema is compatible or merely "missing" (vault not opted in); exits 5 on an incompatible schema. Run after `/plugin update lazycortex-obsidian@lazycortex`.

## How to run

The worker lives at `${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py`. Invoke via:

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py" <subcommand> [flags] [args]
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation error (no or unknown subcommand, bad args, invalid `--validate-entry` payload) |
| 5 | Version drift (incompatible icon-map schema — `check-versions`) |
| 6 | Repaint commit did not land (`reconcile-commit`) |

Nothing else is an error. A target path that does not exist, and an icon-map that is missing, unreadable, or malformed, both leave the run inert at exit 0 — icons are cosmetic and a hook must never block a commit over one; the reason goes to stderr.

## Logging

Log every invocation to `./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Use two separate steps: `Bash(mkdir -p ...)` then `Write`.

## Non-goals

- Editing Iconize's `data.json` (that's the reloader plugin's job).
- Managing the Iconize `rules` array.
- Installing icon packs.
