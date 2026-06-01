---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, pre-commit shim, and a `.gitignore` entry for Iconize's live `data.json` (it's rewritten on every icon click and by the bundled iconize-reloader plugin — runtime state, not source). Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans, strips legacy worker-written PostToolUse entries, migrates icon-map schema. Re-runnable; idempotent. Must be run from the consumer vault's git root. Installs all three iconize-sync hard-dependency plugins — `obsidian-icon-folder` (Iconize), `folder-notes`, and the bundled `iconize-reloader` — via the `/lazy-obsidian.update-plugin` primitive, which also deep-merges opinionated settings from `plugin-settings.json`. PostToolUse is plugin-shipped — no consumer settings.json mutation."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git ls-files*), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), Bash(rm *), Bash(jq *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList
argument-hint: "[--dry-run] — scaffolds into <repo-root>/.claude/ and <repo-root>/.githooks/"
---
# Install iconize-sync (Obsidian)

Scaffolds the iconize-sync system into the **current git repo** so the plugin's `lazy-obsidian.iconize-sync` skill can start painting icons from frontmatter. The repo must contain an Obsidian vault (a `.obsidian/` directory somewhere — typically at repo root).

## Scope

Project-local only. There is no global scope — iconize-sync is inherently per-vault.

## Execution discipline (MANDATORY — read before any action)

