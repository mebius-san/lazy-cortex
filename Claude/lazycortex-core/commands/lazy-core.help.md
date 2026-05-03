---
description: Show lazycortex-core purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-core** — opinionated hygiene layer for Claude Code configs. Audits what's loading into context, slims oversized rules, flags secrets/PII/paths before public commits, and batches MCP tool permissions.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-core.agent-models` — interactively assign model tiers (haiku/sonnet/opus/inherit) to every dispatchable subagent missing from `lazy.settings.json`; routes each entry to its structurally-correct scope.
- `lazy-core.audit` — read-only report of what gets loaded into context at startup, by category and size.
- `lazy-core.doctor` — health check across rules, agents, skills, commands, settings, memory, hooks, CLAUDE.md. Delegates to sibling audits.
- `lazy-core.install` — bootstrap the plugin into a project (or globally); copies hygiene + security rule templates. Idempotent.
- `lazy-core.optimize` — slim oversized rule files, move reference material to agents, fix global-vs-local settings leakage.
- `lazy-core.setup` — meta-installer that runs every enabled lazycortex plugin's install skill in dependency order. Idempotent.
- `lazy-expert.cancel-job` — cancel an expert job by removing its directory. Confirms via AskUserQuestion for non-done jobs.
- `lazy-expert.collect-job` — collect the result of a dispatched expert job; returns `{status, response}`.
- `lazy-expert.dispatch-job` — dispatch a job to a named expert queue; returns `{job_id, queue_path}`.
- `lazy-expert.list-jobs` — list expert queue jobs, optionally filtered by expert name or status.
- `lazy-guard.allow-mcp` — add all tools of one or more MCP servers to `permissions.allow` at the correct scope.
- `lazy-guard.check-public` — scan a repo (or subtree) for leaked secrets, PII, internal hostnames, hardcoded local paths. Respects `.guard-waivers.json`.
- `lazy-repo.mark-public` — walk a repo through the check-public audit, create a waivers file, optionally flip GitHub visibility.
- `lazy-routine.register` — register a named routine in `lazy-core.runtime`; used by plugin install skills.
- `lazy-routine.unregister` — remove a named routine from `lazy-core.runtime`; protects the built-in `expert-pump`.

**Commands** (invoke as `/<name>`):

- `lazy-core.checkup` — single entry point: runs every read-only audit/doctor (consumer + author trios), merges findings into one per-plugin table, then prompts for the mutating fix-flow to run.
- `lazy-core.help` — this listing.

<!-- pub.sync-readmes:help-block:start -->
**Documentation:**

- [allow-new-mcp-server](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/allow-new-mcp-server.md) — Stop allow prompts for a new MCP server in one command — lazy-guard.allow-mcp classifies and registers every tool automatically.
- [assign-agent-models](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/assign-agent-models.md) — Run /lazy-core.agent-models to assign haiku/sonnet/opus tiers to every agent, then the agent-model-router hook routes each dispatch to the right model automatically.
- [bootstrap-plugins-with-setup](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/bootstrap-plugins-with-setup.md) — Run /lazy-core.setup to install every enabled lazycortex plugin in one command — auto-discovered, dependency-ordered, idempotent.
- [cancel-expert-job](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/cancel-expert-job.md) — Run /lazy-expert.cancel-job to stop a pending or done expert job before or after the daemon completes it.
- [diagnose-project-config](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/diagnose-project-config.md) — Run /lazy-core.doctor to get a full health check across rules, agents, skills, settings, memory, hooks, and CLAUDE.md — then confirm fixes.
- [dispatch-collect-expert-job](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/dispatch-collect-expert-job.md) — Dispatch an expert job with /lazy-expert.dispatch-job, then retrieve its result with /lazy-expert.collect-job once the daemon finishes it.
- [enable-expert-runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/enable-expert-runtime.md) — Run /lazy-core.install, opt in to the expert runtime, start the daemon, then dispatch and collect long-running jobs without hitting subagent nesting limits.
- [hygiene-rule-explainer](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/hygiene-rule-explainer.md) — Explains the six clauses of lazy-core.hygiene: project-local scope, dot-namespaces, settings split, MCP scope, path hygiene, and dynamic content rules.
- [list-expert-jobs](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/list-expert-jobs.md) — Run /lazy-expert.list-jobs to see every job in the expert queue — filter by expert name or status to find what you need fast.
- [make-repo-public](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/make-repo-public.md) — Step-by-step guide to making a repo public safely — audit, fix secrets, set your public author identity, create the waiver file, and flip GitHub visibility.
- [pre-commit-leak-scan](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/pre-commit-leak-scan.md) — Run lazy-guard.check-public for ad-hoc audits and let the pre-commit hook block secrets automatically on every staged commit.
- [register-plugin-routine](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/register-plugin-routine.md) — Register a dot-namespaced routine with the runtime daemon so your plugin runs a periodic check automatically — and remove it cleanly when you no longer need it.
- [scaffold-new-artifacts](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/scaffold-new-artifacts.md) — When you ask Claude to create a new skill, rule, or agent, these always-loaded and path-scoped rules make it start from a template instead of guessing the structure.
- [slim-startup-context](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/slim-startup-context.md) — Run /lazy-core.audit to measure your startup context, then /lazy-core.optimize to slim rule files and move project-specific settings out of global config.
- [understand-leak-taxonomy](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/understand-leak-taxonomy.md) — Learn the FAIL-vs-WARN leak taxonomy, how waivers work, and what the public-repo flow checks before publishing.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/troubleshooting.md) — Common failure modes across lazycortex-core skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/faq.md) — Answers to non-obvious questions about skill selection, upgrade flows, settings placement, plugin composition, agent routing, MCP scope decisions, and the expert runtime.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-core/help/`.
<!-- pub.sync-readmes:help-block:end -->

No agents.

See `README.md` in the plugin for full scenarios and examples.
