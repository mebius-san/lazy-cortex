---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, pre-commit shim, and a `.gitignore` entry for Iconize's live `data.json` (it's rewritten on every icon click + by the iconize-sync worker, so it's runtime state, not source). Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans, strips legacy worker-written PostToolUse entries, migrates icon-map schema. Re-runnable; idempotent. Must be run from the consumer vault's git root. Installs all three iconize-sync hard-dependency plugins — `obsidian-icon-folder` (Iconize), `folder-notes`, and the bundled `iconize-reloader` — via the `/lazy-obsidian.update-plugin` primitive, which also deep-merges opinionated settings from `plugin-settings.json`. PostToolUse is plugin-shipped — no consumer settings.json mutation."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git ls-files*), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), Bash(rm *), Bash(jq *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList
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

## Execution discipline (MANDATORY — read before any action)

This skill has 14 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate repo root and vault`
   - `Step 1.5a — Install/update folder-notes`
   - `Step 1.5b — Install/update obsidian-icon-folder`
   - `Step 1.5c — Install/update iconize-reloader (bundled)`
   - `Step 2 — Scaffold protocol doc`
   - `Step 2.5 — Strip legacy PostToolUse entries`
   - `Step 2.6 — Assert Iconize frontmatter-feature settings`
   - `Step 2.7 — Icon-map scaffold (schema-aware)`
   - `Step 3 — Install the pre-commit shim`
   - `Step 4 — Create callbacks dir`
   - `Step 4.5 — Ensure iconize data.json is gitignored`
   - `Step 5 — Verify`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

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

## Step 1.5 — Install/update hard-dependency plugins

Three MANDATORY hard deps. No prompt, no skip. The user opted into
iconize-install — iconize-sync is non-functional without all three, so
asking "install folder-notes?" here would be pointless ceremony and
(worse) invites the agent to silently treat "skip" as a valid outcome.

`update-plugin` is version-aware and idempotent — always invoke it; never
short-circuit because a manifest probe looked green. "Manifest present"
does NOT mean "already current" — that's `update-plugin`'s job.

| id | flag |
|---|---|
| `folder-notes` | — |
| `obsidian-icon-folder` | — |
| `iconize-reloader` | `--bundled` |

For each row, in order (each is its own TaskCreate task — 1.5a / 1.5b / 1.5c):

1. Invoke `/lazy-obsidian.update-plugin <id> [<flag>]`.
2. Record the state tuple (`binary=... overrides=... community=...`) for
   the Step 6 report.
3. If `update-plugin` returns **FAIL** → **ABORT the entire skill** with a
   clear error: "Hard dependency `<id>` could not be installed/updated
   (`<reason>`). iconize-sync requires all three. Resolve and re-run." Do
   not continue to subsequent rows or steps. No silent `skipped`, no
   continue-anyway. A failed hard dep is a failed install.

## Step 2 — Scaffold protocol doc (per-file prompt)

State machine (one `AskUserQuestion` per file):

- **New** (target missing) → install / skip.
- **Unchanged** (byte-identical) → no prompt.
- **Drift** (differ) → show unified diff, ask: **overwrite** / **keep-local**.

**Scope**: protocol doc only. The icon-map is handled in Step 2.7 (its drift
decision is schema-aware, so a generic byte-diff prompt would hide the
migration option).

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

## Step 2.7 — Icon-map scaffold (schema-aware)

The icon-map uses a bilateral version handshake (`schema_version` + optional
`min_hook_version`). The worker's preflight renders hooks inert (exit 0, stderr
diagnostic) on mismatch — so a stale schema silently disables syncing.

This step is the **single decision point for the icon-map** — byte-drift and
schema migration are handled together so the user sees one coherent prompt,
not two sequential ones where `migrate` (the in-place upgrade that preserves
authored registries and matchers) is easy to miss behind an overwrite /
keep-local drift prompt.

Retrieve `SCHEMA_VERSION`, `SUPPORTED_SCHEMA`, and `HOOK_VERSION` from the
worker: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py check-versions`.

### Decision matrix

Read `.claude/obsidian-iconize/icon-map.json` and dispatch:

