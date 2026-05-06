---
chapter_type: block
summary: Bootstrap lazycortex-log in a project with /lazy-log.install, then verify the logging rule stays coherent with /lazy-log.audit.
last_regen: 2026-05-05
no_diagram: true
source_skills:
  - lazy-log.install
  - lazy-log.audit
---
# Install and audit lazycortex-log

Getting lazycortex-log running in a project takes one command and under a minute. Keeping it coherent as skills evolve takes another. This block covers both: `/lazy-log.install` lays the foundation; `/lazy-log.audit` verifies it is still intact whenever something changes.

## What's in this block

### /lazy-log.install — bootstrap

`/lazy-log.install` detects whether the plugin is enabled at project or user scope, then works through eight ordered steps to set up everything the plugin needs.

It starts by discovering which rule templates the plugin ships (via a glob against the plugin cache — never a hardcoded list), then walks you through each one. For a rule that is not yet present it asks whether to install it; for a rule that has drifted from the shipped version it shows the diff and asks whether to overwrite or keep your local edits; for a rule left behind by a prior plugin version it asks whether to delete or keep it. One prompt at a time, one decision at a time.

Beyond rule files, the skill creates `.logs/changelog.md` if it does not already exist (the seed file that `lazy-log.distill` will later populate), appends a `.logs/` entry to `.gitignore` so that per-contributor run logs and the structured commit log stay out of version control, and seeds `lazy.settings.json` with `agent_models` entries for every log agent the plugin ships. Tier values for those entries come from `lazycortex-core`'s `default-tiers.json` at runtime — the skill never hardcodes them. Finally, it registers the `lazy-log.commit-recorder` post-commit hook so that every subsequent `git commit` lands in `.logs/commits.jsonl` automatically. The whole sequence is idempotent: re-running after a plugin update or a manual rule edit is always safe.

### /lazy-log.audit — verify

`/lazy-log.audit` is read-only until you tell it to act. It checks the installed rule file in the main session, then fans out three parallel Explore subagents — one for skills, one for agents, one for commands — each looking for any optional `## Logging` sections that disagree with the rule.

The inline checks confirm that `.claude/rules/lazy-log.logging.md` is present, has a `description` field in its frontmatter, specifies `./.logs/claude/<name>/` as the log path, references `git_sha` capture via `git rev-parse HEAD`, uses UTC timestamps, and calls out the two-step write pattern (`Bash(mkdir -p ...)` then the `Write` tool — never chained with `&&`). Any per-file `## Logging` sections that point to a different path, use a non-standard timestamp format, or suggest chaining are flagged as `[WARN]`. A missing rule file is `[FAIL]` and short-circuits the cross-checks. After collecting all findings, the skill presents a report and asks which items to fix — nothing is mutated without confirmation.

## How they work together

Install bootstraps; audit verifies later. The typical sequence is: enable the plugin, run `/lazy-log.install` once to wire everything up, then let the project proceed. Audit enters the picture in three situations:

- After `/plugin update lazycortex-log@lazycortex` — the plugin cache refreshes but rule files in `.claude/rules/` do not update automatically. Re-running `/lazy-log.install` syncs them; `/lazy-log.audit` confirms the sync landed cleanly.
- After a manual rule edit — if a rule file was hand-edited, `/lazy-log.audit` surfaces any divergence from the expected content before it silently propagates into future run logs.
- When run-log files appear in unexpected locations — if a skill is logging to `~/.claude/...` or a hardcoded project path rather than `./.logs/claude/<name>/`, the cross-check agents catch it and the report gives you the exact file and line.

Running audit regularly is low-cost: it is read-only, takes a few seconds, and produces a structured report. Running it after any install-adjacent change keeps the logging foundation solid.

## Where this fits

This block is the foundation layer for the rest of lazycortex-log. Once install and audit are healthy:

- The **change-history block** (`/lazy-log.recall`, `/lazy-log.timeline`, `/lazy-log.summary`) can surface past changes reliably because the run-log paths and `git_sha` fields are consistent across all artifacts.
- The **changelog block** (`/lazy-log.distill`, `/lazy-log.bullets`) can build human-readable prose because `.logs/commits.jsonl` is being populated by the commit-recorder hook that install registered.
- The **housekeeping block** (`/lazy-log.clean`) can classify orphaned log folders accurately because the canonical skill namespace is stable and the logging rule is coherent.

Skipping install or running with a broken rule produces gaps in all three downstream flows. Running audit first is the fastest way to confirm the foundation is ready before relying on any of them.
