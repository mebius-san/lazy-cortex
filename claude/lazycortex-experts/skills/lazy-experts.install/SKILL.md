---
name: lazy-experts.install
description: "Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds agent-model tiers for the three generic agents (interpreter, designer, planner) from `lazycortex-core`'s `default-tiers.json` into `lazy.settings.json[agent_models].lazycortex`. Ships no expert-entry seeding — composition lives in the consumer's `lazy.settings.json[experts]`. Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(ls *), Bash(python3 *), AskUserQuestion
---
# Install lazycortex-experts

Seed agent-model tiers for the three generic agents in the consumer's `lazy.settings.json` so dispatch routing picks up the right Claude tier for each. No rules to sync (this plugin ships none); no expert entries to seed (composition is consumer-side per `docs/specs/2026-05-13-experts-plugin-design.md § 7`).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine target paths`
   - `Step 3 — Seed lazy.settings.json`
   - `Step 4 — Verify / Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `unchanged`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-experts@lazycortex` key holds an array — non-empty proves the plugin is installed and usable in the current cwd.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless.

Inspect the `scope` field of the entries:
- `"user"` → global, target `~/.claude/lazy.settings.json`.
- `"project"` → per-project, target `<repo-root>/.claude/lazy.settings.json`.

If both scopes appear, ask the user which to target. Default: `project`.

Abort **only** if `lazycortex-experts@lazycortex` is absent or its array is empty. Message: `lazycortex-experts not enabled — add "lazycortex-experts@lazycortex": true to enabledPlugins in your settings.json and run /plugin install lazycortex/lazycortex-experts.`

Outcome: `scope-detected: <user|project>`.

## Step 2: Determine target paths

| Scope | `lazy.settings.json` path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` (root = `git rev-parse --show-toplevel`, or cwd if not in a git repo — warn the user) |

Locate `lazycortex-core`'s shipped defaults file:

```bash
ls ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/skills/lazy-core.agent-models/default-tiers.json | sort -V | tail -1
```

Newest version wins. If the file is absent → FAIL with `lazycortex-core not installed; install it before /lazy-experts.install`. Do NOT fall through to a hardcoded fallback — silent drift is exactly what the SOT is meant to prevent.

Outcome: `target-resolved: <path>`, `defaults-resolved: <path>`.

## Step 3: Seed lazy.settings.json

Read the target `lazy.settings.json`. If missing or unparseable, initialize as `{"_version": 1, "agent_models": {}}`. Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite other groups).

Read the resolved defaults JSON. Select every key under `defaults` that starts with `lazycortex-experts:` — these are the entries to seed.

For each `(dispatch, tier)` pair from the defaults file, write back only if anything changed:

- **absent** in `agent_models.lazycortex` → add the entry. State `added`.
- **equal** → leave untouched. State `unchanged`.
- **different** → leave the user's value untouched. State `kept-local` (report both values).

Never touch other `lazycortex` entries (seeded by sibling install skills).

If any mutation happened, write the file with `_version: 1` preserved at the top.

Outcome (one line per seeded entry): `lazycortex.<key> = <tier> (<state>)`.

## Step 4: Verify / Report

- Read back the written `lazy.settings.json` and confirm it parses + contains the three `lazycortex-experts:*` keys under `agent_models.lazycortex`.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from (from `installed_plugins.json`).
  - Defaults file path used.
  - Per-key outcome.

Outcome: `verified` or `verify-failed: <reason>`.

## Step 5: Log the run

Log to `./.logs/claude/lazy-experts.install/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-experts.install)` then the `Write` tool. Never chain.

Outcome: `logged: <path>`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/lazy-experts.install` aborts: "plugin not enabled"** — `lazycortex-experts@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-experts@lazycortex": true` to `enabledPlugins` in `settings.json`, restart Claude Code, re-run.
- **`/lazy-experts.install` aborts: "lazycortex-core not installed"** — the defaults file glob returned nothing → install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

## Notes

- **Idempotent**: re-running this skill is safe. Entries are only added when absent; existing entries are never overwritten.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does not re-sync settings. Re-run if `default-tiers.json` shipped new `lazycortex-experts:*` rows in a later release.
- **Scope independence**: project-scope installs do not affect global config.
