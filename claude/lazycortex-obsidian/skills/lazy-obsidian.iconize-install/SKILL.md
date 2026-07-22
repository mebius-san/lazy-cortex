---
name: lazy-obsidian.iconize-install
description: "Scaffold the iconize-sync system into an Obsidian vault: local icon-map, pre-commit shim, and a `.gitignore` entry for Iconize's live `data.json` (it's rewritten on every icon click and by the bundled iconize-reloader plugin — runtime state, not source). Quiet file-sync — writes/merges silently when absent, unchanged, or non-conflicting; asks only on a genuine same-region conflict. Orphans (a retired vault-local protocol doc, stale worker-written PostToolUse entries) are left in place silently, never deleted. Migrates icon-map schema in place. Re-runnable; idempotent. Must be run from the consumer vault's git root. Installs all three iconize-sync hard-dependency plugins — `obsidian-icon-folder` (Iconize), `folder-notes`, and the bundled `iconize-reloader` — via the `/lazy-obsidian.update-plugin` primitive, which also deep-merges opinionated settings from `plugin-settings.json`. PostToolUse is plugin-shipped — no consumer settings.json mutation."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git ls-files*), Bash(git -C *), Bash(chmod *), Bash(python3 *), Bash(cp *), Bash(test *), Bash(date *), Bash(rm *), Bash(jq *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList
argument-hint: "[repo=<abs>] [--dry-run] — scaffolds into <repo-root>/.claude/ and <repo-root>/.githooks/ (repo= sets the target under headless dispatch)"
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
   - `Step 2 — Detect legacy protocol doc`
   - `Step 2.5 — Detect legacy PostToolUse entries`
   - `Step 2.6 — Assert Iconize frontmatter-feature settings`
   - `Step 2.7 — Icon-map scaffold (schema-aware, file-sync policy)`
   - `Step 3 — Install the pre-commit shim`
   - `Step 4 — Create callbacks dir`
   - `Step 4.5 — Ensure iconize data.json is gitignored`
   - `Step 5 — Verify`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `kept-orphan`).
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

- Repo root (`<repo-root>`):
  - **Headless dispatch** — if the invoking prompt carries `repo=<abs>` (a `repo=`-targeted run, e.g. from `lazy-core.autosetup` / `lazy-obsidian.install`), `<repo-root>` **is** that path. Do **not** run `git rev-parse` — a dispatched agent's Bash cwd is the coordinator's repo, not the target, so cwd-derived roots mutate the wrong repo.
  - **Interactive** — no `repo=` in the prompt: `<repo-root>` = `git rev-parse --show-toplevel` (cwd is the vault the operator is standing in).
- Vault (`<vault>`): walk from `<repo-root>` looking for `.obsidian/` (usually `<repo-root>` itself). If none found, abort with a message telling the user to initialize Obsidian first.

Every mutating command below MUST target `<repo-root>` / `<vault>` explicitly (`--vault <vault>`, `git -C <repo-root>`, absolute `<repo-root>/…` paths) — never a cwd-relative path or a cwd walk-up. Only the git/Claude-run hook entrypoints (the pre-commit shim, PostToolUse, Stop) are allowed to resolve the vault from cwd, because there cwd is guaranteed to be the repo.

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

## Step 2 — Detect legacy protocol doc

Pre-1.0.0 versions of this skill scaffolded `.claude/protocols/obsidian.iconize.md` as a vault-local copy of the protocol mechanics. v1.0.0 retires that copy — the canonical home is the plugin's `references/lazy-obsidian.iconize-protocol.md`, reachable at `${CLAUDE_PLUGIN_ROOT}/references/lazy-obsidian.iconize-protocol.md` for any agent or human reader. Two identical copies were redundant in source, and the install copy added a drift surface that paid for nothing (the body had no per-vault customization seams).

This is now an orphan: a file the plugin no longer ships. Orphans are never deleted and never prompted — the user may have customized it, and we can't prove it's safe to remove.

- **Target absent** (`.claude/protocols/obsidian.iconize.md` does not exist) → no prompt. Outcome: **not-present**.
- **Target present** → leave the file untouched, silently. Outcome: **kept-orphan**. The Step 6 report notes the file is a retired duplicate so the user can delete it manually if they wish.

## Step 2.5 — Detect legacy PostToolUse entries

