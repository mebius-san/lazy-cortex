---
description: Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, the plugin audit-skill contract, and the plugin help-command contract.
paths:
  - ".claude/skills/**"
  - ".claude/commands/**"
  - ".claude/templates/core/skill-template.md"
  - ".claude/templates/core/command-template.md"
---
# Skill / Command Authoring

Audience: anyone authoring a skill, command, or runnable script the main agent will execute. Applies to every runnable artifact under `.claude/skills/**`, `.claude/commands/**`, and the plugin equivalents.

This file is the single source of truth for **how to write** these artifacts. For agent-specific authoring see `lazy-core.agent-writing`. For how to write rule files themselves see `lazy-core.rule-writing`. Behavioral rules enforced at every run live elsewhere and are cross-referenced below — do not copy them here.

**Template:** `${CLAUDE_PLUGIN_ROOT}/templates/core/skill-template.md` — start from this when creating a new skill or command. The template carries the Execution-Discipline preamble and the section skeleton; copy its body, fill placeholders, delete the trailing authoring-notes block.

## 1. Execution-Discipline preamble (MANDATORY)

### Why

Multi-phase skills fail silently in a specific, repeatable way: the executing agent reads the steps in order, drops one, then writes a report listing only the steps it ran. Instructions were correct; the structure did not make the skip visible.

### Rule

Every skill, command, and runnable script MUST carry an `Execution discipline` preamble as its first content section — immediately after the H1 title and the opening descriptive paragraph, before any `##` phase/step heading.

### Required template

The preamble ships pre-filled inside the full skill / command templates — `${CLAUDE_PLUGIN_ROOT}/templates/core/skill-template.md` and `${CLAUDE_PLUGIN_ROOT}/templates/core/command-template.md`. Start a new artifact from the matching template (per `lazy-core.scaffold`); the preamble block is already in place between the H1/opening paragraph and the first `##` phase heading. Substitute the `<…>` placeholders, expand the canonical task list to one entry per phase, and never abbreviate the list.

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

## 6. No dirty working tree

Skills, commands, and runnable scripts that modify a tracked file MUST commit that file in the same execution. If they cannot commit (transactional state — `MERGE_HEAD`/`CHERRY_PICK_HEAD`/rebase/bisect; ambiguous trigger; no meaningful "what just happened" anchor for the commit message) they MUST NOT write.

The "write now, leave for human to commit later" pattern is forbidden. It produces flapping working trees, races with downstream normalizers (e.g., a frontmatter rewriter that re-runs and silently re-edits the file), and offloads reconciliation work onto the user.

**Why this is a rule and not a guideline:** the alternative — auto-detect intent at write time — is unreliable, and the cost of a dirty tree is paid by the user, not the author. Forbidding the pattern at the rule level forces the author to decide up front: this artifact has a commit story, or it does not write.

**Apply this clause to:** any skill/command path that calls `Write`, `Edit`, `f.write_text`, `f.write`, or shells out to a subprocess that mutates a tracked path.

**How to comply:**