This skill has 14 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate repo root and vault`
   - `Step 1.5a — Install/update folder-notes`
   - `Step 1.5b — Install/update obsidian-icon-folder`
   - `Step 1.5c — Install/update iconize-reloader (bundled)`
   - `Step 2 — Migrate legacy protocol doc`
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

The PostToolUse hook is now **plugin-shipped**: it lives in `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json` and is auto-loaded by Claude Code when the plugin is enabled. This skill no longer mutates the consumer's `.claude/settings.json`. The hook self-gates on presence of `.claude/iconize/obsidian-icon-map.json` — so enabling the plugin in a vault that hasn't opted in is a no-op.

The pre-commit shim **still lives in the consumer's `.githooks/`** — git has no plugin awareness. The shim resolves the plugin at exec time (no baked path).

## Artifacts scaffolded

| Artifact | Target path | Source |
|---|---|---|
| Icon-map | `.claude/iconize/obsidian-icon-map.json` | `${CLAUDE_PLUGIN_ROOT}/templates/iconize/obsidian-icon-map.json` |
| Pre-commit shim | `.githooks/pre-commit` | Rendered from `pre-commit-shim.sh` via the worker's `install-hooks` |
| Callback dir (empty) | `.claude/callbacks/` | Created empty; user drops executables here |

The plugin no longer scaffolds a vault-local protocol doc. The single canonical home is `${CLAUDE_PLUGIN_ROOT}/references/lazy-obsidian.iconize-protocol.md` (cited by the worker and by icon-map matchers). Step 2 below migrates legacy installs by deleting any pre-1.0.0 vault-local copy.

## Step 1 — Locate repo root and vault

- Repo root: `git rev-parse --show-toplevel`.
- Vault: walk from repo root looking for `.obsidian/`. If none found, abort with a message telling the user to initialize Obsidian first.

## Step 1.5 — Install/update hard-dependency plugins

Three MANDATORY hard deps. No prompt, no skip. The user opted into iconize-install — iconize-sync is non-functional without all three, so asking "install folder-notes?" here would be pointless ceremony and (worse) invites the agent to silently treat "skip" as a valid outcome.

`update-plugin` is version-aware and idempotent — always invoke it; never short-circuit because a manifest probe looked green. "Manifest present" does NOT mean "already current" — that's `update-plugin`'s job.

| id | flag |
|---|---|
| `folder-notes` | — |
| `obsidian-icon-folder` | — |
| `iconize-reloader` | `--bundled` |

For each row, in order (each is its own TaskCreate task — 1.5a / 1.5b / 1.5c):

1. Invoke `/lazy-obsidian.update-plugin <id> [<flag>]`.
2. Record the state tuple (`binary=... overrides=... community=...`) for the Step 6 report.
3. If `update-plugin` returns **FAIL** → **ABORT the entire skill** with a clear error: "Hard dependency `<id>` could not be installed/updated (`<reason>`). iconize-sync requires all three. Resolve and re-run." Do not continue to subsequent rows or steps. No silent `skipped`, no continue-anyway. A failed hard dep is a failed install.

## Step 2 — Migrate legacy protocol doc (one-shot)

Pre-1.0.0 versions of this skill scaffolded `.claude/protocols/obsidian.iconize.md` as a vault-local copy of the protocol mechanics. v1.0.0 retires that copy — the canonical home is the plugin's `references/lazy-obsidian.iconize-protocol.md`, reachable at `${CLAUDE_PLUGIN_ROOT}/references/lazy-obsidian.iconize-protocol.md` for any agent or human reader. Two identical copies were redundant in source, and the install copy added a drift surface that paid for nothing (the body had no per-vault customization seams).

State machine:

- **Target absent** (`.claude/protocols/obsidian.iconize.md` does not exist) → no prompt. Outcome: **not-present**.
- **Target present** → `AskUserQuestion`:
  - question: `Delete legacy iconize-sync protocol doc at .claude/protocols/obsidian.iconize.md?`
  - description: ``This file is a leftover from pre-1.0.0 installs. The protocol now lives only at `${CLAUDE_PLUGIN_ROOT}/references/lazy-obsidian.iconize-protocol.md` (referenced by the worker and by icon-map matchers). The vault-local copy was an exact duplicate; if you customized it, that text is preserved by **keep**.``
  - options: **delete** / **keep**.
  - On **delete**: remove the file, then `rmdir .claude/protocols` (best-effort — silent failure when the directory still has other unrelated entries). Outcome: **deleted**.
  - On **keep**: leave the file untouched. Outcome: **kept**.

## Step 2.5 — Strip legacy PostToolUse entries (one-shot migration)

Plugin versions ≤ 0.1.23 wrote a `PostToolUse` entry into the consumer's `.claude/settings.json` with a hardcoded absolute plugin path. That entry is now obsolete (the hook is plugin-shipped) and stale (path pinned to an old plugin version).

1. Read `.claude/settings.json`. If missing or not an object → skip this step.
2. Walk `settings.hooks.PostToolUse` (if present). Any group whose `hooks[].command` contains the string `iconize_sync.py` is a legacy entry.
3. For each legacy group found, `AskUserQuestion` (one question per group):
   - **strip** — remove the group and rewrite `settings.json`. Preserve other unrelated PostToolUse groups untouched.
   - **keep** — leave as-is (user accepts the stale hook; diagnostic only).
4. If all legacy groups are stripped and the `PostToolUse` list becomes empty, remove the key entirely; if `hooks` becomes empty, remove it too.
5. Never auto-strip without confirmation — wizard discipline.

## Step 2.6 — Assert Iconize frontmatter-feature settings

The worker writes icon/color into frontmatter under `iconize_icon` and `iconize_color`. Iconize must be configured to paint from those exact keys.

**Required settings** (in `<vault>/plugins/obsidian-icon-folder/data.json` under the `settings` object):

| Key | Required value |
|---|---|
| `iconInFrontmatterEnabled` | `true` |
| `iconInFrontmatterFieldName` | `"iconize_icon"` |
| `iconColorInFrontmatterFieldName` | `"iconize_color"` |

Procedure:

1. Read `<vault>/plugins/obsidian-icon-folder/data.json`. If missing → WARN: "Iconize is not installed or hasn't been launched once. Re-run `/lazy-obsidian.update-plugin obsidian-icon-folder` or open Obsidian once to let it initialize its `data.json`, then re-run this skill." Skip this step (return to Step 2.7).
2. Extract `settings.iconInFrontmatterEnabled`, `settings.iconInFrontmatterFieldName`, `settings.iconColorInFrontmatterFieldName`.
3. For each key whose value differs from the required value, add to a **drift** list. Show the drift list to the user.
4. If drift is non-empty, `AskUserQuestion`: **fix** / **keep-local** / **skip**.
   - **fix** — rewrite the three keys to the required values. Preserve all other `settings` keys and all other top-level keys (`rules`, `recentlyUsedIcons`, path-keyed entries). Atomic write (`data.json.tmp` → `mv`).
   - **keep-local** — record in the report that frontmatter-driven icons will not paint until the user adjusts Iconize settings manually.
   - **skip** — no write.
5. Report state: **asserted** / **fixed** / **kept-local** / **skipped** / **iconize-absent**.

Wizard discipline: one `AskUserQuestion` for the whole drift block (not one per key) — the three settings are conceptually a single "frontmatter feature" toggle and make no sense partial.

## Step 2.7 — Icon-map scaffold (schema-aware)

The icon-map uses a bilateral version handshake (`schema_version` + optional `min_hook_version`). The worker's preflight renders hooks inert (exit 0, stderr diagnostic) on mismatch — so a stale schema silently disables syncing.

This step is the **single decision point for the icon-map** — byte-drift and schema migration are handled together so the user sees one coherent prompt, not two sequential ones where `migrate` (the in-place upgrade that preserves authored registries and matchers) is easy to miss behind an overwrite / keep-local drift prompt.

Retrieve `SCHEMA_VERSION`, `SUPPORTED_SCHEMA`, and `HOOK_VERSION` from the worker: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py check-versions`.

