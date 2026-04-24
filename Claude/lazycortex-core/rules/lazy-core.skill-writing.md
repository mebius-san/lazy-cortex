---
description: Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, and the plugin audit-skill contract.
paths: [".claude/skills/**", ".claude/commands/**"]
---
# Skill / Command Authoring

Audience: anyone authoring a skill, command, or runnable script the main agent will execute. Applies to every runnable artifact under `.claude/skills/**`, `.claude/commands/**`, and the plugin equivalents.

This file is the single source of truth for **how to write** these artifacts. For agent-specific authoring see `lazy-core.agent-writing`. For how to write rule files themselves see `lazy-core.rule-writing`. Behavioral rules enforced at every run live elsewhere and are cross-referenced below — do not copy them here.

## 1. Execution-Discipline preamble (MANDATORY)

### Why

Multi-phase skills fail silently in a specific, repeatable way: the executing agent reads the steps in order, drops one, then writes a report listing only the steps it ran. Instructions were correct; the structure did not make the skip visible.

### Rule

Every skill, command, and runnable script MUST carry an `Execution discipline` preamble as its first content section — immediately after the H1 title and the opening descriptive paragraph, before any `##` phase/step heading.

### Required template

The full canonical template to copy verbatim lives at `${CLAUDE_PLUGIN_ROOT}/templates/execution-discipline-preamble.md` — `Read` it and paste the code-fenced block into your skill after the H1 and opening paragraph, before any `##` step heading. Substitute the `«…»` items; never abbreviate the step list.

Contract shape at a glance (the full template is longer; this is the "what it enforces" summary, not the thing to copy):

```
## Execution discipline (MANDATORY — read before any action)
This «skill/command» has «N» ordered steps. To make skips structurally impossible:
1. Before any other tool: `TaskCreate` one task per step (canonical titles verbatim).
2. Mark in_progress on enter, completed on exit; no-ops must emit an outcome word.
3. Never enter Report while any task is still `pending`.
4. Report lists one line per task — a missing line is a bug.
```

Rationale: a `TaskCreate` checklist makes a skip visible (the task stays `pending`); a structural Report-step contract makes a missing outcome visible even if the task list is neglected.

### Preamble ↔ step-list sync

The canonical list inside the preamble IS the contract. If a phase/step is added or removed, the preamble list MUST be updated in the same edit. Drift between preamble list and actual step sections is a `FAIL`-severity `lazy-core.audit` finding.

### Waiver

A file may opt out by declaring a non-empty string in frontmatter:

```yaml
execution-discipline-waiver: "<concrete reason>"
```

- The value must be a concrete reason. `true` / `yes` / `""` are rejected as `FAIL`.
- Waivered files surface as `INFO` in `lazy-core.audit` — visibility, not silent skip.
- Legitimate patterns: help commands (static text); thin dispatchers where real execution is in a sibling script; pure-reference wrappers around another doc.
- No blanket waivers by directory/glob. Each exemption is per-file and justified.

Agents share this waiver mechanism — see `lazy-core.agent-writing § 4`.

## 2. No "Optional" in phase/step headings

No `##` or `###` heading under a phase/step MAY contain the word **Optional** (case-insensitive). Phases are mandatory for the agent to execute. A choice the *user* makes (accept/decline) belongs inside the phase via `AskUserQuestion`, never at the heading level.

A heading reading "Optional — <thing>" invites the agent to silently skip the phase. Match → `FAIL` in `lazy-core.audit`.

## 3. Outcome vocabulary per step

Every step must produce a one-word outcome the Report step can list. Examples: `installed`, `updated`, `unchanged`, `kept-local`, `skipped-per-user-choice`, `asserted`, `already-present`, `absent`, `warned`. English prose report lines are banned — the vocabulary forces the agent to think per step.

## 4. No narrative padding

A skill/command MUST NOT contain passages whose removal leaves the agent's executable instructions unchanged.

- **Banned**: incident post-mortems, version numbers cited as historical context, "we got burned by…", "in a past session X…", "the user had to patch …", storytelling framing.
- **Allowed**: failure-mode descriptions (general vulnerability — "agents reading X as Y drop the phase"), trade-off rationales ("default to gitignored because permissions are personal"), `Why:` lines that constrain discretionary decisions.
- **Removal test**: delete the passage; if executable behavior is unchanged, the passage was padding — delete it for real.

`lazy-core.audit` Agent B greps a short denylist (`\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`) and emits `WARN` on match. Heuristic, not structural — the author owns the final call.

