---
name: lazy-core.setup
description: "Meta-installer that runs every applicable plugin install + post-install configurator for the current project. Discovers `<namespace>.install` skills in enabled plugins and any skill carrying `lazy_setup_phase:` frontmatter, builds an ordered plan, runs each child, and reports results. Idempotent — safe to re-run after every plugin update or on a fresh project. Use after `/plugin update`, on a fresh clone, or after enabling a new plugin. Optional `--dry-run` previews the plan without executing."
allowed-tools: Read, Write, Glob, AskUserQuestion, Skill, Bash(mkdir -p *), Bash(git rev-parse *), Bash(date *)
---
# Run lazycortex meta-installer

Single command that brings the current project up-to-date with every enabled plugin's install + post-install configurator chain. Discovery is convention-based: any `<namespace>.install` skill in an enabled plugin runs automatically, and any skill that opts in via `lazy_setup_phase:` frontmatter participates without an edit to this skill.

## When to invoke

- After `/plugin update` to re-sync rule templates and pick up new configurators.
- On a fresh project clone, to bootstrap end-to-end.
- After enabling a new plugin.

## Arguments

- `--dry-run` — build the plan and render the preview, then stop without confirming or executing.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Discover`
   - `Step 2 — Plan`
   - `Step 3 — Preview`
   - `Step 4 — Confirm`
   - `Step 5 — Execute`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `discovered`, `planned`, `previewed`, `confirmed`, `ran`, `failed`, `aborted-by-user`, `dry-run`, `nothing-to-do`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Discover

Scan plugin sources for two opt-in mechanisms — both convention-based, no central registry:

1. **Plugin installers** — any skill whose directory name matches `*.install` inside an enabled plugin. Identify enabled plugins by reading `~/.claude/plugins/installed_plugins.json`. Use the entry's `installPath` field to resolve the cached source root.
2. **Cross-cutting / configurator skills** — any skill whose `SKILL.md` frontmatter declares `lazy_setup_phase:` with a value in `{pre-install, per-plugin, post-install}`.

Glob the source roots:

- `~/.claude/plugins/cache/**/skills/*/SKILL.md` — installed plugins.
- `claude/*/skills/*/SKILL.md` — monorepo dev sources (only relevant inside this repo; ignored if the directory is absent).

For each match, `Read` its frontmatter and record:

- `dispatch` — full skill name in `<plugin>:<namespace>.<name>` form. Use the plugin name from `installed_plugins.json` for cache hits, or the parent directory name for monorepo hits.
- `phase` — value of `lazy_setup_phase:` if present; else `per-plugin` if the directory name matches `*.install`; else **skip** (not part of the plan).
- `path` — absolute path to the `SKILL.md`.

Skills inside disabled plugins (cache hit but plugin not present in `installed_plugins.json`) are excluded.

Outcome: `discovered: N skills (M install + K configurator)`.

## Step 2: Plan

Group discovered skills by phase. Execution order is fixed:

1. **`pre-install`** — runs before any plugin templates land. Reserved for future use.
2. **`per-plugin`** — every `<namespace>.install` discovered above. Sort with `lazy-core.install` first (it seeds `lazy.settings.json` consumed by later steps), then alphabetical for the rest.
3. **`post-install`** — cross-cutters that depend on plugin templates already being in place. Sort alphabetical.

If the plan is empty (no enabled plugins ship `*.install` and no skill opts in), set outcome `nothing-to-do` and skip to Step 6.

Outcome: `planned: N total (P pre + Q per-plugin + R post)`.

## Step 3: Preview

Render the plan as a bullet list grouped by phase, in the order it will run:

```
pre-install:
  (none)
per-plugin:
  • lazycortex-core:lazy-core.install
  • lazycortex-log:lazy-log.install
  • lazycortex-obsidian:lazy-obsidian.install
post-install:
  • lazycortex-core:lazy-guard.allow-mcp
  • lazycortex-core:lazy-core.agent-models
```

Each line is the exact `<full-dispatch-string>` that will be passed to `Skill`. Outcome: `previewed`.

If invoked with `--dry-run`, set Step 4 and Step 5 outcomes to `dry-run` and skip directly to Step 6.

## Step 4: Confirm

Single `AskUserQuestion`:

- question: **"Run the planned setup chain (N skills across pre-install / per-plugin / post-install)?"**
- options:
  - `run` — proceed to Step 5.
  - `abort` — stop the run; set Step 5 outcome to `aborted-by-user` and skip to Step 6.

Outcome: `confirmed` or `aborted-by-user`.

## Step 5: Execute

For each skill in the plan, in plan order:

1. Invoke via `Skill(skill: "<full-dispatch-string>")`. The child owns its own interactivity (its own `AskUserQuestion` prompts, sub-confirmations) and its own `./.logs/claude/<child>/...` log.
2. Capture the child's outcome:
   - `ok` — the child reached its own Report step and reported success or no-op.
   - `failed: <reason>` — the child errored, was aborted, or surfaced an error in its report. Capture the reason verbatim.
   - `skipped` — the child's own confirmation was declined.
3. **On failure: log the entry and CONTINUE.** Never abort the loop — collect every result so the user gets a single coherent summary.

Per-skill outcomes accumulate in three lists for Step 6: `ok`, `failed`, `skipped`. Outcome: `ran: <ok>/<total> ok, <failed> failed, <skipped> skipped`.

## Step 6: Report

Render three sections plus a per-step status line. The Report MUST contain one line per Step 1–5 task and one line per child:

```
Step 1 — discovered: N skills (M install + K configurator)
Step 2 — planned: N total (P pre + Q per-plugin + R post)
Step 3 — previewed
Step 4 — confirmed | aborted-by-user | dry-run
Step 5 — ran: X/N ok, Y failed, Z skipped | dry-run | aborted-by-user

✓ ran successfully:
  • <full-dispatch-string>
  …
✗ failed:
  • <full-dispatch-string> — <reason>
  …
• skipped (declined inside child):
  • <full-dispatch-string>
  …
```

If failures exist, append: `Re-run /lazy-core.setup after fixing — idempotent.` Never offer interactive retry mid-run.

## Step 7: Log the run

Log to `./.logs/claude/lazy-core.setup/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

Frontmatter: `git_sha`, `git_branch`, `date`, `input` (the args passed, or `none`). Body: `# lazy-core.setup` heading, `## Actions` (per-step bullets including each dispatched child + its outcome), `## Result` (success / partial-failure / dry-run / aborted).

## Failure modes

- **`/lazy-core.setup` stops at Step 4: user chose "abort"** — the setup confirmation was declined → re-run when ready to proceed; individual children are idempotent and safe to re-run.
- **One or more child skills failed during Step 5** — the report shows which children returned `failed: <reason>` → fix the root cause reported per child, then re-run `/lazy-core.setup` (idempotent).

## Notes

- **Idempotent.** Children are individually idempotent; re-running after fixing a failure brings everything to current.
- **No fingerprint or SessionStart hook.** Manual invocation only.
- **No `--scope` flag.** Each child self-detects scope.
- **Adding a new install skill** to any enabled plugin is automatic — no edit to this skill needed. Adding a new configurator opts in via `lazy_setup_phase:` frontmatter.
- **Anti-pattern**: skills already chained from inside another install flow MUST NOT carry `lazy_setup_phase:`. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` for the contract.
