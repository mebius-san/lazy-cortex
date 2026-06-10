---
description: Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, no-dirty-tree clause, and the optional Failure-modes section.
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

### Rule

Every skill, command, and runnable script MUST carry an `Execution discipline` preamble as its first content section — immediately after the H1 title and the opening descriptive paragraph, before any `##` phase/step heading.

### Required template

Start a new artifact from `${CLAUDE_PLUGIN_ROOT}/templates/core/skill-template.md` (or `command-template.md`) per `lazy-core.scaffold`. The preamble is pre-filled between the H1/opening paragraph and the first `##` phase heading; substitute the `<…>` placeholders, expand the canonical task list to one entry per phase, and never abbreviate the list.

### Preamble ↔ step-list sync

The canonical list inside the preamble IS the contract. If a phase/step is added or removed, the preamble list MUST be updated in the same edit. Drift between preamble list and actual step sections is a `FAIL`-severity `lazy-core.audit` finding.

### Waiver

A file may opt out by declaring a non-empty string in frontmatter:

```yaml
execution-discipline-waiver: "<concrete reason>"
```

- The value must be a concrete reason. `true` / `yes` / `""` are rejected as `FAIL`.
- Waivered files surface as `INFO` in `lazy-core.audit` — visibility, not silent skip.
- Legitimate patterns: help commands (static text); thin dispatchers where real execution is in a sibling script; pure-reference wrappers around another doc; skills invoked as sub-steps by another skill or agent (see § 1.5 — preamble would compete with the caller's step list and force an early exit).
- No blanket waivers by directory/glob. Each exemption is per-file and justified.

Agents share this waiver mechanism — see `lazy-core.agent-writing § 4`.

## 1.5 Nested skills — no preamble in sub-skill chains

A skill invoked from another skill's `Skill: ...` call OR from an agent's body is a **nested skill**. The outer caller already runs its own Execution-Discipline preamble — its step list owns orchestration. A MANDATORY numbered-steps preamble inside the nested skill competes with the caller's active mandate: the LLM's attention re-anchors to the most-recently-loaded step list, drops the outer caller's step pointer, and exits at the bottom of the nested skill's last step. The outer caller's remaining steps never execute.

### Rule

A skill invoked from another agent's body or from another skill's `Skill: ...` call MUST declare `execution-discipline-waiver:` in frontmatter (per § 1.4) with a reason naming the nested-call context, AND MUST NOT carry the canonical `## Execution discipline (MANDATORY)` H2 with a numbered "X ordered steps" list and TaskCreate requirement. Replace it with plain procedural prose under `## Process` (or equivalent).

### Top-level vs nested

- **Top-level** (preamble required): invoked by the operator via slash-command (`/spec.create-feature`, `/lazy-review.start`, …) or directly from an operator-facing session. The preamble guards the operator's intent → step mapping.
- **Nested** (preamble forbidden): invoked by another skill or agent as a sub-step in a longer chain.

A skill needing BOTH paths splits: a thin operator-facing wrapper with the preamble + a separate primitive (Python CLI subcommand preferred, or a sub-skill with the waiver) that does the mechanical work. The wrapper calls the primitive; the nested-from-agent path bypasses the wrapper.

### Why

LLM attention follows the most-recently-loaded mandatory-step-list. A nested skill's MANDATORY preamble re-anchors the calling agent's mental model to the inner skill's steps; the outer step pointer is dropped. The agent reaches the bottom of the inner step list, perceives "job done", echoes the inner skill's final status, exits. Post-sub-skill work in the outer caller (markers stamping, commits, `response.json` writes) never happens.

### Enforcement

`lazy-core.audit` flags any skill that:

1. Is referenced in a `Skill: <plugin>:<name>` call from another skill's SKILL.md OR an agent's body, AND
2. Carries a canonical `## Execution discipline (MANDATORY)` preamble.

Severity: `WARN`. The waivered variant (frontmatter `execution-discipline-waiver: "nested-from-agent — outer caller owns step discipline"`) is `INFO`.

## 2. No "Optional" in phase/step headings

No `##` or `###` heading under a phase/step MAY contain the word **Optional** (case-insensitive). Phases are mandatory for the agent to execute. A choice the *user* makes (accept/decline) belongs inside the phase via `AskUserQuestion`, never at the heading level.

A heading reading "Optional — <thing>" invites the agent to silently skip the phase. Match → `FAIL` in `lazy-core.audit`.

## 3. Outcome vocabulary per step

Every step must produce a one-word outcome the Report step can list. Examples: `installed`, `updated`, `unchanged`, `kept-local`, `skipped-per-user-choice`, `asserted`, `already-present`, `absent`, `warned`. English prose report lines are banned — the vocabulary forces the agent to think per step.

## 4. No narrative padding

A skill/command MUST NOT contain passages whose removal leaves the agent's executable instructions unchanged.

- **Banned**: incident post-mortems, version numbers cited as historical context, storytelling framing ("we got burned by…", "in a past session X…", "the user had to patch …").
- **Allowed**: failure-mode descriptions (general vulnerability — "agents reading X as Y drop the phase"), trade-off rationales ("default to gitignored because permissions are personal"), `Why:` lines that constrain discretionary decisions.
- **Removal test**: delete the passage; if executable behavior is unchanged, delete it for real.

`lazy-core.audit` Agent B greps a denylist (`\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`) and emits `WARN` on match. Heuristic — author owns the final call.

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

**Apply to:** any skill/command path that calls `Write`, `Edit`, `f.write_text`, `f.write`, or shells out to a subprocess that mutates a tracked path.

**How to comply:**

- Pair every write with `git add <path>` + `git commit -m "<short, deterministic message>" -- <path>` in the same execution. Use `core.hooksPath=/dev/null` if the artifact is itself fired by a hook chain to avoid re-entry.
- If the artifact runs in a flow that lacks a meaningful commit anchor, restructure: either gate the write so it never fires from that flow, or buffer the write into a real commit-anchored flow.
- Loop-guard hooks that auto-commit their own writes by content (e.g., a publish-status hook bails when HEAD's diff is folder-notes-only).

**Waiver mechanism:** declare `dirty-tree-waiver: "<reason>"` in frontmatter (skills/agents/commands) or as a `# dirty-tree-waiver: <reason>` comment in the file header (hooks/scripts). Audit downgrades the finding from WARN to INFO when present.

## 7. Failure modes section (optional, agent-grounding)

Skills MAY include a `## Failure modes` section near the bottom — between the last phase and any logging/safety sections. The section grounds downstream help-doc generators (when present) in documented behaviour.

Shape: a flat bullet list, one entry per documented user-visible abort or surfaced error, in the form `- **<symptom shown to user>** — <likely cause> → <fix or `lazy-<x>.<y>` skill that fixes it>.` Phrase symptoms in the user's voice ("`/lazy-core.install` aborts saying X"), not the agent's internal vocabulary.

Include when the skill has user-visible aborts; omit when no such failure modes exist (do NOT write `## Failure modes` followed by "(none)"). `lazy-core.audit` Agent B emits `INFO` (not `WARN`) when a SKILL.md body contains an explicit abort, "if X then error", or "fails when" phrase but no `## Failure modes` section.

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
- § 7 is informational: `lazy-core.audit` Agent B emits `INFO` when a SKILL.md with documented aborts lacks a `## Failure modes` section.

## Scope

- **In-scope**: runnable artifacts under `.claude/skills/**`, `.claude/commands/**`, `claude/*/skills/**`, `claude/*/commands/**`.
- **Out-of-scope**: `.claude/agents/**` (see `lazy-core.agent-writing`), `.claude/rules/*.md` (see `lazy-core.rule-writing`), `.claude/templates/`, `docs/`.
- Scripts under `.claude/hooks/` are now governed by `lazy-core.hook-writing` (which itself cross-references § 1 and § 6 here). Scripts under `.claude/skills/*/bin/` continue to inherit § 1 from their parent skill.
