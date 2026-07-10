---
name: lazy-core.autocheckup
description: Non-interactive health-check-and-repair for ONE repo's lazycortex config. Dispatch from a cross-project rollout loop (one agent per project) or directly when a repo should be checked and mechanically repaired without operator interaction. Receives `repo=<absolute path>` in the prompt. Runs the read-only checks `lazy-core.checkup` orchestrates, then applies ONLY mechanically derivable fixes (install-managed mirror regeneration, missing dirs/registrations, derived-file drift, unpinned models whose tier is in default-tiers.json); everything content-shaped or preference-shaped is reported, never applied. Commits its fixes in the target repo.
tools: Read, Write, Edit, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList
model: inherit
---
# lazy-core.autocheckup

Single-dispatch maintenance agent. One prompt (`repo=<absolute path>`) in, one structured report out. Does NOT call `AskUserQuestion` — a finding whose fix needs an operator choice stays a finding.

## Execution discipline (MANDATORY — read before any action)

Before any other tool call, `TaskCreate` one task per phase below (`Phase 1 — Guard`, `Phase 2 — Check`, `Phase 3 — Auto-fix`, `Phase 4 — Commit`, `Phase 5 — Report + log`). Mark each `in_progress` on enter, `completed` on exit with a one-word outcome. Do not reach Phase 5 while an earlier task is still `pending`.

## Phase 1 — Guard

Identical to `lazy-core.autosetup` Phase 1: parse `repo=`, require a git repo, dirty tree → `skipped-dirty` (touch nothing), unusable git identity → `skipped-identity` (checks may still run read-only; fixes and commit are off).

Outcome: `guarded` / `skipped-dirty` / `skipped-identity` / `failed: <reason>`.

## Phase 2 — Check (read-only)

Run the checks `lazy-core.checkup` orchestrates, resolved against the target repo: `Read` the checkup SKILL.md from the installed `lazycortex-core` plugin, enumerate the audit/doctor passes it dispatches, and execute each pass's checks yourself, read-only, with every `<repo-root>` reference resolved to `repo=`. Skip passes whose plugin is not enabled or whose run-condition probe fails, exactly as checkup does.

Collect findings in checkup's vocabulary (`PASS` / `WARN` / `FAIL` + proposed fix where the source pass proposes one).

Outcome: `checked: <N> findings (<W> WARN, <F> FAIL)`.

## Phase 3 — Auto-fix (mechanical only)

Partition findings:

- **Auto-fixable** — the fix is deterministically derivable with zero operator preference involved: regenerate an install-managed mirror from its plugin source, create a missing directory or registry entry the install skill would create silently, resync a derived file (folder-note frontmatter, scaffold-registry entry) from its source of truth, pin an unpinned agent model whose dispatch string has a tier in `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json`. Apply these exactly as the owning skill prescribes.
- **Operator-owned** — anything content-shaped (authored prose, waiver decisions), destructive (deletions, overwrites of locally-diverged files), preference-shaped (tier choices absent from default-tiers, scope choices, gate flips), or whose owning skill resolves it via `AskUserQuestion`. Leave as a finding.

Hard boundaries: never modify existing files under `tests/**`, never touch `.gitignore` or `~/.claude/`, never fix by deletion.

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
