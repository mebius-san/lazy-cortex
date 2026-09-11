---
name: lazy-core.setup
description: "Run after `/plugin update`, on a fresh clone, after enabling a new plugin, or whenever the operator asks to set lazycortex up in this project — the meta-installer that discovers and runs every enabled plugin's `<namespace>.install` skill plus any `lazy_setup_phase:` configurator in one ordered pass, so the operator never invokes install skills one by one. Idempotent; `--dry-run` previews the plan without executing."
allowed-tools: Read, Write, AskUserQuestion, Skill, Bash(mkdir -p *), Bash(git rev-parse *), Bash(date *), Bash(PYTHONPATH=* python3 *), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
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

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Migrate settings`
   - `Step 1 — Discover`
   - `Step 2 — Plan`
   - `Step 3 — Preview`
   - `Step 4 — Proceed`
   - `Step 5 — Execute`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `up-to-date`, `migrated`, `discovered`, `planned`, `previewed`, `proceed`, `ran`, `failed`, `dry-run`, `nothing-to-do`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 0: Migrate settings

Bring `.claude/lazy.settings.json` up to the current per-section schema version before any installer reads or writes it. The migration ladder lives in `${CLAUDE_PLUGIN_ROOT}/bin/lazy_settings_migrations/` and is exposed via the `lazy_settings.py` CLI.

Run exactly:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazy_settings.py" migrate .claude/lazy.settings.json)
```

The script prints one summary line, optionally followed by per-section upgrade lines. Examples:

- `migrated: 0 sections (6 up-to-date)` — no migrations needed (also the result when the settings file is absent — every section starts at its current version).
- `migrated: 2 sections (4 up-to-date)` followed by `  review: v1 -> v2` etc. — ladder applied.

Capture the summary line (and any per-section lines) for the Step 6 report.

Outcome:

- `up-to-date` if zero sections were migrated.
- `migrated: N sections (M up-to-date)` if any section was upgraded.
- `failed: <stderr>` if the CLI exits non-zero — stop the run, surface the failure in Step 6, and skip Steps 1–5 with outcome `aborted-by-migration-failure`.

## Step 1: Discover

Scan plugin sources for two opt-in mechanisms — both convention-based, no central registry:

1. **Plugin installers** — any skill whose directory name matches `*.install` inside an enabled plugin. Resolve the enabled set per `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` § "Resolving a repo's enabled plugin set": the union of the `enabledPlugins` maps in `./.claude/settings.json` and `./.claude/settings.local.json`, every key whose value is `true`, with the `@<marketplace>` suffix stripped off each key. That union is the only authority for enablement. `~/.claude/plugins/installed_plugins.json` is a machine-wide registry spanning every project on this host, so it MUST NOT be read as an enablement signal — consult it solely to resolve an enabled plugin's `installPath` (any entry for that plugin will do; the cache path is per-plugin-version, not per-project).
2. **Cross-cutting / configurator skills** — any skill whose `SKILL.md` frontmatter declares `lazy_setup_phase:` with a value in `{pre-install, per-plugin, post-install}`.

Both mechanisms are resolved by one primitive — run exactly:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazy_setup.py" discover .)
```

It prints one JSON object. `skills` is the chain already in execution order (Step 2's order), each entry carrying `dispatch` (`<plugin>:<namespace>.<name>`), `phase`, `path` (absolute `SKILL.md`), `plugin`, and `live_session` (ignored here — the interactive chain runs such skills normally). `plugins` maps every enabled plugin to the source root the chain reads it from: in a plugin-authoring repo (`dev_mode: true`) an enabled plugin's `claude/<plugin>/` sources outrank its cached copy. `skipped` lists enabled plugins the machine has no sources for — report each as `skipped: plugin not installed on this machine`, never a hard failure. Skills inside plugins outside the enabled union never appear — a cache hit for a plugin this repo does not enable belongs to some other project on this host.

The primitive is the whole step: no listing of the plugin cache or of `claude/*/skills/` by this skill, whatever tool the session offers. A non-zero exit is `failed: <stderr>` — stop the run and surface it in Step 6.

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
  • lazycortex-obsidian:lazy-obsidian.install
post-install:
  • lazycortex-core:lazy-guard.allow-mcp
  • lazycortex-core:lazy-core.agent-models
```

Each line is the exact `<full-dispatch-string>` that will be passed to `Skill`. Outcome: `previewed`.

If invoked with `--dry-run`, set Step 4 and Step 5 outcomes to `dry-run` and skip directly to Step 6.

## Step 4: Proceed

No confirmation prompt — running the install chain is the whole point of invoking `/lazy-core.setup`, and `--dry-run` (handled in Step 3) is the only preview-without-execute path. Each child owns its own interactivity, so the meta-installer never adds a redundant top-level gate.

Proceed straight to Step 5. Outcome: `proceed` (or `dry-run` when Step 3 already short-circuited).

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

Render three sections plus a per-step status line. The Report MUST contain one line per Step 0–5 task and one line per child:

```
Step 0 — up-to-date | migrated: N sections (M up-to-date) | failed: <stderr>
Step 1 — discovered: N skills (M install + K configurator)
Step 2 — planned: N total (P pre + Q per-plugin + R post)
Step 3 — previewed
Step 4 — proceed | dry-run
Step 5 — ran: X/N ok, Y failed, Z skipped | dry-run | aborted-by-migration-failure

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

- **`/lazy-core.setup` stops at Step 0: migration ladder errored** — `lazy_settings.py migrate` exited non-zero → read the captured stderr in the Step 6 report, fix the underlying ladder bug (typically a malformed `MIGRATIONS = {...}` callable in `lazy_settings_migrations/<section>.py`), then re-run `/lazy-core.setup`. Steps 1–5 do not run until the settings file is current.
- **`/lazy-core.setup` ran a child you didn't want** — there is no top-level confirmation; the chain runs every discovered installer. Use `--dry-run` first to preview the plan, or disable the unwanted plugin before re-running. Individual children are idempotent and safe to re-run.
- **One or more child skills failed during Step 5** — the report shows which children returned `failed: <reason>` → fix the root cause reported per child, then re-run `/lazy-core.setup` (idempotent).

## Notes

- **Idempotent.** Children are individually idempotent; re-running after fixing a failure brings everything to current.
- **No fingerprint or SessionStart hook.** Manual invocation only.
- **No `--scope` flag.** Each child self-detects scope.
- **Adding a new install skill** to any enabled plugin is automatic — no edit to this skill needed. Adding a new configurator opts in via `lazy_setup_phase:` frontmatter.
- **Anti-pattern**: skills already chained from inside another install flow MUST NOT carry `lazy_setup_phase:`. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` for the contract.
