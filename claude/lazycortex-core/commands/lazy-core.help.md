---
description: Show lazycortex-core purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
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
- `lazy-log.clean` — interactive housekeeping for `.logs/claude/`; classifies each run-log directory against the live skill/agent/command name set, surfaces orphans and unnamed clusters, and applies merge/delete/leave per user confirmation.
- `lazy-routine.register` — register a named routine in `lazy-core.runtime`; used by plugin install skills.
- `lazy-routine.unregister` — remove a named routine from `lazy-core.runtime`; protects the built-in `expert-pump`.

**Commands** (invoke as `/<name>`):

- `lazy-core.checkup` — single entry point: runs every read-only audit/doctor (consumer + author trios), merges findings into one per-plugin table, then prompts for the mutating fix-flow to run.
- `lazy-core.help` — this listing.

**Agents** (dispatched via `Agent(subagent_type: "lazycortex-core:<name>")`):

- `lazy-log.bullets` — drafts user-facing changelog bullet blocks from recent distilled entries.
- `lazy-log.distill` — rolls commits in `.logs/commits.jsonl` into themed changelog entries in `.logs/changelog.md`.
- `lazy-log.recall` — searches change history across `.logs/changelog.md`, per-run log files, `.logs/commits.jsonl`, and git log; returns ranked results with git SHAs.
- `lazy-log.summary` — synthesises a multi-source narrative summary for a given topic or time range.
- `lazy-log.timeline` — produces a chronological view of changes for a date range or topic.

**Rule:**

- `lazy-log.logging` — run-logging contract; every skill, agent, and command must log each run to `.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md`.

<!-- help-block:start -->
**Documentation:**

- [agent-models](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/agent-models.md) — Assign haiku/sonnet/opus tiers to every agent in your vault and let the model-router hook route each dispatch automatically.
- [change-history](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/change-history.md) — Run-log housekeeping and change-history access — clean up orphaned log directories, distill commits into themed prose, and ask "why was X changed?" across every source at once.
- [experts](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/experts.md) — Dispatch jobs to named expert workers, keep the main session free, and collect results when the daemon finishes them.
- [git-coordination](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/git-coordination.md) — Inspect and manually break the per-repo staging lock that prevents hooks and skills from stomping each other's git index changes.
- [guardian](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/guardian.md) — Catch secrets, PII, and internal paths before they reach a public repo; stop per-tool allow prompts for new MCP servers in one step.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/install-and-audit.md) — Bootstrap and verify lazycortex-core — the shared scaffolding layer every other plugin depends on.
- [memory](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/memory.md) — Per-expert long-term memory tracked in git — experts consult notes before primary work, write new notes as a side-effect of jobs, and consolidate via reflect passes.
- [runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/runtime.md) — Register, unregister, and recover routines in the per-repo serial daemon — five routine types keep the async team running in order; the recovery skill handles both dirty-tree and remote-sync halts.
- [add-memory-to-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/add-memory-to-expert.md) — Opt an existing expert into the memory subsystem, dispatch jobs to accumulate runs, run the first reflect pass, and verify the expert's first durable notes land in .memory/.
- [make-repo-public](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/make-repo-public.md) — Step-by-step guide to making a repo public safely — audit, fix secrets, set your public author identity, create the waiver file, and flip GitHub visibility.
- [setup-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-expert.md) — Add a named expert role and dispatch your first async job — keep working while the daemon runs it, then collect the result.
- [setup-routine](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-routine.md) — Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
- [setup-runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-runtime.md) — Bootstrap the per-repo serial daemon so the async expert team has an executor — install wizard, start the daemon, then unblock it with /lazy-runtime.recover if the working tree halts.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/troubleshooting.md) — Common failure modes across lazycortex-core skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/faq.md) — Answers to non-obvious questions about skill selection, upgrade flows, settings placement, plugin composition, agent routing, MCP scope decisions, the expert runtime, memory subsystem, daemon halt recovery, and change-history access.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-core/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and examples.
