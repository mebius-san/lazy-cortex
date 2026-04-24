---
description: Show lazycortex-core purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-core** — opinionated hygiene layer for Claude Code configs. Audits what's loading into context, slims oversized rules, flags secrets/PII/paths before public commits, and batches MCP tool permissions.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-core.install` — bootstrap the plugin into a project (or globally); copies hygiene + security rule templates. Idempotent.
- `lazy-core.audit` — read-only report of what gets loaded into context at startup, by category and size.
- `lazy-core.doctor` — health check across rules, agents, skills, commands, settings, memory, hooks, CLAUDE.md. Delegates to sibling audits.
- `lazy-core.optimize` — slim oversized rule files, move reference material to agents, fix global-vs-local settings leakage.
- `lazy-guard.check-public` — scan a repo (or subtree) for leaked secrets, PII, internal hostnames, hardcoded local paths. Respects `.guard-waivers.json`.
- `lazy-guard.allow-mcp` — add all tools of one or more MCP servers to `permissions.allow` at the correct scope.
- `lazy-repo.mark-public` — walk a repo through the check-public audit, create a waivers file, optionally flip GitHub visibility.

No agents. No other commands.

See `README.md` in the plugin for full scenarios and examples.
