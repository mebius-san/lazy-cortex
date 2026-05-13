---
description: Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing.
paths:
  - ".claude/agents/**"
  - ".claude/templates/core/agent-template.md"
---
# Agent Authoring

Agents are dispatched as one-shot subagents via the `Agent` tool. Their output is their return value. This rule covers what differs from skills/commands; shared rules (Execution-Discipline preamble, no-Optional, narrative padding) cross-reference `lazy-core.skill-writing`.

**Template:** `${CLAUDE_PLUGIN_ROOT}/templates/core/agent-template.md` — start from this when creating a new agent. The template carries the single-response model contract, structured-report block, and tool-allowlist hygiene reminders; copy its body, fill placeholders, delete the trailing authoring-notes block.

## 1. Frontmatter requirements (FAIL if missing)

- `name:` — dot-namespaced (`<namespace>.<name>`).
- `description:` — must state *when* to dispatch this agent, not just what it does. The coordinator reads this to decide.
- `tools:` — explicit allowlist. See § 5.
- `model: inherit` — always set to `inherit`. This is Claude Code's native keyword meaning "use the parent's model". Actual model routing is handled by `lazy.settings.json` via the `lazy-core.model-router` hook; the frontmatter value is the fallback when no config override exists.

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

Apply identically to agents; see `lazy-core.skill-writing`: § 2 (no Optional headings), § 3 (outcome vocabulary), § 4 (no narrative padding), § 5 (coordinator pattern if the agent IS a coordinator), § 6 (no dirty working tree — applies to every agent that calls `Write`/`Edit` or shells out to a subprocess that mutates a tracked path).

## 7. Logging

Non-ephemeral agents log per `lazy-log.logging` to `./.logs/claude/<agent-name>/<timestamp>.md`. Ephemeral Explore dispatches are exempt — coordinator owns the log.

## 8. Model tier registration

When creating a new agent (under `.claude/agents/` or a plugin's `<plugin>/agents/`), the author MUST register a model tier for it in `lazy.settings.json` if any such config file exists at either scope (`./.claude/lazy.settings.json` or `~/.claude/lazy.settings.json`). Skipping registration leaves the agent inheriting whatever the harness picks, which is fine for ad-hoc tools but inconsistent for shipped artifacts.

Procedure:

1. **Pick the tier**. Consult `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json` first — if the dispatch string is in `defaults`, use that. Otherwise pick by the heuristic in `lazy-core.agent-models § Step 7` (build/audit/plan/design → opus; mechanical formatters → haiku; retrieval/synthesis → sonnet; catch-all delegators → default).
2. **Pick the scope**. Project agents (`.claude/agents/*.md`) → `./.claude/lazy.settings.json` under group `_project`. Plugin agents (`<plugin>/agents/*.md`) → follow the plugin's install scope; default global. Built-ins are seeded by `lazy-core.install`.
3. **Write the entry**. Add `"<dispatch>": "<tier>"` under the correct group in `agent_models`. Preserve all other keys.
4. **If the dispatch is now a canonical default for the ecosystem** (i.e. it's a built-in or LazyCortex plugin agent that every install should get the same tier for), also add it to `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json` so the wizard offers it as a template default to future installs.

If `lazy.settings.json` does not exist at either scope (uninstalled / opted out), this step is a WARN — record the chosen tier in the agent's PR description so a later `lazy-core.install` + `lazy-core.agent-models` run can seed it.

## Enforcement

`lazy-core.audit` Agent B enforces §§ 1, 2, 5, 8 (frontmatter complete, no AskUserQuestion, tool allowlist, model tier registered when config exists) on `.claude/agents/*.md` and `claude/*/agents/*.md`. Preamble presence per § 4 reuses the skill-writing check.

Dirty-tree heuristic (no write-without-commit) reuses the skill-writing § 6 check; agents are scanned alongside skills in the same Agent B pass.