### Decision matrix

**Pre-flight (case 0): legacy-path migration.** Pre-1.0.0 versions of this skill placed the icon-map at `.claude/obsidian-iconize/icon-map.json`. The 1.0.0 layout is `.claude/iconize/obsidian-icon-map.json` — `iconize/` as the resolver subsystem dir, file name carries the platform tag. If the legacy file exists, run a single `AskUserQuestion`:

- question: `Migrate icon-map from .claude/obsidian-iconize/icon-map.json to .claude/iconize/obsidian-icon-map.json?`
- description: ``v1.0.0 renamed the path. The v1.0.0 worker only reads the new path; leaving the file at the old path silently disables iconize-sync. **Migrate** does an atomic `mv` (no content change) and continues the rest of Step 2.7 against the moved file. **Keep-old** leaves the file in place; the install reports a FAIL for this step and the worker stays inert until the user fixes the path manually.``
- options: **migrate-path** *(Recommended)* / **keep-old**.
- On **migrate-path**: `mkdir -p .claude/iconize && mv .claude/obsidian-iconize/icon-map.json .claude/iconize/obsidian-icon-map.json && rmdir .claude/obsidian-iconize 2>/dev/null`. Outcome contributes `path-migrated` to the Step 6 report; then continue with cases 1–5 below against the new path (the file is now at the new path → cases 2-or-later apply, never case 1).
- On **keep-old**: do nothing. State: **legacy-path-kept** (FAIL).

Cases 1–5 below operate on `.claude/iconize/obsidian-icon-map.json`:

1. **Target missing** → install the plugin's template at `${CLAUDE_PLUGIN_ROOT}/templates/iconize/obsidian-icon-map.json`. No prompt (mirrors Step 2's "New" branch for the protocol doc). State: **installed**.
2. **Target present, `schema_version == SCHEMA_VERSION`** (handshake OK):
   - Byte-identical to template → no prompt. State: **unchanged**.
   - Byte-differs (authored customizations on the current schema) → show unified diff and issue a **single** `AskUserQuestion` with three options. `migrate` is first and labeled **(Recommended)** — it preserves authored work and is the right answer for almost every consumer. Plain overwrite/keep-local without a smart-merge option strands users with hand-authored registries between two bad choices.
     - **migrate** *(Recommended)* — three-way merge. For every top-level key
       and nested entry (registries' inner maps, `matchers[]` keyed by `id`,
       `stage_colors`):
       - Keys present only in shipped template → **add** to authored file.
       - Keys present only in authored file → **keep** verbatim.
       - Keys present in both with byte-equal values → no-op.
       - Keys present in both with **different** values → emit one
         `AskUserQuestion` per conflict (key path + both values shown):
         **keep-authored** / **take-shipped**. No bulk "resolve all"
         shortcut — each conflict is a separate decision.
       Atomic write (`icon-map.json.tmp` → `mv`). State: **merged**
       (annotate count of additions, conflicts-kept-authored,
       conflicts-took-shipped).
     - **overwrite** — replace with shipped template. Description MUST spell
       out that this wipes all authored registries/matchers/stage-colors.
       State: **overwritten**.
     - **keep-local** — leave authored file untouched; new shipped entries
       won't reach this vault until next install. State: **kept-local**.
