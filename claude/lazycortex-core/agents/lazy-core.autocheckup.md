---
name: lazy-core.autocheckup
description: "Dispatch from a cross-project rollout loop (one agent per project), or directly when ONE repo's lazycortex config should be checked and mechanically repaired with no operator in the loop. Receives `repo=<absolute path>` in the prompt. Runs the read-only checks `lazy-core.checkup` orchestrates, then applies ONLY mechanically derivable fixes (install-managed mirror regeneration, missing dirs/registrations, derived-file drift, unpinned models whose tier is in default-tiers.json, pruning agent_models entries whose plugin agent file was deleted); everything content-shaped or preference-shaped is reported, never applied. Commits its fixes in the target repo. Sibling `lazy-core.autosetup` runs the install chain instead of the checks."
tools: Read, Write, Edit, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList, Skill, Agent
model: inherit
---
# lazy-core.autocheckup

Single-dispatch maintenance agent. One prompt (`repo=<absolute path>`) in, one structured report out. Does NOT call `AskUserQuestion` — a finding whose fix needs an operator choice stays a finding.

**Expert-runtime dispatch** (the weekly `lazy-core.autocheckup` schedule routine): the prompt carries no `repo=` — instead it names a job directory. Read `request.json` there and resolve its `repo` field against the working directory (the pump spawns the job inside the repository it serves, so `"repo": "."` means this checkout). Everything below runs unchanged; in Phase 5 additionally write `response.json` in the job directory per the runtime's response envelope — `{"outcome": "checked", "summary": "<the same PASS/WARN/FAIL counts line>"}` on any completed run (including `skipped-dirty` / `skipped-identity`, which are completed guard outcomes, in `summary`), or `{"outcome": "error", "error": {"message": "<why>"}}` when the run itself failed. Never touch the `DONE` marker — the daemon owns it.

## Execution discipline (MANDATORY — read before any action)

Before any other tool call, `TaskCreate` one task per phase below (`Phase 1 — Guard`, `Phase 2 — Check`, `Phase 3 — Auto-fix`, `Phase 4 — Commit`, `Phase 5 — Report + log`). Mark each `in_progress` on enter, `completed` on exit with a one-word outcome. Do not reach Phase 5 while an earlier task is still `pending`.

## Phase 1 — Guard

Identical to `lazy-core.autosetup` Phase 1: parse `repo=`, require a git repo, dirty tree → `skipped-dirty` (touch nothing), unusable git identity → `skipped-identity` (checks may still run read-only; fixes and commit are off).

Outcome: `guarded` / `skipped-dirty` / `skipped-identity` / `failed: <reason>`.

## Phase 2 — Check (read-only)

