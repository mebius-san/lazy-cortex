---
name: lazy-spec.audit
description: "Run when the operator asks whether the lazycortex-specs plugin itself is internally consistent — the decisions-registry rule still matches what the code relies on, every CLI verb is documented, every skill and reference resolves. Read-only; findings name the fix (re-run `/lazy-spec.install`, edit the drifted file, run `/lazy-spec.doctor`) rather than applying one."
allowed-tools: Read, Glob, Grep, Bash(mkdir -p *), Agent
---
# Audit lazycortex-specs

Read-only health check over the plugin's own artifacts: does `rules/spec.decisions.md` still describe invariants the code actually holds, and is the skill/command/reference/template surface internally coherent. Findings are surfaced; nothing is mutated. This is the plugin's `<namespace>.audit` per the maintainer contract — `lazy-spec.doctor` is the separate, unrelated skill that audits a *consumer's* spec catalog content, not this plugin's own sources.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Dispatch parallel scan agents A/B/C/D`
   - `Step 2 — Merge findings by severity`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it".
3. **Do not reach the Report step until `TaskList` shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per Agent (A/B/C/D). A missing line is a bug; do not render the report with gaps.

## Step 1 — Dispatch parallel scan agents A/B/C/D

Dispatch all 4 agents in a **single assistant message with 4 Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Coordinator pattern, dispatch rules, and structured-report contract (`## scan: …` + `### findings` with `[SEVERITY] title | path:line` + `### summary`) are owned by `lazy-core.parallel-scan.md` (in `lazycortex-core`) — read it before authoring or modifying agent prompts. Severity vocabulary: `PASS` / `WARN` / `FAIL` / `INFO`. Budget per agent: "Report under 600 words".

### Agent A — Decisions-rule semantics

Scope: `claude/lazycortex-specs/rules/spec.decisions.md`, `claude/lazycortex-specs/bin/spec_decisions.py`, `claude/lazycortex-core/references/lazy-core.markdown-style.md`, `claude/lazycortex-specs/skills/lazy-spec.set-stage/SKILL.md`, `claude/lazycortex-specs/references/lazy-spec.layout-protocol.md`, `claude/lazycortex-specs/references/lazy-spec.lifecycle-protocol.md`, `claude/lazycortex-specs/skills/lazy-spec.doctor/SKILL.md`.

Verify the rule's invariants still hold against the plugin's actual state, not just that the rule file has valid frontmatter (`lazy-core.doctor` already covers that generically):

- `spec.decisions.md` exists; `paths:` is a YAML block-list (not an inline array — a rule with an inline `paths: [...]` silently never loads); the first body line states the spec-catalog self-limitation. Missing / inline-array `paths:` → FAIL. Missing self-limitation line → WARN.
- The `spec_role` closed set in `lazy-spec.layout-protocol.md`, `lazy-spec.lifecycle-protocol.md`, and `lazy-spec.doctor/SKILL.md` each lists `decisions` as a legal value. Missing from any of the three → FAIL — the rule's own "unrecoverable from the artifact" test presumes decisions is a recognized, addressable role.
- `lazy-core.markdown-style.md` carries both a `[!decision] #spec/decision` row and a `[!decision-candidate]` row. Missing either → FAIL — the rule's decision-candidate bar and the registry's transfer source have nothing to point at.
- `bin/spec_decisions.py` still declares `_LIVING_ROLES` as exactly `{design, bug, tech, architecture}` and `_HALT_FLAGS` as exactly `{spec_cancelled, spec_halted, spec_released}` (grep the literal set contents). Drift → FAIL — the rule and the primitive would silently disagree on which docs originate decisions and which asset states block a transfer.
- `lazy-spec.set-stage/SKILL.md` calls `lazycortex-specs decide promote` on the approve transition of a living doc. Missing → FAIL — this is the design's sole integration point for every automatic transfer.

### Agent B — Skills & CLI surface

Scope: `claude/lazycortex-specs/skills/*/SKILL.md`, `claude/lazycortex-specs/commands/lazy-spec.help.md`, `claude/lazycortex-specs/bin/lazycortex-specs`, `claude/lazycortex-specs/.claude-plugin/overview.md`.

