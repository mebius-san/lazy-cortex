---
description: "Run when the operator asks what lazycortex-core can do, which of its verbs handles a job, or what is available now that it is installed — lists this plugin's whole surface: config install / audit / doctor / slim-context / setup, the expert job runtime with its routines and per-expert memory, model-tier and LLM-provider routing, the git staging-lock verbs, the guard scans that catch secrets and PII before a repo goes public, the change-history log agents, and the ten authoring rules it ships."
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-core** — opinionated hygiene layer for Claude Code configs. Audits what's loading into context, slims oversized rules, flags secrets/PII/paths before public commits, and batches MCP tool permissions.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-core.agent-models` — interactively assign model tiers (haiku/sonnet/opus/inherit) to every dispatchable subagent missing from `lazy.settings.json`; routes each entry to its structurally-correct scope.
- `lazy-core.agent-models-seed` — dispatched by each plugin's install skill to seed that plugin's tiers from core's `default-tiers.json`; never overwrites a value you chose. Not for direct use.
- `lazy-core.audit` — read-only report of what gets loaded into context at startup, by category and size.
- `lazy-core.daemon-authoring` — author a new LLM-calling daemon or periodic process born with the rate-limit guard: routine-vs-standalone decision, `lazy-claude` wiring, launchd skeleton.
- `lazy-core.doctor` — health check across rules, agents, skills, commands, settings, memory, hooks, CLAUDE.md. Delegates to sibling audits.
- `lazy-core.git-status` — read-only: who currently holds the per-repo git staging lock, and whether the guard hook's heuristics will break it on their own.
- `lazy-core.git-unlock` — force that staging lock open when the automatic heuristics will not — typically a live holder that abandoned its window. Confirms before deleting.
- `lazy-core.install` — bootstrap the plugin into a project (or globally); copies hygiene + security rule templates. Idempotent.
- `lazy-core.iterate` — drive a do → verify → fix loop against one target until a verification pass comes back clean, with hard caps on cycles, repeated findings, and regression spirals. Also the loop every expert runs over its own output before finishing.
- `lazy-core.providers` — add, change, remove, or list the LLM endpoints an expert job can spawn against (base URL, token variable, model per tier), stored in the machine-local settings overlay; an expert's `provider` field names one.
- `lazy-core.scaffold-local` — add or drop a repo-specific `_local` template entry, so new files matching its globs start from your own template instead of a plugin's.
- `lazy-core.scaffold-sync` — dispatched by a plugin's install skill to copy that plugin's authoring templates into the consumer and upsert its registry entries. Not for direct use.
- `lazy-core.slim-context` — slim oversized rule files, move reference material to agents, fix global-vs-local settings leakage.
- `lazy-core.setup` — meta-installer that runs every enabled lazycortex plugin's install skill in dependency order. Idempotent.
- `lazy-expert.cancel-job` — cancel an expert job: stops its executor (SIGTERM, grace, then SIGKILL) and marks the bundle `CANCELLED`, keeping the directory on disk for forensics; releases the dedup key. Confirms via AskUserQuestion for non-done jobs.
- `lazy-expert.collect-job` — collect the result of a dispatched expert job; returns `{status, response}`.
- `lazy-expert.dispatch-job` — dispatch a job to a named expert queue; returns `{job_id, queue_path}`.
- `lazy-expert.list-jobs` — list expert queue jobs, optionally filtered by expert name or status.
- `lazy-guard.allow-mcp` — add all tools of one or more MCP servers to `permissions.allow` at the correct scope.
- `lazy-guard.check-public` — scan a repo (or subtree) for leaked secrets, PII, internal hostnames, hardcoded local paths. Respects `.guard-public.json`.
- `lazy-repo.mark-public` — walk a repo through the check-public audit, create a waivers file, optionally flip GitHub visibility.
- `lazy-log.clean` — interactive housekeeping for `.logs/claude/`; classifies each run-log directory against the live skill/agent/command name set, surfaces orphans and unnamed clusters, and applies merge/delete/leave per user confirmation.
- `lazy-memory.index` — rebuild the `.memory/` tag files after notes were hand-edited, moved, or drifted from what they claim. Recovery only — normal writes keep the index in sync.
- `lazy-memory.mark-persona` — give one expert memory: append the persona aspect so it keeps notes between jobs. Idempotent.
- `lazy-memory.reflect` — ask a persona-marked expert to consolidate what it has learned, folding its recent run logs into its memory notes.
- `lazy-memory.write` — the only blessed writer of `.memory/`: writes the note, regenerates the touched tag files, and commits atomically under the memory-bot identity.
- `lazy-routine.offer-protocols` — attach optional protocol references to a writer-dispatching routine; discovers the candidates and unions your picks into that routine's `protocols` list.
- `lazy-routine.register` — register a named routine in `lazy-core.runtime`; used by plugin install skills.
- `lazy-routine.unregister` — remove a named routine from `lazy-core.runtime`; protects the built-in `lazy-expert.pump`.
- `lazy-runtime.preflight` — validate that every routine-dispatched expert is launchable: static config checks plus a trivial-prompt launch probe that catches hanging or auth-blocked MCP servers, then proposes and applies confirmed fixes.
- `lazy-runtime.recover` — restart a daemon that stopped scheduling: branches on the halt reason (dirty tree, remote sync, bad routine config, closed rate-limit window), then atomically clears the halt.
- `lazy-runtime.tick` — manual daemon iteration on a checkout whose daemon is stopped: due routines in order, one named routine, or `--drain` until the queues are empty; commits like the daemon, defers the push.

