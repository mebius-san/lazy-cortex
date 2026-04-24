---
description: Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing.
paths: [".claude/agents/**"]
---
# Agent Authoring

Agents are dispatched as one-shot subagents via the `Agent` tool. Their output is their return value. This rule covers what differs from skills/commands; shared rules (Execution-Discipline preamble, no-Optional, narrative padding) cross-reference `lazy-core.skill-writing`.

## 1. Frontmatter requirements (FAIL if missing)

- `name:` — dot-namespaced (`<namespace>.<name>`).
- `description:` — must state *when* to dispatch this agent, not just what it does. The coordinator reads this to decide.
- `tools:` — explicit allowlist. See § 5.

## 2. Single-response execution model

An agent's output IS its return value. The agent does not iterate with the user; the coordinator does.

- **No `AskUserQuestion` calls inside an agent** → `FAIL`. Agents have no user channel.
- **No partial reports**. The structured report must be complete, or the agent must fail explicitly with an error string the coordinator can surface.

## 3. Structured-report contract

Coordinator-dispatched agents MUST return the structured block (`## scan: <name>`, `### findings` with `[SEVERITY] title | path:line`, `### summary`) — see `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. Ad-hoc dispatches may use prose but keep severity vocabulary: `PASS/WARN/FAIL` or `INFO/WARN/FAIL`.

## 4. Execution discipline for multi-phase agents

Agents with `## Phase N` or `## Process` step sections carry the preamble from `lazy-core.skill-writing § 1` — structural-skip failure mode is identical. Single-response agents (one prompt → one reply) opt out via `execution-discipline-waiver: "<reason>"` in frontmatter (same validation rules as skills).

## 5. Tool allowlist hygiene

Minimum tools. Dispatch cost scales with surface.

- `tools: ["*"]` without justification → `WARN`.
- Tools listed but never invoked in the body → `WARN` (dead surface).

## 6. Shared rules (cross-reference, do not duplicate)

Apply identically to agents; see `lazy-core.skill-writing`: § 2 (no Optional headings), § 3 (outcome vocabulary), § 4 (no narrative padding), § 5 (coordinator pattern if the agent IS a coordinator).

## 7. Logging

Non-ephemeral agents log per `lazy-log.logging` to `./.logs/claude/<agent-name>/<timestamp>.md`. Ephemeral Explore dispatches are exempt — coordinator owns the log.

## Enforcement

`lazy-core.audit` Agent B enforces §§ 1, 2, 5 (frontmatter complete, no AskUserQuestion, tool allowlist) on `.claude/agents/*.md` and `claude/*/agents/*.md`. Preamble presence per § 4 reuses the skill-writing check.
