---
name: lazy-observe.audit
description: "Audit the lazycortex-observe plugin: verify any rule files still encode their invariants and cross-check artifact conventions. Read-first; presents findings, asks before fixing. Severity: PASS / WARN / FAIL."
allowed-tools: Read, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList
---
# lazy-observe.audit

Audit the `lazycortex-observe` plugin for rule-body integrity and cross-artifact consistency. Read-first; nothing is mutated until the user approves.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executor MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Scan rule files`
   - `Step 2 — Cross-artifact check`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it".
3. **Do not reach Step 3 (Report) until `TaskList` shows every prior task `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one outcome line per step.

## Step 1: Scan rule files

- `Glob: claude/lazycortex-observe/rules/*.md`. For each file, verify frontmatter parses and the body still encodes the invariants the plugin relies on. (No invariants yet → `INFO no rule files shipped`.)

Outcome: per-rule severity line, or `INFO no rule files shipped`.

## Step 2: Cross-artifact check

- `Glob: claude/lazycortex-observe/skills/*/SKILL.md` and `claude/lazycortex-observe/agents/*.md`. Verify each carries the execution-discipline preamble (or a `execution-discipline-waiver:` frontmatter key) per `lazy-core.skill-writing § 1` and `lazy-core.agent-writing § 4`.
- Verify the logging rule is satisfied: each artifact references `.logs/claude/<name>/` somewhere in its body.

Outcome: per-artifact severity line.

## Step 3: Report

Render a markdown report. Severity: `PASS` / `WARN` / `FAIL` / `INFO`. One section per scan; one line per finding (`[SEVERITY] title | path:line`).

Outcome: `reported`.

## Step 4: Log the run

Two separate calls — `Bash(mkdir -p .logs/claude/lazy-observe.audit)` then `Write` to `.logs/claude/lazy-observe.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Frontmatter: `git_sha`, `git_branch`, `date`, `input`. Body: report.

Outcome: `logged`.