## 5. Parallel-Scan coordinator pattern

Skills that do ≥ 3 independent scan blocks before the first user interaction MUST be thin coordinators that dispatch parallel **Explore** subagents.

Full contract (dispatch rules, structured-report shape, coordinator responsibilities) lives in `claude/lazycortex-core/references/lazy-core.parallel-scan.md`. Read it before authoring any coordinator skill.

Summary:

- Dispatch all agents in a **single assistant message**, cap at 4.
- Use `subagent_type: "Explore"`, `mode: "dontAsk"` (read-only).
- Each agent returns the structured block (`## scan: …`, `### findings` with `[SEVERITY] title | path:line`, `### summary`).
- Severity vocabulary: `PASS / WARN / FAIL` (doctor-family) or `INFO / WARN / FAIL` (audits that only measure + flag).
- Coordinator owns Write/Edit, waivers, and the log write. Agents are ephemeral and do not log.

## 6. Plugin audit skill contract

### The rule

Every plugin in `claude/<plugin>/` ships a `<namespace>.audit` skill — one per namespace the plugin owns. Location: `claude/<plugin>/skills/<namespace>.audit/SKILL.md`. Guard uses `check-public` for historical reasons; new plugins name theirs `<namespace>.audit`.

No `<namespace>.doctor` — doctor-level orchestration (waivers, currency, fix/waive loop) is `lazy-core.doctor`'s single entry point. A plugin that ships its own doctor fragments the "check everything" command and is a `lazy-core.doctor` finding.

### Minimum contract

1. **Semantic rule-file verification** — if the plugin ships `claude/<plugin>/rules/*.md`, the audit must confirm each rule's body still encodes the invariants the plugin relies on. A generic "frontmatter exists" check is not enough — `lazy-core.doctor` already covers that.
2. **Cross-artifact consistency** — per-skill / per-agent / per-command conventions the rule implies (log paths, timestamp formats, forbidden idioms) must be cross-checked against current file state.
3. **Read-first** — collect findings, present a report, then ask which to fix. Never auto-fix without confirmation.
4. **Severity**: `PASS` / `WARN` / `FAIL` (plus `INFO` for transient status). Match `lazy-core.doctor`'s glossary so merged reports stay coherent.
5. **Coordinator pattern** if scanning > 1 artifact class (skills + agents + commands) — see § 5.
6. **Logging** — obey `lazy-log.logging`: `./.logs/claude/<namespace>.audit/YYYY-MM-DD_HH-MM-SS.md` per run.

### Doctor delegation

`lazy-core.doctor` Phase 3 delegates by hardcoded list (availability + run-condition probe). When adding a plugin audit, register it there: availability = plugin in `~/.claude/plugins/installed_plugins.json`; run condition = opt-in gate if one exists. Discovery-based delegation (glob for `<namespace>.audit`) is a future refactor — keep the hardcoded list in sync.

## Cross-referenced contracts (not copied here)

- `lazy-core.agent-writing` — agent-specific authoring (single-response model, tool allowlist, structured-report contract).
- `lazy-core.rule-writing` — rule-file authoring (mandatory frontmatter, scope, size budget).
- `lazy-log.logging` — every skill/agent/command logs to `./.logs/claude/<name>/…`.
- `lazy-core.hygiene` — scope, naming (dot-namespace), settings split, MCP scope, path hygiene.
- `lazy-guard.security` — public-repo credential/PII rules.

## Enforcement

- `lazy-core.audit` Agent B enforces §§ 1–4 (preamble presence, no-Optional, narrative-padding heuristic). Absent preamble and "Optional" in heading are `FAIL`; narrative-padding denylist match is `WARN`.
- `lazy-core.doctor` surfaces these findings in Phase 3 and prompts the user to fix or waive.
- § 6 is an author-side contract — `lazy-core.doctor` flags plugin-structure violations (missing `<namespace>.audit`, shipped `<namespace>.doctor`, non-compliant install skills) in its plugin-structure pass.

## Scope

- **In-scope**: runnable artifacts under `.claude/skills/**`, `.claude/commands/**`, `claude/*/skills/**`, `claude/*/commands/**`.
- **Out-of-scope**: `.claude/agents/**` (see `lazy-core.agent-writing`), `.claude/rules/*.md` (see `lazy-core.rule-writing`), `.claude/templates/`, `docs/`.
- Scripts under `.claude/hooks/` and `.claude/skills/*/bin/` are a future refinement of § 1.
