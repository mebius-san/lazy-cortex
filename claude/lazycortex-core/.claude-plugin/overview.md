## Why this plugin

Claude Code configurations drift fast. Rule files bloat. `settings.json` accumulates one-off permissions. New MCP servers each demand another round of allow prompts. And if the repo ever becomes public, the secrets and internal paths nobody was looking for are the things that ship.

`lazycortex-core` is the opinionated hygiene and runtime layer for Claude Code projects. It tells you what is actually loading into context, slims what is oversized, flags what is risky before the commit, and classifies new MCP servers in one step.

It also gives you an **asynchronous team**. You dispatch a job to a named expert (designer, developer, reviewer, or your own role) and keep working in the main session; a per-repo serial daemon drains the queue in the background, each expert gets a clean working tree without contention, and you collect the result later when it is ready. Routines work the same way for periodic checks. Every other lazycortex plugin assumes this one is installed.

## Who it's for

- **Claude Code users** who want to see — and shrink — their startup context footprint.
- **Maintainers of public-facing repos** who need a deterministic pre-commit check for secrets, PII, and internal paths.
- **Teams adopting MCP** who are tired of per-tool allow prompts.
- **Plugin authors** who need a consistent rules + settings + runtime baseline across their own plugins.

## Blocks

- **install-and-audit** — Bootstrap and verify the lazycortex-core plugin in your project. Covers what `/lazy-core.install` drops (rules, authoring templates, the `lazy.settings.json` scaffold, optional expert-runtime + daemon-supervisor wizard) and the deeper checks `/lazy-core.audit`, `/lazy-core.doctor`, and `/lazy-core.optimize` perform. Plus `/lazy-core.setup`, the meta-installer that chains every enabled plugin's install in dependency order, and the non-interactive maintenance pair for cross-project rollout loops: the `lazy-core.autosetup` agent re-runs the install chain for one repo without questions, and `lazy-core.autocheckup` applies only mechanically derivable fixes from the checkup passes. Members: lazy-core.install, lazy-core.audit, lazy-core.doctor, lazy-core.optimize, lazy-core.setup, lazy-core.autosetup, lazy-core.autocheckup.
- **guardian** — Public-repo guardrails and MCP permission management. Catches secrets, PII, and internal paths before they ship; classifies new MCP servers' tools so consumers stop drowning in allow prompts. Members: lazy-repo.mark-public, lazy-guard.check-public, lazy-guard.allow-mcp.
- **runtime** — Per-repo serial daemon that drives the async team. Routines and expert jobs run in order without contending over the working tree; the recovery skill restores the daemon after a halt, and the preflight skill validates that a routine's expert is actually launchable (config + MCP servers) before it runs live. Members: lazy-routine.register, lazy-routine.unregister, lazy-runtime.recover, lazy-runtime.preflight.
- **experts** — An async team of named experts. Dispatch jobs to specialized workers, keep the main session free, and collect results later. Each expert is a role configured at install time with its own prompt and tools; the runtime daemon drains the queue without holding up the caller. Members: lazy-expert.dispatch-job, lazy-expert.collect-job, lazy-expert.cancel-job, lazy-expert.list-jobs.
- **memory** — Per-expert long-term memory under `.memory/<expert>/`, tracked in git. Persona-marked experts grow over runs: they consult notes before primary work, write new notes via `lazy-memory.write` as a side-effect of jobs, and consolidate via `kind=reflect` passes. Members: lazy-memory.write, lazy-memory.index, lazy-memory.reflect, lazy-memory.mark-persona.
- **agent-models** — Per-agent Claude model tier routing. The wizard fills in haiku/sonnet/opus tiers for every dispatchable agent in your vault; the `lazy-core.model-router` PreToolUse hook injects the configured tier on every `Agent` call so cheap-by-default works without per-agent flags. Members: lazy-core.agent-models.
- **git-coordination** — Coordinated git staging across hooks and skills via a per-repo staging lock. Inspect who currently holds the lock and break it manually when the auto-break heuristics don't apply. Members: lazy-core.git-status, lazy-core.git-unlock.
- **change-history** — Run-log housekeeping and change-history access. Classifies and prunes `.logs/claude/` run-log directories against the live skill/agent/command name set; rolls per-commit log entries into themed changelog blocks; answers "why was X changed?" / "when did we touch Y?" across `.logs/`, git log, and memory; drafts user-facing changelog bullets. Members: lazy-log.clean, lazy-log.distill, lazy-log.recall, lazy-log.timeline, lazy-log.summary, lazy-log.bullets.

## Walkthroughs

- **make-repo-public** — Make a repo public safely and keep it audited. Path: lazy-repo.mark-public (audit, fix, set `public_author`, write `.guard-waivers.json`, optional GitHub-visibility flip) → ongoing `/lazy-guard.check-public` runs (the pre-commit hook then activates automatically on every commit).
- **setup-runtime** — Bootstrap the per-repo serial daemon so the async team has an executor. Path: lazy-core.install (runtime-daemon wizard) → start the daemon (`./run.sh`) → first `/lazy-runtime.recover` if the tree halts.
- **setup-routine** — Register a custom periodic routine with the runtime daemon and remove it cleanly when no longer needed. Path: lazy-routine.register → daemon picks it up on the next cycle → lazy-routine.unregister.
- **setup-expert** — Add a named expert to your async team and dispatch your first job. Path: lazy-core.install (expert wizard) → lazy-expert.dispatch-job → lazy-expert.list-jobs → lazy-expert.collect-job.
- **add-memory-to-expert** — Opt an existing expert into the memory subsystem and run the first reflect pass. Path: lazy-memory.mark-persona → first few dispatches accumulate `.logs/claude/<expert>/` runs → lazy-memory.reflect → expert writes its first `.memory/<expert>/*.md` notes via lazy-memory.write.

## Requirements

- **Claude Code** with plugin support.
- **git** — the public-repo flow and most hooks assume a git repo.
- **Python 3** — bundled hook scripts (`lazy-guard.check-public`, `lazy-guard.settings`, `lazy-core.model-router`, `lazy-core.git-guard`) are Python.
- **GitHub CLI (`gh`)** — optional, only needed if you want `/lazy-repo.mark-public` to flip repo visibility for you.

## Quick start

1. Install the plugin (see the README's Installation section — `/plugin marketplace add` + `/plugin install`).
2. Run `/reload-plugins`.
3. Run `/lazy-core.install` inside each project (or once globally) to drop the always-loaded `lazy-core.hygiene` and `lazy-guard.security` rules, sync authoring templates, and seed `lazy.settings.json`.
4. Run `/lazy-core.audit` to see what is currently loading; run `/lazy-core.doctor` whenever the config feels off.
5. For public repos: run `/lazy-repo.mark-public` to set up `.guard-waivers.json` and opt into pre-commit scanning.