Plugin versions ≤ 0.1.23 wrote a `PostToolUse` entry into the consumer's `.claude/settings.json` with a hardcoded absolute plugin path. That entry is now obsolete (the hook is plugin-shipped) and stale (path pinned to an old plugin version). It is an orphan of a previous version.

Orphans are left in place silently — never deleted, never prompted. The consumer's `settings.json` is their territory; auto-stripping a region of it (even a stale one) risks discarding adjacent edits or a hook the user re-pointed deliberately. The plugin-shipped hook self-gates and is harmless alongside a stale duplicate; the report tells the user the entry is dead so they can remove it by hand.

1. Read `.claude/settings.json`. If missing or not an object → Outcome: **not-present**.
2. Walk `settings.hooks.PostToolUse` (if present). Any group whose `hooks[].command` contains the string `iconize_sync.py` is a legacy entry.
3. If one or more legacy groups are found → leave them untouched. Outcome: **kept-orphan** (count). The report names the file + path so the user can strip them manually. If none found → Outcome: **not-present**.

Never mutate `settings.json` in this step.

## Step 2.6 — Assert Iconize frontmatter-feature settings

The worker writes icon/color into frontmatter under `iconize_icon` and `iconize_color`. Iconize must be configured to paint from those exact keys.

**Required settings** (in `<vault>/plugins/obsidian-icon-folder/data.json` under the `settings` object):

| Key | Required value |
|---|---|
| `iconInFrontmatterEnabled` | `true` |
| `iconInFrontmatterFieldName` | `"iconize_icon"` |
| `iconColorInFrontmatterFieldName` | `"iconize_color"` |

This is a clean deep-merge of opinionated plugin settings onto the existing `data.json` — apply silently unless a value directly contradicts an existing one.

Procedure:

1. Read `<vault>/plugins/obsidian-icon-folder/data.json`. If missing → WARN: "Iconize is not installed or hasn't been launched once. Re-run `/lazy-obsidian.update-plugin obsidian-icon-folder` or open Obsidian once to let it initialize its `data.json`, then re-run this skill." Skip this step (return to Step 2.7). Outcome: **iconize-absent**.
2. Extract `settings.iconInFrontmatterEnabled`, `settings.iconInFrontmatterFieldName`, `settings.iconColorInFrontmatterFieldName`.
3. Classify each of the three keys:
   - **Absent or already equal to the required value** → set/leave it to the required value silently (a missing key or an equal key is not a conflict — the shipped default applies cleanly). Preserve all other `settings` keys and all other top-level keys (`rules`, `recentlyUsedIcons`, path-keyed entries). Atomic write (`data.json.tmp` → `mv`) only when something changed. Outcome contribution: **asserted** (already equal) / **merged** (set from absent).
   - **Present with a non-default value the user deliberately set** (e.g. a custom `iconInFrontmatterFieldName` pointing at a different frontmatter key) → this is a genuine conflict: the shipped value and the local value disagree about the same setting and we can't tell which should win. This is the ONLY case that prompts.
4. If any key is a genuine conflict, `AskUserQuestion` (one prompt for the whole frontmatter-feature block — the three settings are conceptually a single toggle and make no sense partial):
   - question: `Iconize frontmatter settings conflict with shipped defaults — which wins?`
   - description: quote each conflicting key with both the local value and the required value, and note that frontmatter-driven icons paint from `iconize_icon` / `iconize_color` only when the shipped values are in effect.
   - options: **merge-shipped** / **keep-local**.
   - **merge-shipped** — rewrite the conflicting keys to the required values (preserving everything else; atomic write). Outcome: **merged**.
   - **keep-local** — leave the conflicting keys as the user has them; record that frontmatter-driven icons will not paint until the user reconciles Iconize settings manually. Outcome: **kept-local**.
5. Report state (aggregate across the three keys): **asserted** / **merged** / **kept-local** / **iconize-absent**.

## Step 2.7 — Icon-map scaffold (schema-aware, file-sync policy)

The icon-map uses a bilateral version handshake (`schema_version` + optional `min_hook_version`). The worker's preflight renders hooks inert (exit 0, stderr diagnostic) on mismatch — so a stale schema silently disables syncing.