3. **Target present, `schema_version` (call it `N`) `< SCHEMA_VERSION` and a migration chain `N → N+1 → … → SCHEMA_VERSION` is fully covered by the transforms table below.** A missing `schema_version` is treated as `N=1` (pre-handshake back-compat). Render a per-step preview (one bullet per chain step describing what that step changes — see transforms table) and issue a **single** `AskUserQuestion` with three options. `migrate` is first and labeled **(Recommended)**:
   - **migrate** *(Recommended)* — apply each chain step in order. Each step mutates `schema_version` to its target and applies its transform. Final atomic write (`icon-map.json.tmp` → `mv`). Preserve all keys not touched by any step (registries, stage_colors, matchers' unrelated fields, key order). State: **migrated-v`N`-to-v`SCHEMA_VERSION`** (e.g. `migrated-v1-to-v2`, future `migrated-v2-to-v3`, `migrated-v1-to-v3` for a two-step walk).
   - **overwrite** — replace with the plugin's empty current-schema template. The prompt description MUST spell out that this wipes all authored registries, matchers, and stage-colors. State: **overwritten**.
   - **keep-local** — leave the older-schema file untouched. Hooks remain inert (exit 0 with stderr diagnostic) until the user migrates. State: **v`N`-kept**, surface as a FAIL in the Step 6 report.

   #### Transforms table (one row per `N → N+1` step)

   When a worker version is released that bumps `SCHEMA_VERSION`, the author adds a row here describing the in-place transform from the previous schema. The walker concatenates rows whose source ≥ the consumer's `N` and whose target ≤ `SCHEMA_VERSION`. If any step in `N → … → SCHEMA_VERSION` is missing from this table, fall through to case 3a below.

   | Step | Transform | Implementation |
   |---|---|---|
   | 1 → 2 | Drop every `emit` key from every matcher; drop the legacy top-level `version` string (worker reads `schema_version` only); set `schema_version: 2`. | `jq 'del(.version) \| .schema_version = 2 \| .matchers = (.matchers \| map(del(.emit)))'` |

   #### 3a. Older schema with no migration path

   `schema_version < SCHEMA_VERSION` but the chain is incomplete (some intermediate step has no transforms-table row). Treat as a configuration error in the plugin itself, not a consumer fault. Render a single `AskUserQuestion` with two options: **overwrite** (same as 3's overwrite, wipes authored content) / **keep-local** (state: **migration-path-missing**, surface as FAIL). Do not offer a partial migration — half-applying the chain is worse than not applying it.
4. **Target present, `schema_version` outside `SUPPORTED_SCHEMA` on the high side** (future version the installed worker doesn't know) → **plugin too old** blocker. Report and do not edit. State: **blocker-plugin-too-old**.
5. **Target present, `schema_version == SCHEMA_VERSION` but `min_hook_version` exceeds the installed `HOOK_VERSION`** → same **plugin too old** blocker.

### Wizard discipline

Cases 2-drift, 3, and 3a each use **one** top-level `AskUserQuestion` (case 2-drift's `migrate` branch then issues N follow-up conflict prompts, one per conflicting key — that's expected, not a violation). Never ask a generic drift prompt (overwrite / keep-local) and then a second schema prompt (upgrade / keep) — when `migrate` is available, it must be the first option and labeled **(Recommended)**, so the user doesn't have to pick `keep-local` just to unlock a migration path. This applies to same-schema drift (merge with conflict prompts) and any older-schema drift the transforms table can chain to `SCHEMA_VERSION` (in-place schema upgrade — works for v1→v2 today, v2→v3 once that row lands, etc.).

## Step 3 — Install the pre-commit shim

Invoke the plugin worker's `install-hooks` subcommand. This writes the pre-commit shim to `.githooks/pre-commit`. No consumer `settings.json` mutation happens here (the PostToolUse hook is plugin-shipped; see architecture note above).

```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py install-hooks
```

If `core.hooksPath` is not set to `.githooks`, ask the user (single `AskUserQuestion`): **set-hooksPath** / **leave-as-is**. If set, run `git config core.hooksPath .githooks`.

## Step 4 — Create callbacks dir

```
mkdir -p .claude/callbacks
```

Leave empty; add a `.gitkeep` so the directory is tracked. (Users drop executable scripts here to implement exotic `callback:` matchers.)

## Step 4.5 — Ensure iconize `data.json` is gitignored

Iconize (`obsidian-icon-folder`) stores the vault's full icon-mapping database (path → icon, plus `settings` / `rules` / `recentlyUsedIcons`) in `.obsidian/plugins/obsidian-icon-folder/data.json`. The file is rewritten on every icon click and by the bundled `iconize-reloader` plugin (which bridges folder-note frontmatter into folder-keyed entries) — so it's runtime state, not source. Tracking it produces merge conflicts on every branch switch and noisy diffs on every commit.

Because this step runs only inside `iconize-install`, the opt-in is implicit: the user is scaffolding iconize-sync, so they clearly intend to use it.

1. `entry = ".obsidian/plugins/obsidian-icon-folder/data.json"` (repo-root relative — the path iconize writes regardless of vault subdir, because the vault is `.obsidian/` under the repo root per Step 1).
2. Target: `<repo-root>/.gitignore`. If it doesn't exist, `AskUserQuestion`: **create** (seed a new `.gitignore` containing just this entry) / **skip** (respect repos that intentionally have no `.gitignore`). One prompt, then honor the choice on re-runs via idempotency below.
3. Read the file (or start from empty if just created). If any non-comment line equals `entry` → state: **already-ignored**, no write.
4. Otherwise, append `entry` on its own line (prepend `\n` if the file doesn't end in one). State: **added**.
5. Check whether the file is currently tracked: `git ls-files --error-unmatch <entry>`. Exit 0 → emit a one-line WARN in the report reminding the user to run `git rm --cached <entry>` to stop tracking it. Never auto-`git rm` — that's a history-touching action, user's call.

Idempotent: re-running reports **already-ignored** every time after the first write.

## Step 5 — Verify

Run the worker's `check-versions`. Expect exit 0. Report shape includes:

- `pre_commit.status` — `ok` / `missing` / `major-drift` / `minor-drift`.
- `icon_map_schema.status` — `ok` / `incompatible` / `missing`.
- `icon_map_schema.declared`, `icon_map_schema.min_hook_version` — echo.

Any non-`ok` status surfaces as a drift finding; re-run the relevant step to resolve.

Then run `reconcile --dry-run` and print the plan so the user can see what a full sweep would do. Do not apply.

## Step 6 — Report

One bullet per step, in order — missing bullet = skipped step, back up and run it.

- **Step 1** — repo-root + vault paths (or abort reason).
- **Step 1.5a** `folder-notes`: state tuple (`binary=created|updated-<x>-to-<y>|unchanged overrides=... community=...`). Never `skipped` — hard deps abort the skill instead.
- **Step 1.5b** `obsidian-icon-folder`: state tuple. Never `skipped`.
- **Step 1.5c** `iconize-reloader`: state tuple. Never `skipped`.
- **Step 2** legacy protocol doc: **deleted** / **kept** / **not-present**.
- **Step 2.5** legacy PostToolUse: **stripped** (count) / **kept** / **not-present**.
- **Step 2.6** Iconize frontmatter settings: **asserted** / **fixed** / **kept-local** / **skipped** / **iconize-absent**.
- **Step 2.7** icon-map: **installed** / **unchanged** / **merged** (with `additions=N conflicts-kept-authored=N conflicts-took-shipped=N`) / **overwritten** / **kept-local** / **migrated-v`N`-to-v`SCHEMA_VERSION`** / **v`N`-kept** / **migration-path-missing** / **blocker-plugin-too-old**. Prepend **path-migrated** when the v1.0.0 legacy-path pre-flight ran (e.g. `path-migrated, merged`); **legacy-path-kept** when the user declined the path migration (FAIL).
- **Step 3** pre-commit shim: HOOK_VERSION + `core.hooksPath` (**set** / **already-set** / **left-as-is**).
- **Step 4** callbacks dir: **created** / **already-present** / **.gitkeep-added**.
- **Step 4.5** `.gitignore` (iconize data.json): **added** / **already-ignored** / **gitignore-created** / **skipped**; WARN if `git ls-files --error-unmatch` exits 0 (user runs `git rm --cached`, never auto).
- **Step 5** verify: `check-versions` status + `reconcile --dry-run` summary.

Next steps: "run `lazy-obsidian.iconize-config` to seed registries, then `lazy-obsidian.iconize-sync reconcile`." Add consequence lines for any **kept-local** / **skipped** assertion (2.6, 2.7, 4.5 only — hard-dep skips don't reach Step 6).

## Step 7 — Log the run

Log to `./.logs/claude/lazy-obsidian.iconize-install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Two-step write: `Bash(mkdir -p ...)` then `Write`.

## Failure modes

- **`/lazy-obsidian.iconize-install` aborts: no `.obsidian/` found** — the repo root has no Obsidian vault directory → initialize Obsidian in this repo first, then re-run.
- **`/lazy-obsidian.iconize-install` aborts: "Hard dependency `<id>` could not be installed/updated"** — `/lazy-obsidian.update-plugin` returned FAIL for `folder-notes`, `obsidian-icon-folder`, or `iconize-reloader` (network failure or registry lookup error) → check network connectivity, run `/lazy-obsidian.update-plugin <id>` manually to see the underlying error, then re-run.

## Idempotency

Safe to re-run. Drift prompts only fire when content actually differs. Step 2 (legacy protocol-doc migration) is idempotent — once the legacy file is deleted (or confirmed kept), subsequent runs report **not-present** / **kept** with no further prompt. Legacy PostToolUse detection (Step 2.5) is also idempotent — after the first re-run strips them, subsequent runs find nothing to strip. Icon-map orphan handling lives in Step 2.7's schema-aware decision matrix.

## Wizard discipline

Every decision point uses `AskUserQuestion`, one question at a time. Never bundle "delete legacy protocol? install icon-map?" into a single multi-select prompt. Legacy-stripping (Steps 2 and 2.5) each get their own prompt. The icon-map gets **one** schema-aware prompt (Step 2.7) whose options depend on the drift/schema case — so a v1-vs-v2 situation offers `migrate` alongside `overwrite` and `keep-local`, not a sequential drift-then-migration pair where `migrate` is hidden behind a prior choice.