- Pair every write with `git add <path>` + `git commit -m "<short, deterministic message>" -- <path>` in the same execution. Use `core.hooksPath=/dev/null` if the artifact is itself fired by a hook chain to avoid re-entry.
- If the artifact runs in a flow that lacks a meaningful commit anchor, restructure: either gate the write so it never fires from that flow, or buffer the write into a real commit-anchored flow.
- Loop-guard hooks that auto-commit their own writes by content (e.g., `pub.status.hook._is_real_commit` bails when HEAD's diff is folder-notes-only).

**Waiver mechanism:** an artifact may opt out by declaring `dirty-tree-waiver: "<reason>"` in frontmatter (skills/agents/commands) or as a `# dirty-tree-waiver: <reason>` comment in the file header (hooks/scripts). The audit downgrades the finding from WARN to INFO when a waiver is present.

## 7. Plugin audit skill contract

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

## 8. Plugin help command contract

### The rule

Every plugin in `claude/<plugin>/` ships a `<namespace>.help` command. Location: `claude/<plugin>/commands/<namespace>.help.md`. Filename matches the plugin's *primary* namespace — the one the plugin is named after (`lazy-core` for `lazycortex-core`). Plugins that ship multiple namespaces still expose a single help command at the primary namespace; the help block lists every namespace's surface.

Same status as § 7: a plugin missing its `<namespace>.help` command is a `tool.doctor` `[FAIL]`, not a stylistic gap.

### Minimum contract

1. **Verbatim-block pattern** — frontmatter carries `description:` only. Body opens with the literal instruction `Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.` followed by a `---` separator and the help block.
2. **Help block content** — short purpose statement plus one-line bullet per skill / agent / command / rule / hook the plugin ships. Stays in sync with the plugin's actual surface: any artifact added or removed updates the help block in the same edit.
3. **Execution-discipline waiver** — help commands are static text. Declare `execution-discipline-waiver: "static help text — no executable steps"` in frontmatter (per § 1 Waiver). Surfaces as `INFO` in `lazy-core.audit`, never `FAIL`.
4. **Logging** — exempt from `lazy-log.logging` by virtue of the verbatim "Do not log this run" instruction.

### Surface reference

The full plugin-surface contract (required files, forbidden empty stubs, namespace-naming rationale) lives at `.claude/skills/tool.doctor/references/plugin-surface.md`. § 8 here is the authoring-side counterpart; the surface reference is the enforcement-side specification.

## 9. Failure modes section (optional, agent-grounding)

Skills MAY include a `## Failure modes` section near the bottom — between the last phase and any logging/safety sections. The section grounds the `pub.help-writer` agent's troubleshooting chapters in documented behaviour rather than agent-reconstructed guesses.

### Shape

The section is a flat bullet list, one entry per documented user-visible abort or surfaced error:

```markdown
## Failure modes

- **<symptom shown to user>** — <likely cause> → <fix or `lazy-<x>.<y>` skill that fixes it>.
- **<symptom>** — <cause> → <fix>.
```

Phrase symptoms in the user's voice ("`/lazy-core.install` aborts saying X"), not the agent's internal vocabulary.

### When to include the section

- **Include** when the skill has user-visible aborts, surfaced errors, or failure paths the user can encounter in normal use.
- **Omit** when no such failure modes exist; do not write `## Failure modes` followed by "(none)".

### Audit signal

`lazy-core.audit` Agent B emits `INFO` (not `WARN`) when a SKILL.md body contains an explicit abort, "if X then error", or "fails when" phrase but no `## Failure modes` section. INFO because author judgment governs whether the abort is user-visible vs. internal.

## Cross-referenced contracts (not copied here)

- `lazy-core.agent-writing` — agent-specific authoring (single-response model, tool allowlist, structured-report contract).
- `lazy-core.rule-writing` — rule-file authoring (mandatory frontmatter, scope, size budget).
- `lazy-log.logging` — every skill/agent/command logs to `./.logs/claude/<name>/…`.
- `lazy-core.hygiene` — scope, naming (dot-namespace), settings split, MCP scope, path hygiene.
- `lazy-guard.security` — public-repo credential/PII rules.

Opting a skill into `lazy-core.setup`: see `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` (`lazy_setup_phase:` frontmatter contract — read on demand, not auto-loaded).

## Enforcement

- `lazy-core.audit` Agent B enforces §§ 1–4 (preamble presence, no-Optional, narrative-padding heuristic) and § 6 (no dirty working tree — heuristic write-without-commit detection). Absent preamble and "Optional" in heading are `FAIL`; narrative-padding denylist match and unwaived dirty-tree finding are `WARN`.
- `lazy-core.doctor` surfaces these findings in Phase 3 and prompts the user to fix or waive.
- § 7 is an author-side contract — `lazy-core.doctor` flags plugin-structure violations (missing `<namespace>.audit`, shipped `<namespace>.doctor`, non-compliant install skills) in its plugin-structure pass.
- § 8 is enforced by `tool.doctor`: missing `commands/<namespace>.help.md` is `[FAIL]`; filename / namespace mismatch is `[WARN]`. See `.claude/skills/tool.doctor/references/plugin-surface.md`.
- § 9 is informational: `lazy-core.audit` Agent B emits `INFO` when a SKILL.md with documented aborts lacks a `## Failure modes` section.

## Scope

- **In-scope**: runnable artifacts under `.claude/skills/**`, `.claude/commands/**`, `claude/*/skills/**`, `claude/*/commands/**`.
- **Out-of-scope**: `.claude/agents/**` (see `lazy-core.agent-writing`), `.claude/rules/*.md` (see `lazy-core.rule-writing`), `.claude/templates/`, `docs/`.
- Scripts under `.claude/hooks/` are now governed by `lazy-core.hook-writing` (which itself cross-references § 1 and § 6 here). Scripts under `.claude/skills/*/bin/` continue to inherit § 1 from their parent skill.