This step is quiet by default: it writes, merges, and migrates the icon-map silently and prompts **only** on a genuine per-key value conflict (the same key carries different values in the authored file and the shipped template, and we can't tell which should survive). Adding shipped keys, keeping authored keys, and applying a schema transform are all non-contradicting operations done silently. "Conflict" ≠ "bytes differ".

Retrieve `SCHEMA_VERSION`, `SUPPORTED_SCHEMA`, and `HOOK_VERSION` from the worker: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py --vault <vault> check-versions`.

### Decision matrix

**Pre-flight (case 0): legacy-path migration.** Pre-1.0.0 versions of this skill placed the icon-map at `.claude/obsidian-iconize/icon-map.json`. The 1.0.0 layout is `.claude/iconize/obsidian-icon-map.json` — `iconize/` as the resolver subsystem dir, file name carries the platform tag. A path move is a clean `mv` with no content change — apply it silently, no prompt. If the legacy file exists AND the new path does not: `mkdir -p <repo-root>/.claude/iconize && mv <repo-root>/.claude/obsidian-iconize/icon-map.json <repo-root>/.claude/iconize/obsidian-icon-map.json && rmdir <repo-root>/.claude/obsidian-iconize 2>/dev/null`. Outcome contributes `path-migrated` to the Step 6 report; then continue with cases 1–5 below against the new path (the file is now at the new path → cases 2-or-later apply, never case 1). If both the legacy and the new path exist, leave the legacy file as a **kept-orphan** (don't clobber the new path) and proceed against the new path.

Cases 1–5 below operate on `<repo-root>/.claude/iconize/obsidian-icon-map.json`:

1. **Target missing** → install the plugin's template at `${CLAUDE_PLUGIN_ROOT}/templates/iconize/obsidian-icon-map.json`. No prompt. State: **installed**.
2. **Target present, `schema_version == SCHEMA_VERSION`** (handshake OK):
   - Byte-identical to template → no prompt. State: **unchanged**.
   - Byte-differs (authored customizations on the current schema) → **three-way merge silently**, no top-level drift prompt. For every top-level key and nested entry (registries' inner maps, `matchers[]` keyed by `id`, `stage_colors`):
     - Keys present only in shipped template → **add** to authored file (silent).
     - Keys present only in authored file → **keep** verbatim (silent).
     - Keys present in both with byte-equal values → no-op.
     - Keys present in both with **different** values → genuine conflict. Emit one `AskUserQuestion` per conflict (key path + both values shown): **keep-authored** / **take-shipped**. No bulk "resolve all" shortcut — each conflict is a separate decision. This is the ONLY prompt this case can raise; when there are no value conflicts the merge is fully silent.
     Atomic write (`icon-map.json.tmp` → `mv`). State: **merged** (annotate count of additions, conflicts-kept-authored, conflicts-took-shipped).
3. **Target present, `schema_version` (call it `N`) `< SCHEMA_VERSION` and a migration chain `N → N+1 → … → SCHEMA_VERSION` is fully covered by the transforms table below.** A missing `schema_version` is treated as `N=1` (pre-handshake back-compat). The schema transform is a non-contradicting in-place upgrade — **apply it silently**, no prompt. Apply each chain step in order; each step mutates `schema_version` to its target and applies its transform. Final atomic write (`icon-map.json.tmp` → `mv`). Preserve all keys not touched by any step (registries, stage_colors, matchers' unrelated fields, key order). State: **migrated-v`N`-to-v`SCHEMA_VERSION`** (e.g. `migrated-v1-to-v2`, future `migrated-v2-to-v3`, `migrated-v1-to-v3` for a two-step walk). After migrating, if the file now byte-differs from the current-schema template, run the case-2 three-way merge on top (silent except per-key value conflicts).

   #### Transforms table (one row per `N → N+1` step)

   When a worker version is released that bumps `SCHEMA_VERSION`, the author adds a row here describing the in-place transform from the previous schema. The walker concatenates rows whose source ≥ the consumer's `N` and whose target ≤ `SCHEMA_VERSION`. If any step in `N → … → SCHEMA_VERSION` is missing from this table, fall through to case 3a below.

   | Step | Transform | Implementation |
   |---|---|---|
   | 1 → 2 | Drop every `emit` key from every matcher; drop the legacy top-level `version` string (worker reads `schema_version` only); set `schema_version: 2`. | `jq 'del(.version) \| .schema_version = 2 \| .matchers = (.matchers \| map(del(.emit)))'` |

   #### 3a. Older schema with no migration path

   `schema_version < SCHEMA_VERSION` but the chain is incomplete (some intermediate step has no transforms-table row). Treat as a configuration error in the plugin itself, not a consumer fault — the plugin can't safely transform the file, so this IS a genuine conflict (we can't reconcile the authored content with the current schema without losing data). Render a single `AskUserQuestion`: **merge-shipped** (replace with the plugin's empty current-schema template — description MUST spell out that this wipes all authored registries, matchers, and stage-colors) / **keep-local** (state: **migration-path-missing**, surface as FAIL). Do not offer a partial migration — half-applying the chain is worse than not applying it.
4. **Target present, `schema_version` outside `SUPPORTED_SCHEMA` on the high side** (future version the installed worker doesn't know) → **plugin too old** blocker. Report and do not edit. State: **blocker-plugin-too-old**.
5. **Target present, `schema_version == SCHEMA_VERSION` but `min_hook_version` exceeds the installed `HOOK_VERSION`** → same **plugin too old** blocker.

### Conflict-prompt discipline

The only prompts this step raises are the per-key value-conflict prompts in case 2 (and the single can't-reconcile prompt in case 3a). A clean install (case 1), a no-op (case 2 byte-identical), a non-contradicting merge (case 2 with no value conflicts), a path move (case 0), and a schema transform (case 3) are all silent. Never raise a generic overwrite/keep-local drift prompt — bytes differing is not a conflict; only the same key carrying incompatible values on both sides is.

## Step 3 — Install the pre-commit shim

Invoke the plugin worker's `install-hooks` subcommand. This writes the pre-commit shim to `.githooks/pre-commit`. No consumer `settings.json` mutation happens here (the PostToolUse hook is plugin-shipped; see architecture note above).

```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py --vault <vault> install-hooks
```

Then reconcile `core.hooksPath`:

- **Unset** → `git -C <repo-root> config core.hooksPath .githooks` silently (clean apply — nothing local to contradict). Outcome: **set**.
- **Already `.githooks`** → no-op. Outcome: **already-set**.
- **Set to some OTHER path** → genuine conflict: the user points git at a different hooks dir and the pre-commit shim won't fire from `.githooks`. This is the ONLY case that prompts. `AskUserQuestion`: **set-hooksPath** (repoint to `.githooks`) / **keep-local** (leave the user's path; warn the shim won't run until they wire it in). Outcome: **set** / **kept-local**.

## Step 4 — Create callbacks dir

```
mkdir -p <repo-root>/.claude/callbacks
```

Leave empty; add a `.gitkeep` so the directory is tracked. (Users drop executable scripts here to implement exotic `callback:` matchers.)

## Step 4.5 — Ensure iconize `data.json` is gitignored

Iconize (`obsidian-icon-folder`) stores the vault's full icon-mapping database (path → icon, plus `settings` / `rules` / `recentlyUsedIcons`) in `.obsidian/plugins/obsidian-icon-folder/data.json`. The file is rewritten on every icon click and by the bundled `iconize-reloader` plugin (which bridges folder-note frontmatter into folder-keyed entries) — so it's runtime state, not source. Tracking it produces merge conflicts on every branch switch and noisy diffs on every commit.

Because this step runs only inside `iconize-install`, the opt-in is implicit: the user is scaffolding iconize-sync, so they clearly intend to use it.

1. `entry = ".obsidian/plugins/obsidian-icon-folder/data.json"` (repo-root relative — the path iconize writes regardless of vault subdir, because the vault is `.obsidian/` under the repo root per Step 1).
2. Target: `<repo-root>/.gitignore`. This is the one `.gitignore` write the skill is allowed to make (pre-existing, intentional behavior — runtime state must not be tracked). Apply it silently — no create/skip prompt:
   - **File absent** → create `<repo-root>/.gitignore` containing just `entry`. State: **gitignore-created**.
   - **File present** → read it. If any non-comment line equals `entry` → no write. State: **already-ignored**.
   - **File present, entry absent** → append `entry` on its own line (prepend `\n` if the file doesn't end in one). State: **added**.
3. Check whether the file is currently tracked: `git ls-files --error-unmatch <entry>`. Exit 0 → emit a one-line WARN in the report reminding the user to run `git rm --cached <entry>` to stop tracking it. Never auto-`git rm` — that's a history-touching action, user's call.

Idempotent: re-running reports **already-ignored** every time after the first write. This is the only `.gitignore` line the skill manages — it never touches other entries.

## Step 5 — Verify

Run the worker's `--vault <vault> check-versions`. Expect exit 0. Report shape includes:

- `pre_commit.status` — `ok` / `missing` / `major-drift` / `minor-drift`.
- `icon_map_schema.status` — `ok` / `incompatible` / `missing`.
- `icon_map_schema.declared`, `icon_map_schema.min_hook_version` — echo.

Any non-`ok` status surfaces as a drift finding; re-run the relevant step to resolve.

Then run `--vault <vault> --dry-run reconcile` and print the plan so the user can see what a full sweep would do. Do not apply.

## Step 6 — Report

One bullet per step, in order — missing bullet = skipped step, back up and run it.

- **Step 1** — repo-root + vault paths (or abort reason).
- **Step 1.5a** `folder-notes`: state tuple (`binary=created|updated-<x>-to-<y>|unchanged overrides=... community=...`). Never `skipped` — hard deps abort the skill instead.
- **Step 1.5b** `obsidian-icon-folder`: state tuple. Never `skipped`.
- **Step 1.5c** `iconize-reloader`: state tuple. Never `skipped`.
- **Step 2** legacy protocol doc: **kept-orphan** / **not-present**.
- **Step 2.5** legacy PostToolUse: **kept-orphan** (count) / **not-present**.
- **Step 2.6** Iconize frontmatter settings: **asserted** / **merged** / **kept-local** / **iconize-absent**.
- **Step 2.7** icon-map: **installed** / **unchanged** / **merged** (with `additions=N conflicts-kept-authored=N conflicts-took-shipped=N`) / **migrated-v`N`-to-v`SCHEMA_VERSION`** / **migration-path-missing** / **blocker-plugin-too-old**. Prepend **path-migrated** when the v1.0.0 legacy-path pre-flight moved the file; **kept-orphan** for the legacy path when both old and new paths exist.
- **Step 3** pre-commit shim: HOOK_VERSION + `core.hooksPath` (**set** / **already-set** / **kept-local**).
- **Step 4** callbacks dir: **created** / **already-present** / **.gitkeep-added**.
- **Step 4.5** `.gitignore` (iconize data.json): **added** / **already-ignored** / **gitignore-created**; WARN if `git ls-files --error-unmatch` exits 0 (user runs `git rm --cached`, never auto).
- **Step 5** verify: `check-versions` status + `reconcile --dry-run` summary.

Next steps: "run `lazy-obsidian.iconize-config` to seed registries, then `lazy-obsidian.iconize-sync reconcile`." Add consequence lines for any **kept-local** outcome (2.6, 2.7, 3) and for any **kept-orphan** (2, 2.5 — note the file is a retired duplicate the user can delete by hand). Hard-dep failures abort before Step 6.

## Step 7 — Log the run

Log to `./.logs/claude/lazy-obsidian.iconize-install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Two-step write: `Bash(mkdir -p ...)` then `Write`.

## Failure modes

- **`/lazy-obsidian.iconize-install` aborts: no `.obsidian/` found** — the repo root has no Obsidian vault directory → initialize Obsidian in this repo first, then re-run.
- **`/lazy-obsidian.iconize-install` aborts: "Hard dependency `<id>` could not be installed/updated"** — `/lazy-obsidian.update-plugin` returned FAIL for `folder-notes`, `obsidian-icon-folder`, or `iconize-reloader` (network failure or registry lookup error) → check network connectivity, run `/lazy-obsidian.update-plugin <id>` manually to see the underlying error, then re-run.

## Idempotency

Safe to re-run. Quiet file-sync prompts only on a genuine same-region/same-key conflict — never merely because bytes differ. Step 2 (legacy protocol doc) and Step 2.5 (legacy PostToolUse) never mutate: they report **kept-orphan** every run while the orphan is on disk, **not-present** once the user removes it by hand. The icon-map (Step 2.7) is silent on install / no-op / clean merge / schema transform and asks only per conflicting key value.

## Conflict-prompt discipline

The skill is quiet by default. The only `AskUserQuestion` prompts it raises are genuine conflicts, each as its own one-question prompt: per-conflicting-key icon-map merges (Step 2.7 case 2 / can't-reconcile case 3a), the Iconize frontmatter-feature conflict (Step 2.6, one prompt for the three-key block), and a non-`.githooks` `core.hooksPath` (Step 3). Orphans and clean applies are silent. "Conflict" means the same key/region carries incompatible values on both sides — bytes differing is not a conflict.
