---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, and pre-commit shim. Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans, strips legacy worker-written PostToolUse entries, migrates icon-map schema. Re-runnable; idempotent. Must be run from the consumer vault's git root. PostToolUse is plugin-shipped — no consumer settings.json mutation."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), Bash(rm *), AskUserQuestion
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

## Architecture note (why this skill is smaller than before)

The PostToolUse hook is now **plugin-shipped**: it lives in
`${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json` and is auto-loaded by Claude Code when
the plugin is enabled. This skill no longer mutates the consumer's
`.claude/settings.json`. The hook self-gates on presence of
`.claude/obsidian-iconize/icon-map.json` — so enabling the plugin in a vault
that hasn't opted in is a no-op.

The pre-commit shim **still lives in the consumer's `.githooks/`** — git has
no plugin awareness. The shim resolves the plugin at exec time (no baked path).

## Artifacts scaffolded

| Artifact | Target path | Source |
|---|---|---|
| Protocol doc | `.claude/protocol/obsidian.iconize.md` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/protocol.md` |
| Icon-map | `.claude/obsidian-iconize/icon-map.json` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/icon-map.json` |
| Pre-commit shim | `.githooks/pre-commit` | Rendered from `pre-commit-shim.sh` via the worker's `install-hooks` |
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

## Step 2.5 — Strip legacy PostToolUse entries (one-shot migration)

Plugin versions ≤ 0.1.23 wrote a `PostToolUse` entry into the consumer's
`.claude/settings.json` with a hardcoded absolute plugin path. That entry is
now obsolete (the hook is plugin-shipped) and stale (path pinned to an old
plugin version).

1. Read `.claude/settings.json`. If missing or not an object → skip this step.
2. Walk `settings.hooks.PostToolUse` (if present). Any group whose
   `hooks[].command` contains the string `iconize_sync.py` is a legacy entry.
3. For each legacy group found, `AskUserQuestion` (one question per group):
   - **strip** — remove the group and rewrite `settings.json`. Preserve other
     unrelated PostToolUse groups untouched.
   - **keep** — leave as-is (user accepts the stale hook; diagnostic only).
4. If all legacy groups are stripped and the `PostToolUse` list becomes empty,
   remove the key entirely; if `hooks` becomes empty, remove it too.
5. Never auto-strip without confirmation — wizard discipline.

## Step 2.7 — Schema handshake migration

Icon-map uses a bilateral version handshake (`schema_version` + optional
`min_hook_version`). The worker's preflight renders hooks inert (exit 0, stderr
diagnostic) on mismatch — so a stale schema silently disables syncing.

1. Read the vault's `.claude/obsidian-iconize/icon-map.json` (if present).
2. If the top-level `schema_version` key is absent → this is a pre-handshake
   vault (schema 1 implicit). `AskUserQuestion`: **add** (write
   `schema_version: 1` to make the handshake explicit) / **keep** (back-compat
   continues to work but `check-versions` can't verify).
3. If `schema_version` is present and outside the worker's `SUPPORTED_SCHEMA`
   set → incompatible. Show the mismatch and `AskUserQuestion`:
   **upgrade** (rewrite to current `SCHEMA_VERSION`) / **keep** (hooks remain
   inert until resolved).
4. If `schema_version` is in range but the icon-map's `min_hook_version`
   exceeds the installed `HOOK_VERSION` → the plugin is too old. Surface this
   as an installation blocker; instruct the user to upgrade the plugin. Do
   not edit the icon-map.

Retrieve `SCHEMA_VERSION`, `SUPPORTED_SCHEMA`, and `HOOK_VERSION` from the
worker: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py check-versions`
emits them in the report.

## Step 3 — Install the pre-commit shim

Invoke the plugin worker's `install-hooks` subcommand. This writes the
pre-commit shim to `.githooks/pre-commit`. No consumer `settings.json`
mutation happens here (the PostToolUse hook is plugin-shipped; see
architecture note above).

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

Run the worker's `check-versions`. Expect exit 0. Report shape includes:

- `pre_commit.status` — `ok` / `missing` / `major-drift` / `minor-drift`.
- `icon_map_schema.status` — `ok` / `incompatible` / `missing`.
- `icon_map_schema.declared`, `icon_map_schema.min_hook_version` — echo.

Any non-`ok` status surfaces as a drift finding; re-run the relevant step to
resolve.

Then run `reconcile --dry-run` and print the plan so the user can see what a
full sweep would do. Do not apply.

## Step 6 — Report

Summarize:
- Which artifacts were **created**, **updated**, **unchanged**, or **kept-local**.
- Whether a legacy PostToolUse entry was **stripped**, **kept**, or **not present**.
- Schema migration result: **added** / **upgraded** / **none needed** / **blocker**.
- Shim HOOK_VERSION installed.
- Next steps: "run `lazy-obsidian.iconize-configure` to seed your registries,
  then run `lazy-obsidian.iconize-sync reconcile` for a first full sweep."

## Step 7 — Log the run

Log to `./.logs/claude/lazy-obsidian.iconize-install/YYYY-MM-DD_HH-MM-SS.md`
per the logging rule. Two-step write: `Bash(mkdir -p ...)` then `Write`.

## Idempotency

Safe to re-run. Drift prompts only fire when content actually differs.
Orphan detection: if `.claude/protocol/obsidian.iconize.md` exists but the
plugin no longer ships `protocol.md`, offer deletion. Same for
`icon-map.json`. Legacy PostToolUse detection (Step 2.5) is also idempotent —
after the first re-run strips them, subsequent runs find nothing to strip.

## Wizard discipline

Every decision point uses `AskUserQuestion`, one question at a time. Never
bundle "install protocol? install icon-map?" into a single multi-select
prompt. Legacy-stripping and schema-migration each get their own prompt.