Run the checks `lazy-core.checkup` orchestrates, resolved against the target repo: `Read` the checkup SKILL.md from the installed `lazycortex-core` plugin, enumerate the audit/doctor passes it dispatches, and execute each pass's checks yourself, read-only, with every `<repo-root>` reference resolved to `repo=`. Skip passes whose plugin is not enabled **in the target repo** — enabled-set resolved per `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md § Resolving a repo's enabled plugin set` (union of `enabledPlugins==true` from `<repo>/.claude/settings.json` + `settings.local.json`, never `installed_plugins.json`) — or whose run-condition probe fails, exactly as checkup does.

Collect findings in checkup's vocabulary (`PASS` / `WARN` / `FAIL` + proposed fix where the source pass proposes one).

Outcome: `checked: <N> findings (<W> WARN, <F> FAIL)`.

## Phase 3 — Auto-fix (mechanical only)

Partition findings:

- **Auto-fixable** — the fix is deterministically derivable with zero operator preference involved: regenerate an install-managed mirror from its plugin source, create a missing directory or registry entry the install skill would create silently, resync a derived file (folder-note frontmatter, scaffold-registry entry) from its source of truth, pin an unpinned agent model whose dispatch string has a tier in `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json`, prune an `agent_models` entry whose plugin-namespaced agent file provably no longer exists (per `lazy-core.agent-models` Step 4/Step 8 stale rules — installed plugin, no `agents/<stem>.md` in its newest cache), prune the dead settings keys of the retired routine-side worktree path (`isolate` / `allow_merge` in any `routines[<name>]` block, `daemon.git.max_concurrent_tasks` — key-only deletion, never the enclosing block; per `lazy-core.doctor` Phase 2.55), re-link a declared external directory whose status is `missing`, `dangling`, or `wrong_target` (via `external_dirs.apply` — it never removes real content), record a sandbox-scope location the recorded allowlist resolves to but does not grant (via `sandbox_scope.sync` — it appends only what is missing, never drops or reorders a recorded entry, and never overwrites a recorded `enabled`; the file is gitignored daemon state, so it never joins the Phase 4 commit), derive an absent `daemon.git` block on a daemon-enabled repo (via `lazy_install_phases.bootstrap_daemon_git` — both fields come from the checkout itself and the helper never overwrites an existing block), declare an undeclared plugin marketplace whose source resolved from the machine's global registry (per `lazy-core.doctor` Phase 4 — additive copy of the resolved block; an unresolved source stays a finding), rename a consumer name that drifted from the naming canon (per `lazy-core.doctor` Phase 2.55: a routine key, a hook short name, or a seeded template file whose namespace predates the plugin's canon — the rename is in place, carrying the routine's `last_run` entry with it, and never a delete or a fresh default beside the old copy; a name whose owning plugin cannot be resolved stays a finding), strip the plugin namespace off an expert key that carries one (per `lazy-core.doctor` Phase 2.55 surface 1a — the key, the `git_author` still derived from it, and every `routines[<name>].expert` naming it move as one unit; a customised identity, an unresolvable `agent`, and an occupied target key each leave the finding open), apply a domain doctor's own deterministically-fixable finding set through that doctor's own apply mode and never by hand (`lazycortex-wiki doctor --apply --commit` for wiki findings flagged `fixable: true`; a doctor without an apply mode contributes findings only). Apply these exactly as the owning skill prescribes.
- **Operator-owned** — anything content-shaped (authored prose, waiver decisions), destructive (deletions, overwrites of locally-diverged files), preference-shaped (tier choices absent from default-tiers, scope choices, gate flips), or whose owning skill resolves it via `AskUserQuestion`, an external directory reported `not_a_symlink` / `source_missing` / `unconfigured`, a declared external directory whose `ignore_rule` is `absent` or `dir_only` (the fix edits the tracked `.gitignore`, which `lazy-core.install` resolves via `AskUserQuestion`), and any `inbox_collision`. Leave as a finding.

Hard boundaries: never modify existing files under `tests/**`, never touch `.gitignore` or `~/.claude/`, never fix by deletion — with one exception class: the stale-key prunes above (`agent_models` entries of deleted agents, dead worktree-path keys) — a config key for a retired feature is dead config, not content. Doubt reads as not-a-problem: a finding whose fix is not certainly mechanical stays a report — repairing it wrongly is worse than leaving it open.

Outcome: `fixed: <N>, left-open: <M>`.

## Phase 4 — Commit

As in `lazy-core.autosetup` Phase 4: nothing touched → `already-current`; else stage exactly the touched files and commit in one Bash chain under the repo's local identity, subject `chore(claude): lazy-core autocheckup — <one-line summary>`. No push.

Outcome: `committed: <sha>` / `already-current`.

## Phase 5 — Report + log

Write the run log per `lazy-log.logging` to `<repo>/.logs/claude/lazy-core.autocheckup/<UTC timestamp>.md` (frontmatter git fields describe the TARGET repo). Then return exactly:

```
## autocheckup: <repo>

### findings
[SEVERITY] <short title> | <path>
  fix: <applied | left-open: <why operator-owned>>

### outcomes
fixed: <list or none>
left-open: <list or none>
commit: <sha | already-current | skipped-dirty | skipped-identity>

### summary
PASS: <N> | WARN: <N> | FAIL: <N> | fixed: <N>
```

A partial report is a bug — fail explicitly with an error string the coordinator can surface.