1. **Target missing** → install the plugin's template at
   `${CLAUDE_PLUGIN_ROOT}/templates/obsidian-iconize/icon-map.json`. No prompt
   (mirrors Step 2's "New" branch for the protocol doc). State: **installed**.
2. **Target present, `schema_version == SCHEMA_VERSION`** (handshake OK):
   - Byte-identical to template → no prompt. State: **unchanged**.
   - Byte-differs (authored customizations on the current schema) → show
     unified diff, `AskUserQuestion`: **overwrite** / **keep-local**.
3. **Target present, `schema_version == 1` (or absent, treated as implicit v1)
   and `SCHEMA_VERSION == 2`** → v1-to-v2 migration is available. Preview:
   count matchers that contain an `emit` key and list the first ~5 matcher ids
   that would have `emit` stripped. Then issue a **single** `AskUserQuestion`
   with three options:
   - **migrate** — in-place upgrade. Drop every `emit` key from every matcher,
     set `schema_version: 2`, preserve all other keys (registries,
     stage_colors, version, matchers' other fields, key order). Implementation:
     `jq '.schema_version = 2 | .matchers = (.matchers | map(del(.emit)))'`
     with an atomic write (`icon-map.json.tmp` → `mv`). State: **v1-to-v2-upgraded**.
   - **overwrite** — replace with the plugin's empty v2 template. The prompt
     description MUST spell out that this wipes all authored registries,
     matchers, and stage-colors. State: **overwritten**.
   - **keep-local** — leave the v1 file untouched. Hooks remain inert (exit 0
     with stderr diagnostic) until the user migrates. State: **v1-kept**,
     surface as a FAIL in the Step 6 report.
4. **Target present, `schema_version` outside `SUPPORTED_SCHEMA` on the high
   side** (future version the installed worker doesn't know) → **plugin too
   old** blocker. Report and do not edit. State: **blocker-plugin-too-old**.
5. **Target present, `schema_version == 2` but `min_hook_version` exceeds the
   installed `HOOK_VERSION`** → same **plugin too old** blocker.

### Wizard discipline

Cases 2-drift and 3 each use **one** `AskUserQuestion`. Never ask a generic
drift prompt (overwrite / keep-local) and then a second schema prompt
(upgrade / keep) — when the drift is explained by a schema version bump,
`migrate` must appear as a first-class option inside the same prompt as
`overwrite` and `keep-local`, so the user doesn't have to pick `keep-local`
just to unlock the migration path.

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

One bullet per step, in order — missing bullet = skipped step, back up and run it.

- **Step 1** — repo-root + vault paths (or abort reason).
- **Step 1.5a** `folder-notes`: state tuple (`binary=created|updated-<x>-to-<y>|unchanged overrides=... community=...`). Never `skipped` — hard deps abort the skill instead.
- **Step 1.5b** `obsidian-icon-folder`: state tuple. Never `skipped`.
- **Step 1.5c** `iconize-reloader`: state tuple. Never `skipped`.
- **Step 2** protocol doc: **installed** / **unchanged** / **overwritten** / **kept-local**.
- **Step 2.5** legacy PostToolUse: **stripped** (count) / **kept** / **not-present**.
- **Step 2.6** Iconize frontmatter settings: **asserted** / **fixed** / **kept-local** / **skipped** / **iconize-absent**.
- **Step 2.7** icon-map: **installed** / **unchanged** / **overwritten** / **kept-local** / **v1-to-v2-upgraded** / **v1-kept** / **blocker-plugin-too-old**.
- **Step 3** pre-commit shim: HOOK_VERSION + `core.hooksPath` (**set** / **already-set** / **left-as-is**).
- **Step 4** callbacks dir: **created** / **already-present** / **.gitkeep-added**.
- **Step 4.5** `.gitignore` (iconize data.json): **added** / **already-ignored** / **gitignore-created** / **skipped**; WARN if `git ls-files --error-unmatch` exits 0 (user runs `git rm --cached`, never auto).
- **Step 5** verify: `check-versions` status + `reconcile --dry-run` summary.

Next steps: "run `lazy-obsidian.iconize-config` to seed registries, then `lazy-obsidian.iconize-sync reconcile`." Add consequence lines for any **kept-local** / **skipped** assertion (2.6, 2.7, 4.5 only — hard-dep skips don't reach Step 6).

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
prompt. Legacy-stripping gets its own prompt. The icon-map gets **one**
schema-aware prompt (Step 2.7) whose options depend on the drift/schema case —
so a v1-vs-v2 situation offers `migrate` alongside `overwrite` and
`keep-local`, not a sequential drift-then-migration pair where `migrate` is
hidden behind a prior choice.