**Commands** (invoke as `/<name>`):

- `lazy-core.checkup` — single entry point: runs the two read-only passes this plugin orchestrates (`lazy-core.audit`, then `lazy-core.doctor` in report-only mode, which delegates to the other installed plugins' own audits), merges findings into one per-plugin table, then prompts for the mutating fix-flow to run.
- `lazy-core.help` — this listing.

**Agents** (dispatched via `Agent(subagent_type: "lazycortex-core:<name>")`):

- `lazy-core.autosetup` — non-interactive install-chain executor for one repo (`repo=<path>`): applies derivable/recorded install steps, skips question-gated ones with a `needs-interactive` report, commits its changes. Built for cross-project rollout loops.
- `lazy-core.autocheckup` — non-interactive checkup for one repo (`repo=<path>`): runs the checkup passes read-only, applies only mechanically derivable fixes, reports everything operator-owned, commits its fixes.
- `lazy-log.bullets` — drafts user-facing changelog bullet blocks from recent distilled entries.
- `lazy-log.distill` — rolls commits in `.logs/commits.jsonl` into themed changelog entries in `.logs/changelog.md`.
- `lazy-log.recall` — searches change history across `.logs/changelog.md`, per-run log files, `.logs/commits.jsonl`, and git log; returns ranked results with git SHAs.
- `lazy-log.summary` — synthesises a multi-source narrative summary for a given topic or time range.
- `lazy-log.timeline` — produces a chronological view of changes for a date range or topic.
- `lazy-runtime.doctor` — dispatched hourly by its own routine when something looks stuck: a DEAD-marked job the pump keeps skipping, or a dirty-tree halt older than an hour. Decides retry / permanent-fail / commit on its own. Not for direct use.

**Rules** (synced into `.claude/rules/` by `/lazy-core.install`):

- `lazy-core.agent-writing` — authoring contract for agents: frontmatter, single-response execution model, reporting contract, tool-allowlist hygiene.
- `lazy-core.git` — protects the shared git index: pathspec commit discipline and the staging-window mutex, both enforced by the `lazy-core.git-guard` hook. Always loaded.
- `lazy-core.hook-writing` — authoring contract for lifecycle hooks: script discipline, trigger gating, loop guards, transactional skip, the no-dirty-tree clause.
- `lazy-core.hygiene` — project hygiene: artifact scope, dot-namespace naming, the tracked-vs-local settings split, MCP scope, path hygiene. Always loaded.
- `lazy-core.reference-writing` — authoring contract for reference docs (protocols, schemas, contracts, aspects) under `references/` at any scope.
- `lazy-core.rule-writing` — authoring contract for rule files: mandatory frontmatter, size budget, dot-namespace filename, reference integrity.
- `lazy-core.scaffold` — registry of authoring templates: read the matching template before composing any new artifact. Always loaded.
- `lazy-core.skill-writing` — authoring contract for skills and commands: Execution-Discipline preamble, outcome vocabulary, no-Optional headings, the waiver mechanism.
- `lazy-guard.security` — security posture the `lazy-guard.*` scanners and pre-commit hooks enforce: credential safety, secret blocking everywhere, public-repo readiness. Always loaded.
- `lazy-log.logging` — run-logging contract; every skill, agent, and command must log each run to `.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md`. Always loaded.

<!-- help-block:start -->
**Documentation:**

- [add-memory-to-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/add-memory-to-expert.md) — Opt an existing expert into the memory subsystem, dispatch jobs to accumulate runs, run the first reflect pass, and verify the expert's first durable notes land in .memory/.
- [make-repo-public](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/make-repo-public.md) — Step-by-step guide to making a repo public safely — audit, fix secrets, set your public author identity, create the waiver file, and flip GitHub visibility.
- [setup-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-expert.md) — Add a named expert role and dispatch your first async job — keep working while the daemon runs it, then collect the result.
- [setup-routine](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-routine.md) — Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
- [setup-runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-runtime.md) — Bootstrap the per-repo runtime daemon and know how to recover it with /lazy-runtime.recover from any of its halt reasons — dirty tree, remote sync, a repeating bot commit, a shared inbox, bad routine config, or a closed rate-limit window.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/troubleshooting.md) — Common failure modes across lazycortex-core skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/faq.md) — Non-obvious answers on install, LLM providers, the runtime daemon and experts, routines, scaffolding, git staging, and MCP permissions.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-core/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and examples.
