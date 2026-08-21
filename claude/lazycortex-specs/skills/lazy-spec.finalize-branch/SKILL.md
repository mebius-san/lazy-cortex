---
name: lazy-spec.finalize-branch
description: Use after merging or deleting a source-repo branch to rebase any specs pinned to that branch back to the repo's default branch — walks every `spec_source_branches` frontmatter entry in the vault, applies the shared Pin Reconciliation primitive, refuses to rewrite unmerged pins, and proposes `spec_released` for assets whose pinned docs covered the now-merged branch.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# Finalize Branch

Rebase spec source links from a feature branch back to the repo's default branch once that branch has merged (or been deleted), then propose the `spec_released` gate for each affected asset.

Pin reconciliation, the five flat gates, and source URLs are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those mechanics; it calls the named primitives and references the reference docs.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Discover repo records`
   - `Step 2 — Auto-fetch`
   - `Step 3 — Discover pinned specs`
   - `Step 4 — Reconcile`
   - `Step 5 — Report`
   - `Step 6 — Propose spec_released for affected assets`
   - `Step 7 — Verify`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Two invocation modes:

- **Explicit**: `lazy-spec.finalize-branch <branch>` — reconcile pins only for the named branch. If the branch is still open, report "still open" and exit without changes. Never force-drop an unmerged pin — pass `--force-merged` only when the operator confirms a squash-merge.
- **Auto**: `lazy-spec.finalize-branch --merged` — walk every pinned spec in the vault and reconcile each. Merged/deleted pins are rewritten; open pins are skipped with a note.

Flag:

- `--force-merged` — (explicit mode only) skip the `merge-base --is-ancestor` check; treat the branch as merged as long as it still exists. Use for squash-merges.

## Step 1 — Discover repo records

Read the `repos` section (`lazycortex-core settings-get repos`). For each repo key (skip the `_version` marker), call `lazy-spec.resolve-repo(<repo-key>)` to get `{local_path, branch (default), host, owner, repo, forge, base_url, …}`, and use the preferred remote (default: `origin`).

Products themselves live in `lazy.settings.json[products]` (resolve via `resolve-product`); this skill walks pinned files across the whole vault and attributes each to its owning product via `resolve-product by-path <rel-path>` when it needs the product context for a gate proposal.

## Step 2 — Auto-fetch

For each repo config, run:

```bash
git -C <local_path> fetch --prune <remote>
```

If any fetch fails (network, auth, missing remote), abort the skill with a clear error. Never operate on stale data.

## Step 3 — Discover pinned specs

Grep the vault for markdown files whose frontmatter contains `spec_source_branches:`. Collect one entry per `(file, repo-key, branch)` triple.

- In **explicit mode**, filter to entries whose branch matches the user's argument.
- In **auto mode**, keep all entries.

**Role filter**: per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, only `tech` docs and asset-level `code-plan` / `test-plan` docs may carry `spec_source_branches`. Identify role via the file's `spec_role:` frontmatter (not by filename — filenames are role-only). Any pin found in another file (design, status, code-report, test-report) is a rule violation — log a warning with the file path and skip reconciling it (don't silently "fix" a file that shouldn't contain URLs in the first place). Suggest running `/lazy-spec.doctor` to clean it up.

## Step 4 — Reconcile

For each entry, run the **Pin Reconciliation** primitive from `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`:

1. Resolve the repo config (already loaded above).
2. Branch status:
   - **Explicit mode + `--force-merged`**: skip ancestor check; treat as merged if the branch exists.
   - Otherwise: ancestor check against `refs/remotes/<remote>/<default>`. Not-an-ancestor ⇒ open (skip). No such ref anywhere ⇒ deleted (rewrite).
3. On rewrite: for every source URL in the file body whose prefix matches the resolved repo's `base_url` AND whose branch segment equals the pinned `<branch>`, rebuild it via `lazy-spec.source-url(<repo-key>, <path>, <kind>, branch=<default>)`. The forge-specific path-scheme detection (extracting `<kind>` and `<path>`) lives in the Pin Reconciliation primitive and delegates to the known-forges table — never do a literal substring replace on `/blob/<branch>/`. Remove the `<repo-key>` entry from `spec_source_branches`; drop the key entirely if the dict empties.

## Step 5 — Report

Print a summary grouped by action:

```
## Finalize Branch — <branch-or-"all merged">

### Rewrote (N)
- <file> — <repo-key>:<branch-name> → <default-branch> (merged)
- <file> — <repo-key>:<branch-name> → <default-branch> (deleted)

### Skipped — still open (N)
- <file> — <repo-key>:<branch-name> (branch open on remote)

### Skipped — fetch failed (N)
- <repo-key>: error message

### Warnings — pin on disallowed-role file (N)
- <file>: pin found in a file whose role forbids source URLs — run /lazy-spec.doctor to clean up
```

## Step 6 — Propose `spec_released` for affected assets

The flat-gate model is owned by `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md` — five top-level booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay on each asset's status folder-note. There is no `stage:`, no `awaits_human:`, no `## Workflow`, no per-step `flips_gate` machinery. The ONLY gate mutation channel is `/lazy-spec.flip-gate`.

