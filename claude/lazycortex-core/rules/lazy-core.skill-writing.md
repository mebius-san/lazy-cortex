---
description: Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, no-dirty-tree clause, the optional Failure-modes section, and the mandatory `Agent` member of a restricting `allowed-tools` list.
paths:
  - ".claude/skills/**"
  - ".claude/commands/**"
  - ".claude/templates/core/skill-template.md"
  - ".claude/templates/core/command-template.md"
---
# Skill / Command Authoring

Audience: anyone authoring a skill, command, or runnable script the main agent will execute. Applies to every runnable artifact under `.claude/skills/**`, `.claude/commands/**`, and the plugin equivalents.

This file is the single source of truth for **how to write** these artifacts. For agent-specific authoring see `lazy-core.agent-writing`; for rule files see `lazy-core.rule-writing`. Behavioral rules enforced at every run live elsewhere and are cross-referenced below — do not copy them here.

**Template:** `${CLAUDE_PLUGIN_ROOT}/templates/core/skill-template.md` — start from this when creating a new skill or command. It carries the Execution-Discipline preamble and the section skeleton; copy its body, fill placeholders, delete the trailing authoring-notes block.

## 1. Execution-Discipline preamble (MANDATORY)

### Rule

Every skill, command, and runnable script MUST carry an `Execution discipline` preamble as its first content section — immediately after the H1 title and the opening descriptive paragraph, before any `##` phase/step heading.

### Required template

Start a new artifact from `${CLAUDE_PLUGIN_ROOT}/templates/core/skill-template.md` (or `command-template.md`) per `lazy-core.scaffold`. The preamble is pre-filled; substitute the `<…>` placeholders, expand the canonical task list to one entry per phase, and never abbreviate the list.

### Preamble ↔ step-list sync

The canonical list inside the preamble IS the contract. If a phase/step is added or removed, the preamble list MUST be updated in the same edit. Drift between preamble list and actual step sections is a `FAIL`-severity `lazy-core.audit` finding.

### Waiver

A file may opt out by declaring a non-empty string in frontmatter:

```yaml
execution-discipline-waiver: "<concrete reason>"
```

- The value must be a concrete reason. `true` / `yes` / `""` are rejected as `FAIL`.
- Waivered files surface as `INFO` in `lazy-core.audit` — visibility, not silent skip.
- Legitimate patterns: help commands (static text); thin dispatchers where real execution is in a sibling script; pure-reference wrappers around another doc; skills invoked as sub-steps by another skill or agent (§ 1.5).
- No blanket waivers by directory/glob. Each exemption is per-file and justified.

Agents share this waiver mechanism — see `lazy-core.agent-writing § 4`.

## 1.5 Nested skills — no preamble in sub-skill chains

A skill invoked from another skill's `Skill: ...` call OR from an agent's body is a **nested skill**. The outer caller already runs its own Execution-Discipline preamble — its step list owns orchestration.

### Rule

A nested skill MUST declare `execution-discipline-waiver:` in frontmatter (per § 1 Waiver) with a reason naming the nested-call context, AND MUST NOT carry the canonical `## Execution discipline (MANDATORY)` H2 with a numbered "X ordered steps" list and TaskCreate requirement. Replace it with plain procedural prose under `## Process` (or equivalent).

### Top-level vs nested

- **Top-level** (preamble required): invoked by the operator via slash-command (`/lazy-spec.create-feature`, `/lazy-review.start`, …) or directly from an operator-facing session. The preamble guards the operator's intent → step mapping.
- **Nested** (preamble forbidden): invoked by another skill or agent as a sub-step in a longer chain.

A skill needing BOTH paths splits: a thin operator-facing wrapper with the preamble + a separate primitive (Python CLI subcommand preferred, or a sub-skill with the waiver) that does the mechanical work. The wrapper calls the primitive; the nested-from-agent path bypasses the wrapper.

### Why

LLM attention re-anchors to the most-recently-loaded mandatory step list. A nested skill's MANDATORY preamble drops the outer caller's step pointer: the agent reaches the bottom of the inner list, perceives "job done", echoes the inner skill's final status, and exits — post-sub-skill work in the outer caller (marker stamping, commits, `response.json` writes) never happens.

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

