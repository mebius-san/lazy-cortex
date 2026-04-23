---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, pre-commit shim, and a `.gitignore` entry for Iconize's live `data.json` (it's rewritten on every icon click + by the iconize-sync worker, so it's runtime state, not source). Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans, strips legacy worker-written PostToolUse entries, migrates icon-map schema. Re-runnable; idempotent. Must be run from the consumer vault's git root. Installs all three iconize-sync hard-dependency plugins — `obsidian-icon-folder` (Iconize), `folder-notes`, and the bundled `iconize-reloader` — via the `/lazy-obsidian.update-plugin` primitive, which also deep-merges opinionated settings from `plugin-settings.json`. PostToolUse is plugin-shipped — no consumer settings.json mutation."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git ls-files*), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), Bash(rm *), Bash(jq *), AskUserQuestion
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

## Step 1.5 — Install hard-dependency vault plugins

Iconize-sync has three hard dependencies on Obsidian community plugins. All
three are installed / updated via `/lazy-obsidian.update-plugin`, which:

- fetches the latest release from GitHub (or copies from the bundled source
  for `iconize-reloader`);
- deep-merges the opinionated override block from
  `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/plugin-settings.json` onto the
  vault's `plugins/<id>/data.json` (this is how Iconize gets configured to
  read `iconize_icon` / `iconize_color` from frontmatter and Folder Notes
  gets its `folderNoteName: "{{folder_name}}"` template);
- registers `<id>` in `<vault>/community-plugins.json`.

`update-plugin` is version-aware and idempotent — on re-runs it no-ops when
the vault is already current and re-enforces overrides.

### 1.5a — Folder Notes

Iconize-sync's folder-icon model reads folder-note frontmatter
(`<folder>/<folderNoteName>.md`, per Folder Notes plugin's `folderNoteName`
template — the opinionated override sets this to `{{folder_name}}`).
Without Folder Notes, the reloader can't map folders → folder-notes and
folder icons will never paint.

1. Probe `<vault>/plugins/folder-notes/manifest.json`. If present → invoke
   `/lazy-obsidian.update-plugin folder-notes` directly (it will no-op when
   current, update when the remote is newer).
2. If absent → `AskUserQuestion`: **install** / **skip**.
   - **install** → invoke `/lazy-obsidian.update-plugin folder-notes`.
     Record its reported state tuple in this skill's final report.
   - **skip** → note in the final report that folder icons will not paint
     until Folder Notes is installed. Continue with Step 1.5b.

### 1.5b — Iconize (`obsidian-icon-folder`)

Iconize itself is the target the worker writes to. Without it, there is no
`data.json` to reconcile and the frontmatter-icon feature has no renderer.
The opinionated override configures Iconize to read from `iconize_icon` /
`iconize_color` (see Step 2.6 for the audit assertion).

1. Probe `<vault>/plugins/obsidian-icon-folder/manifest.json`. If present →
   invoke `/lazy-obsidian.update-plugin obsidian-icon-folder` directly.
2. If absent → `AskUserQuestion`: **install** / **skip**.
   - **install** → invoke `/lazy-obsidian.update-plugin obsidian-icon-folder`.
     Record its reported state tuple.
   - **skip** → note in the final report that iconize-sync cannot function
     until Iconize is installed. Continue with Step 1.5c.

### 1.5c — iconize-reloader (bundled)

`iconize-reloader` is the runtime half of the iconize-sync two-writer model:
it watches folder-note frontmatter events (write / rename / delete) and
propagates changes into `data.json`, including **purging folder-keyed
entries whose folder-note no longer exists**. Without it, the worker writes
frontmatter but nothing closes the loop back to `data.json` — stale folder
icons persist and orphans never get purged.

Unlike the other two, `iconize-reloader` is iconize-sync-specific — it has
no standalone value, isn't in the Obsidian community registry, and ships
bundled inside this plugin at
`${CLAUDE_PLUGIN_ROOT}/templates/obsidian/plugins/iconize-reloader/`.

1. Probe `<vault>/plugins/iconize-reloader/manifest.json`. If present →
   invoke `/lazy-obsidian.update-plugin iconize-reloader --bundled`
   (copies from the bundled source if the version differs).
2. If absent → `AskUserQuestion`: **install** / **skip**.
   - **install** → invoke `/lazy-obsidian.update-plugin iconize-reloader --bundled`.
     Record its reported state tuple.
   - **skip** → note in the final report that folder-icon sync and orphan
     purging will not function until the reloader is installed.

### Step 1.5 report

Capture each invocation's state tuple (`binary=... overrides=... community=...`)
and surface all three in the final Step 6 report. If any of the three was
skipped, flag the consequence in the report's "next steps" block.

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

## Step 2.6 — Assert Iconize frontmatter-feature settings

The worker writes icon/color into frontmatter under `iconize_icon` and
`iconize_color`. Iconize must be configured to paint from those exact keys.

**Required settings** (in `<vault>/plugins/obsidian-icon-folder/data.json`
under the `settings` object):

| Key | Required value |
|---|---|
| `iconInFrontmatterEnabled` | `true` |
| `iconInFrontmatterFieldName` | `"iconize_icon"` |
| `iconColorInFrontmatterFieldName` | `"iconize_color"` |

Procedure:

1. Read `<vault>/plugins/obsidian-icon-folder/data.json`. If missing →
   WARN: "Iconize is not installed or hasn't been launched once.
   Re-run `/lazy-obsidian.update-plugin obsidian-icon-folder` or open
   Obsidian once to let it initialize its `data.json`, then re-run this
   skill." Skip this step (return to Step 2.7).