For every asset folder that had at least one of its docs rewritten in Step 4 (a pinned `tech.md` or asset `code-plan.md` / `test-plan.md` whose branch just merged), read its status folder-note and check `spec_released`, `spec_cancelled`, AND `spec_tests_passing` — `/lazy-spec.flip-gate` no longer checks the release ladder itself (it flips unconditionally once confirmed, refusing only a cancelled asset), so this is the skill's own readiness check now, not a backstop. When `spec_released` is currently `false`, `spec_cancelled` is `false`, AND `spec_tests_passing` is `true`, PROPOSE the flip via one `AskUserQuestion` per asset (full-context block per the Wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`): name the asset, state that its source branch just merged, and that confirming runs `/lazy-spec.flip-gate <asset> spec_released`. Default-recommend "release" when the rebase covered the only open pin(s) on that asset. When `spec_tests_passing` is `false`, do NOT propose — report the asset as not yet release-ready and move on; do not rely on the primitive to catch it. On confirm, invoke via the `Skill` tool:

```
Skill(skill: "lazycortex-specs:lazy-spec.flip-gate", args: "<asset-dir> spec_released")
```

`flip_gate` no longer checks the `spec_released` precondition itself (`spec_tests_passing == true`, and the full ladder behind it: develop-done, plan-done, design-done) — it flips unconditionally once the operator confirms, refusing only when the asset is cancelled. This skill's own job is to check the readiness before proposing: read the status folder-note, and only surface the `AskUserQuestion` proposal when `spec_tests_passing` (and the rest of the ladder) already reads `true`. When it doesn't, skip the release for that asset instead of proposing a flip you know is premature — do NOT propose it and rely on a refusal that will not come. The rebase from Step 4 is already applied regardless; only the release flip is held back. The operator settles the stuck gate (e.g. flips `spec_tests_passing` once a green test report exists, or lets `spec.coordinator` derive it) and re-runs `/lazy-spec.finalize-branch`.

If `spec_cancelled: true`, skip silently — cancelled assets never advance. Every release flip's audit trail lives in the status folder-note's `# History` section written by `lazy-spec.flip-gate`; no separate product changelog is updated.

## Step 7 — Verify

Re-check the rewritten files for any surviving source URL whose prefix matches the resolved repo's `base_url` AND whose branch segment still equals the old pinned `<branch>`. Path-scheme detection (which segment is the branch) is delegated to the Pin Reconciliation primitive and the known-forges table — never grep for a literal `/blob/<branch>/`. Zero matches expected; flag any survivor as an error (the rewrite likely missed a URL due to an unusual quoting style).

## Failure modes

- **`/lazy-spec.finalize-branch` aborts: "fetch failed"** — network error, auth failure, or no remote configured for one of the repos in `lazy.settings.json[repos]` → fix connectivity or credentials and re-run; the skill never operates on stale refs.
- **`/lazy-spec.finalize-branch` reports "still open"** — the named branch is not an ancestor of the default branch and still exists on the remote → merge it first, or pass `--force-merged` for a confirmed squash-merge.
- **An asset never gets a `spec_released` proposal** — `spec_tests_passing` doesn't read `true` yet on its status folder-note, so Step 6's own readiness check skips it (the primitive itself no longer refuses this) → settle the holding gate first (flip `spec_tests_passing` once a green test report exists, or let `spec.coordinator` derive it), then re-run; the rebase itself was already applied.

## Guarantees

- **Never rewrites an unmerged pin** — even in explicit mode, without `--force-merged`.
- **Deleted = merged** — once a branch is gone locally and remotely (after `fetch --prune`), its pins are rewritten to the default.
- **Squash-merges**: the `merge-base --is-ancestor` check returns false because the squashed commit is not an ancestor of the source branch tip. Use `lazy-spec.finalize-branch <branch> --force-merged` for a one-shot, or delete the squashed branch and let the "deleted = merged" rule pick it up.
- **Idempotent** — re-running on an already-finalized branch is a no-op; the rebase finds no matching pins and `flip_gate` leaves an already-`true` `spec_released` untouched (a re-proposal is declined or the gate is already set).

## Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.finalize-branch/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.finalize-branch)`, then `Write` the file — never chain. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`. Body: `# lazy-spec.finalize-branch` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the canonical list. Record:

- Invocation mode (`<branch>`, `--merged`, with or without `--force-merged`).
- Files rewritten, skipped (with reason), and any fetch failures.
- `spec_released` flips proposed / applied / refused.

## Key Rules

- **Resolve via settings** — products live in `lazy.settings.json[products]`; attribute pinned files to a product via `resolve-product by-path` when product context is needed.
- **Auto-fetch each run** — abort on fetch failure, never use stale refs.
- **Never overwrite a spec the skill did not pin itself** — rewrites only happen when a branch is provably merged or deleted.
- **No cross-repo propagation** — if a spec pins `<repo-a-key>: <branch-a>` and also carries `<repo-b-key>: <branch-b>`, each entry is reconciled independently against its own repo config.
- **Respect file roles** — per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, only `tech` docs and asset-level `code-plan` / `test-plan` docs may carry pins. Pins found elsewhere are warned and skipped, not silently rewritten.
- **Proposes `spec_released`, never derives it** — after a successful rebase, proposes the `spec_released` flip (operator-confirmed) via `/lazy-spec.flip-gate` for each affected asset whose `spec_tests_passing` already reads `true`. The release readiness check is this skill's own now (Step 6) — `flip_gate` no longer re-checks it. The rebase is applied regardless of whether an asset gets a proposal at all.