Full contract (dispatch rules, structured-report shape, coordinator responsibilities): `claude/lazycortex-core/references/lazy-core.parallel-scan.md` — read it before authoring any coordinator skill. Summary:

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
- If the artifact runs in a flow that lacks a meaningful commit anchor, restructure: gate the write so it never fires from that flow, or buffer the write into a real commit-anchored flow.
- Loop-guard hooks that auto-commit their own writes by content (e.g., a publish-status hook bails when HEAD's diff is folder-notes-only).

**Waiver mechanism:** declare `dirty-tree-waiver: "<reason>"` in frontmatter (skills/agents/commands) or as a `# dirty-tree-waiver: <reason>` comment in the file header (hooks/scripts). Audit downgrades the finding from WARN to INFO when present.

## 7. Failure modes section (optional, agent-grounding)

Skills MAY include a `## Failure modes` section near the bottom — between the last phase and any logging/safety sections. It grounds downstream help-doc generators (when present) in documented behaviour.

Shape: a flat bullet list, one entry per documented user-visible abort or surfaced error, in the form `- **<symptom shown to user>** — <likely cause> → <fix or `lazy-<x>.<y>` skill that fixes it>.` Phrase symptoms in the user's voice ("`/lazy-core.install` aborts saying X"), not the agent's internal vocabulary.

Include when the skill has user-visible aborts; omit when none exist (do NOT write `## Failure modes` followed by "(none)"). `lazy-core.audit` Agent B emits `INFO` (not `WARN`) when a SKILL.md body contains an explicit abort, "if X then error", or "fails when" phrase but no `## Failure modes` section.

## 8. `description:` states WHEN to invoke

`description:` is the routing table — Claude Code matches the user's request against it to decide what to invoke, and nothing else about the skill is visible at that moment. A description spent on internals ("thin dispatcher", "wraps `foo.bar()`", a list of what the skill prints) gives the router nothing to match on, so the skill never fires and the model does the work by hand instead.

The description **opens** with the invocation condition, in one of three shapes: `Use when <request or situation>` (user-summoned), `Dispatched by /<skill>; not for direct use.` (single caller), `Run when the operator asks to <verb>.` (slash-invoked utility). Mechanism follows only when it disambiguates from a sibling whose trigger overlaps.

A restated purpose (`Use to resolve a dependency`), a condition that cannot be evaluated without already doing the work, and a feature list of the skill's own output are **not** triggers.

Shapes, anti-patterns, worked rewrites, and the judging procedure: `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md` — read it before authoring or auditing a description. Agents follow the same requirement, see `lazy-core.agent-writing § 1`.

## 9. `allowed-tools` — `Agent` is mandatory when the field is used

When a skill declares a restricting `allowed-tools:` frontmatter field, `Agent` MUST be a member of the list (operator decision, 2026-08-12) — sub-dispatching a subagent is a supported design for any skill, not a capability to opt into per-case. A skill with NO `allowed-tools:` field is untouched — it inherits the caller's tools and needs no edit.

## 10. Research-marker convention (search/pull skills)

A **research skill** is any skill that exposes a mode whose contract is to return a bounded knowledge slice on demand — given a question or a path, hand back the matched slice of an existing map, tree, dictionary, or index, never the whole document (`lazy-wiki.structure`'s `query [<path>]` mode is the canonical shape). A skill that only ever writes or rebuilds, with no such query mode, does not qualify; one mixing a rebuild mode and a query mode qualifies on the strength of its query mode alone.

### Marker

Every research skill carries the discipline in two places, both mandatory together:

- Frontmatter: `research: true`.
- `description:`: the word "research" appears in the trigger sentence, so the marker is visible in the skill listing a consuming agent already sees — no extra `Read` needed to spot a candidate.

### Discovery, not enumeration

Nothing that consumes research skills — an aspect, a rule, another skill's body — may hardcode the current set by name; the set grows and a hardcoded list goes stale the day after the next one lands. Every consumer discovers the live set the same way. Primary, portable to any executor: spot the word "research" in a skill's `description:` in the ambient skill listing every session already carries. Secondary, dev-vault verification: `Glob` `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md`, and `~/.claude/plugins/cache/**/skills/*/SKILL.md` (installed plugins — the first two globs alone miss them), `Grep` each frontmatter for `research: true`. Globs alone are not portable to a consumer session, which never sees the dev-vault tree — the skill listing is the one route every executor has.

### Obligation

Marking a skill `research: true` without also documenting a query-mode contract (an invocation shape that returns a bounded slice, not the whole tree) is a broken marker — it tells a consumer "ask me a question" with no way to actually ask one narrowly.

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
- § 8: `lazy-core.audit` Agent B judges each `description:` against the three trigger shapes and emits `WARN` on a mechanism-only one, across skills, agents, **and commands** — a command is routed by its description exactly as a skill is. Judgement, not a grep: a description may phrase its trigger in its own words. A missing `description:` is `FAIL`.
- § 9: `lazy-core.audit` Agent B flags `allowed-tools:` missing `Agent` as `WARN`. A file with no `allowed-tools:` field is out of scope for this check.
- § 10: `lazy-core.audit` Agent B judges each skill's description/body against the research-marker convention — search/pull-shaped without the marker, or marker present without a documented query contract, both `WARN`.

## Scope

- **In-scope**: runnable artifacts under `.claude/skills/**`, `.claude/commands/**`, `claude/*/skills/**`, `claude/*/commands/**`.
- **Out-of-scope**: `.claude/agents/**` (see `lazy-core.agent-writing`), `.claude/rules/*.md` (see `lazy-core.rule-writing`), `.claude/templates/`, `docs/`.
- Scripts under `.claude/hooks/` are governed by `lazy-core.hook-writing` (which cross-references § 1 and § 6 here). Scripts under `.claude/skills/*/bin/` inherit § 1 from their parent skill.
