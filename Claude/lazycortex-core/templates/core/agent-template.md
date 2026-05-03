---
name: <namespace.name>
description: <when to dispatch this agent, not just what it does — coordinator reads this to decide>
tools: Read, Glob, Grep
model: inherit
---
# <Agent Title>

Single-response agent. Reads inputs, performs the scan, returns the structured report below. Does NOT call `AskUserQuestion` — agents have no user channel; the coordinator owns user interaction.

## Scope

<Files / sources this agent reads. Be explicit about globs and exclusions.>

## Checks

<One block per check. State the trigger, the severity (`INFO` / `WARN` / `FAIL` for measurement-style audits, `PASS` / `WARN` / `FAIL` for doctor-style), and the finding text.>

## Structured report (MANDATORY)

Return exactly the block defined in `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`:

```
## scan: <scan-name>

### findings
[SEVERITY] <short title> | <path>:<line>
  detail: <one line>
  fix: <one line>

### summary
PASS: <N> | WARN: <N> | FAIL: <N>
```

A partial report is a bug — fail explicitly with an error string the coordinator can surface, never return a half-rendered block.

<!--
Authoring notes (delete before saving):

- Conform to `lazy-core.agent-writing`:
  § 1 Frontmatter `name`, `description`, `tools` all required (FAIL if missing).
  § 2 Single-response model — no `AskUserQuestion` (FAIL).
  § 3 Structured-report contract for coordinator-dispatched agents.
  § 4 Multi-phase agents carry the Execution-Discipline preamble from `lazy-core.skill-writing § 1`,
      OR opt out via `execution-discipline-waiver: "<reason>"` in frontmatter.
  § 5 Tool allowlist hygiene — `tools: ["*"]` without justification is WARN.
  § 8 Register the agent's model tier in `lazy.settings.json` if that file exists.
- Filename: `<namespace.name>.md` under `.claude/agents/` or `<plugin>/agents/`.
- Logging: only if your project has a logging contract installed (e.g. `lazy-log.logging` from
  `lazycortex-log`). If so, add a `## Logging` section: ephemeral subagents do not log;
  multi-phase non-ephemeral agents log to `./.logs/claude/<namespace.name>/<UTC-timestamp>.md`
  with the contract's required frontmatter. If no logging plugin is installed, omit the section
  entirely — agents do not need to log.
-->