- Every `skills/*/SKILL.md` opens with YAML frontmatter carrying a `name:` or `description:` key. Missing → FAIL.
- Every subcommand token dispatched in `bin/lazycortex-specs`'s subcommand table (`open-request`, `apply-request`, `resolve-product`, `resolve-language`, `flip-gate`, `gate-tick`, `scaffold-asset`, `render-container-stats`, `coordinator-dispatch`, `note-set-key`, `note-check`, `mark-job`, `upstream-tick`, `upstream-doctor`, `decide`) is named somewhere in `commands/lazy-spec.help.md`. Missing → WARN — an operator asking `/lazy-spec.help` what the plugin can do won't learn the verb exists.
- `lazy-spec.decide` and `lazy-spec.audit` both appear in `overview.md`'s `## Blocks` section. Missing → WARN.

### Agent C — References integrity

Scope: `claude/lazycortex-specs/skills/**/SKILL.md`, `claude/lazycortex-specs/rules/*.md`, `claude/lazycortex-specs/references/*.md`.

- Every `${CLAUDE_PLUGIN_ROOT}/references/spec.*.md` path cited from a skill or rule body resolves to an existing file under `references/`. Broken pointer → FAIL.
- `rules/spec.decisions.md` itself: `paths:` is exactly `["**/*.md"]` (no extra globs, no `always_loaded:`), no fenced code block over 10 lines, dot-namespaced filename. Any deviation → WARN.

### Agent D — Templates & worker wiring

Scope: `claude/lazycortex-specs/templates/**`, `claude/lazycortex-specs/bin/*.py`.

- No `decisions.md` template exists anywhere under `templates/spec.*/` — the primitive writes its own frontmatter and header; a template would fight it (design's own "no shipped template" clause). Presence → WARN.
- Every `bin/*.py` module defining a `main(argv)` entry point is dispatched from `bin/lazycortex-specs`'s subcommand table. An orphaned worker → WARN.

## Step 2 — Merge findings by severity

Merge the four agents' findings. Do not re-run or re-derive — fold each agent's report verbatim into the corresponding subsection.

## Step 3 — Report

```
## lazycortex-specs — Plugin Audit Report

scan: Agent A decisions-rule-semantics — <PASS|WARN|FAIL> (<N> findings)
scan: Agent B skills-cli-surface — <PASS|WARN|FAIL> (<N> findings)
scan: Agent C references-integrity — <PASS|WARN|FAIL> (<N> findings)
scan: Agent D templates-worker-wiring — <PASS|WARN|FAIL> (<N> findings)

### Failures
- [ ] <finding> | <path:line>

### Warnings
- [ ] <finding> | <path:line>

### Info
- <n> checks passed clean
```

This skill never writes a fix itself — a rule/reference drift is a hand-edit of the plugin source, a missing help-doc row is a hand-edit of `lazy-spec.help.md`, and structural findings about a consumer's own spec content are `/lazy-spec.doctor`'s job, not this one's.

## Step 4 — Log the run

Per `lazy-log.logging`, write a run log to `./.logs/claude/lazy-spec.audit/YYYY-MM-DD_HH-MM-SS.md`: `mkdir -p` then the `Write` tool (never chain). Frontmatter `git_sha` / `git_branch` / `date` / `input`; body `## Actions` (agents dispatched, findings by severity) and `## Result`.

## Failure modes

- **Agent A reports FAIL on the `spec_role` closed set** — a copy of the set in `lazy-spec.layout-protocol.md` / `lazy-spec.lifecycle-protocol.md` / `lazy-spec.doctor/SKILL.md` dropped `decisions` → hand-edit the drifted copy back in; the three copies are independent by design (no single source of truth), so each must be checked.
- **Agent A reports FAIL on `lazy-spec.set-stage` missing the `decide promote` call** — the approve-transition integration point regressed → restore the call in `lazy-spec.set-stage/SKILL.md`'s approve-transition step.
- **Agent B reports WARN on a CLI verb not in `lazy-spec.help.md`** — a new `bin/lazycortex-specs` subcommand shipped without its help row → add a bullet to the relevant section of `commands/lazy-spec.help.md`.