2. Extract `settings.iconInFrontmatterEnabled`,
   `settings.iconInFrontmatterFieldName`,
   `settings.iconColorInFrontmatterFieldName`.
3. For each key whose value differs from the required value, add to a
   **drift** list. Show the drift list to the user.
4. If drift is non-empty, `AskUserQuestion`: **fix** / **keep-local** /
   **skip**.
   - **fix** — rewrite the three keys to the required values. Preserve all
     other `settings` keys and all other top-level keys (`rules`,
     `recentlyUsedIcons`, path-keyed entries). Atomic write
     (`data.json.tmp` → `mv`).
   - **keep-local** — record in the report that frontmatter-driven icons
     will not paint until the user adjusts Iconize settings manually.
   - **skip** — no write.
5. Report state: **asserted** / **fixed** / **kept-local** / **skipped** /
   **iconize-absent**.

Wizard discipline: one `AskUserQuestion` for the whole drift block (not one
per key) — the three settings are conceptually a single "frontmatter feature"
toggle and make no sense partial.

## Step 2.7 — Schema handshake migration

Icon-map uses a bilateral version handshake (`schema_version` + optional
`min_hook_version`). The worker's preflight renders hooks inert (exit 0, stderr
diagnostic) on mismatch — so a stale schema silently disables syncing.

1. Read the vault's `.claude/obsidian-iconize/icon-map.json` (if present).
2. If the top-level `schema_version` key is absent → this is a pre-handshake
   vault (schema 1 implicit). Treat as schema 1 and proceed to the v1 → v2
   branch below.
3. If `schema_version == SCHEMA_VERSION` (current — 2 at time of this plan)
   → **ok**, no migration.
4. If `schema_version == 1` and `SCHEMA_VERSION == 2` → **v1-to-v2 migration
   available**. Diff preview: count matchers that contain an `emit` key;
   show the count and the first ~5 matcher ids that would have `emit`
   stripped. `AskUserQuestion`: **upgrade** / **keep**.
   - **upgrade**: drop every `emit` key from every matcher, set
     `schema_version: 2`, write back. Preserve all other keys (registries,
     stage_colors, version, matchers' other fields, key order).
   - **keep**: hooks remain inert until resolved; surface a FAIL in the
     report.
5. If `schema_version` is outside `SUPPORTED_SCHEMA` in the other direction
   (future version the installed worker doesn't know) → **plugin too old**.
   Report as a blocker; do not edit the icon-map.
6. If `schema_version == 2` but `min_hook_version` exceeds the installed
   `HOOK_VERSION` → same "plugin too old" blocker.

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

## Step 4.5 — Ensure iconize `data.json` is gitignored

Iconize (`obsidian-icon-folder`) stores the vault's full icon-mapping
database (path → icon, plus `settings` / `rules` / `recentlyUsedIcons`) in
`.obsidian/plugins/obsidian-icon-folder/data.json`. The file is rewritten
on every icon click and by the iconize-sync worker from frontmatter + git
hooks — so it's runtime state, not source. Tracking it produces merge
conflicts on every branch switch and noisy diffs on every commit.

Because this step runs only inside `iconize-install`, the opt-in is
implicit: the user is scaffolding iconize-sync, so they clearly intend to
use it.

1. `entry = ".obsidian/plugins/obsidian-icon-folder/data.json"` (repo-root
   relative — the path iconize writes regardless of vault subdir, because
   the vault is `.obsidian/` under the repo root per Step 1).
2. Target: `<repo-root>/.gitignore`. If it doesn't exist, `AskUserQuestion`:
   **create** (seed a new `.gitignore` containing just this entry) /
   **skip** (respect repos that intentionally have no `.gitignore`). One
   prompt, then honor the choice on re-runs via idempotency below.
3. Read the file (or start from empty if just created). If any non-comment
   line equals `entry` → state: **already-ignored**, no write.
4. Otherwise, append `entry` on its own line (prepend `\n` if the file
   doesn't end in one). State: **added**.
5. Check whether the file is currently tracked: `git ls-files --error-unmatch <entry>`.
   Exit 0 → emit a one-line WARN in the report reminding the user to run
   `git rm --cached <entry>` to stop tracking it. Never auto-`git rm` —
   that's a history-touching action, user's call.

Idempotent: re-running reports **already-ignored** every time after the
first write.

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
- Hard-dependency plugins — one line per plugin with the `update-plugin`
  state tuple (or **skipped** if the user opted out):
  - `folder-notes`: `binary=... overrides=... community=...` / **skipped**
  - `obsidian-icon-folder`: `binary=... overrides=... community=...` / **skipped**
  - `iconize-reloader`: `binary=... overrides=... community=...` / **skipped**
- Whether a legacy PostToolUse entry was **stripped**, **kept**, or **not present**.
- Iconize frontmatter settings: **asserted** / **fixed** / **kept-local** / **skipped** / **iconize-absent**.
- Schema migration result: **none-needed** / **v1-to-v2-upgraded** / **v1-kept** / **blocker-plugin-too-old**.
- Shim HOOK_VERSION installed.
- `.gitignore` (iconize data.json): **added** / **already-ignored** / **gitignore-created** / **skipped** — plus WARN line if the file is currently tracked.
- Next steps: "run `lazy-obsidian.iconize-config` to seed your registries,
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
