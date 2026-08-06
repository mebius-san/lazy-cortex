---
iconize_icon: LiInfo
iconize_color: "#93c5fd"
---
# lazycortex-core

Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

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

## Skills

| Skill | Description |
|---|---|
| `lazy-core.agent-models` | Run when the operator asks which model each subagent runs on or wants to set them — after adding agents, after a fresh `/lazy-core.install`, or when an audit reports missing `agent_models` entries. Also runs as Phase 7 of `/lazy-core.optimize`. Interactive wizard over the entries install did not already seed; also prunes entries whose agent file is gone. Cheap, standalone, safe to re-run. |
| `lazy-core.agent-models-seed` | Dispatched by a plugin's `<namespace>.install` skill (core, diagram, experts, obsidian, python, review, specs, wiki) to seed that plugin's agent-model tiers into the consumer's `lazy.settings.json`; not for direct use. Tiers come from `lazycortex-core`'s `default-tiers.json`, and an operator's existing value is never overwritten. |
| `lazy-core.audit` | Run when the operator asks why sessions start heavy, what is loaded into context at startup, or whether this repo's skills / agents / rules follow the authoring and logging rules. Read-only, reports only — the sibling `/lazy-core.doctor` is the one that checks cross-artifact consistency and offers fixes. |
| `lazy-core.doctor` | Run when the operator asks whether the project config is healthy, or when something feels off — a rule or skill is not firing, plugins may be behind the marketplace, settings / agents / memory / hooks / CLAUDE.md have drifted apart. Merges its own cross-artifact scan with the installed plugins' audits and offers per-finding fixes; the sibling `/lazy-core.audit` only measures context weight and authoring compliance and never fixes. |
| `lazy-core.git-status` | Run when a git command was refused because another Claude session is staging, or the operator asks who holds the git staging lock and whether it can be broken. Read-only — `/lazy-core.git-unlock` is the one that breaks it. |
| `lazy-core.git-unlock` | Run when the operator asks to force the git staging lock open after `/lazy-core.git-status` shows a holder the hook's automatic heuristics (dead PID / other host / stale-and-idle) will not break — typically a live holder that has abandoned its staging window. Confirms before deleting the lock. |
| `lazy-core.install` | Run when the operator asks to set up lazycortex-core in a repo (or globally), or when core artifacts are missing — the plugin's rules are not in `.claude/rules/`, `lazy.settings.json` has no runtime section, `.experts/` is not initialised, or the daemon was never wired. Installs this plugin only; `/lazy-core.setup` is the one that runs every plugin's install. Idempotent and quiet on re-run — decisions are persisted and never re-asked. |
| `lazy-core.optimize` | Run when startup feels slow, the always-loaded context budget crosses its WARN threshold, a rules file has grown oversized, or a project-specific permission leaked into global settings. Unlike `lazy-core.audit`, which only reports, this one rewrites: it moves reference material out of rules into on-demand agent definitions and relocates leaked settings entries to the local scope. |
| `lazy-core.scaffold-local` | Run when the operator asks to add or drop a repo-specific template type — a `_local` scaffold entry with its own group, kind, and path globs, so new files matching those globs start from that template. Use instead of hand-editing the registry in `.claude/rules/lazy-core.scaffold.md`; plugin-shipped entries belong to `/lazy-core.scaffold-sync`. |
| `lazy-core.scaffold-sync` | Dispatched by a plugin's install skill (`lazy-core.install` Step 4, `lazy-python.install` Step 6) to copy that plugin's authoring templates into the consumer and upsert its scaffold-registry entries; not for direct use. Repo-specific `_local` entries are `/lazy-core.scaffold-local`'s business, not this skill's. |
| `lazy-core.setup` | Run after `/plugin update`, on a fresh clone, after enabling a new plugin, or whenever the operator asks to set lazycortex up in this project — the meta-installer that discovers and runs every enabled plugin's `<namespace>.install` skill plus any `lazy_setup_phase:` configurator in one ordered pass, so the operator never invokes install skills one by one. Idempotent; `--dry-run` previews the plan without executing. |
| `lazy-expert.cancel-job` | Run when the operator wants an expert job stopped — wrong expert, changed requirements, a moved source file, or a job that should not finish. Confirms, kills the executor, and marks the bundle CANCELLED; the job directory stays on disk for forensics and the dedup key is released so the same work can be re-dispatched. |
| `lazy-expert.collect-job` | Run when the operator asks for the result of an expert job already dispatched, naming the expert and job_id. Reports pending / done / deferred / failed and, when the job finished, the result file paths to read. |
| `lazy-expert.dispatch-job` | Run when a task should be handed to a named expert to run in the background instead of blocking the session — long work the operator wants queued and picked up later. Returns a job_id in seconds; the runtime daemon executes the job and `/lazy-expert.collect-job` retrieves the output. |
| `lazy-expert.list-jobs` | Run when the operator asks what the expert queue is doing — whether a job has finished, whether the daemon is busy, which experts have work outstanding, or to recover a job_id they lost. Optional filters by expert name and by status. |
| `lazy-guard.allow-mcp` | Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or asks to stop being prompted for one server's tools on every call. Classifies each tool into three buckets — safe/reversible into `permissions.allow`, truly destructive into `permissions.ask`, medium-risk into neither so Claude Code still prompts per call — and writes them to the gitignored `settings.local.json` so personal permission choices never land in tracked settings. |
| `lazy-guard.check-public` | Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs. |
| `lazy-log.clean` | Run when the operator asks to tidy `./.logs/claude/` — stray or misnamed run-log folders, clusters of anonymous `task-N` dirs, logs left behind by skills that no longer exist. Read-first and interactive: classifies every folder against the live artifact names and offers merge / distill-to-memory / delete / leave before anything is touched. |
| `lazy-memory.index` | Run when memory tag files have drifted — an audit reports a note carrying `memory/<topic>` that its tag file does not list, a global tag file points at a missing local one, or notes were hand-edited or moved. Also offered by `/lazy-core.optimize`. Recovery only: `/lazy-memory.write` keeps `.tags/` in sync on every normal write. |
| `lazy-memory.mark-persona` | Run when the operator asks to give an expert memory (let it keep notes between jobs), or when an audit reports that `.memory/<expert>/` exists but the expert is not marked persona. Appends the persona aspect to that one expert; idempotent. |
| `lazy-memory.reflect` | Run when the operator asks an expert to consolidate what it has learned — fold its recent run logs into its memory notes. Dispatches one `kind=reflect` job for that expert; refuses an expert that is not persona-marked (run `/lazy-memory.mark-persona` first). |
| `lazy-memory.write` | Invoked by a persona-marked expert whenever it records or updates a memory note (per `lazy-memory.persona-aspect`), and by the operator when merging notes by hand — the only blessed writer of `.memory/`. Direct `Write` / `Edit` under `.memory/` silently desyncs the tag index; this skill writes the note, regenerates the touched `.tags/` files, and commits atomically under the memory-bot identity. |
| `lazy-repo.mark-public` | Use when preparing a local/private repo — or a subtree inside one — to become public. Runs the full lazy-guard.check-public audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub. Accepts an optional scope argument to mark a subtree public (e.g., `claude/**`) without touching GitHub visibility. |
| `lazy-routine.offer-protocols` | Dispatched by a plugin's install / configure skill (`lazy-review.install`, `spec.install`) right after it registers a writer-dispatching routine, to offer the operator the optional protocol references that fit that routine's context; not for direct use. Only ever appends to the routine's flat `protocols` list. |
| `lazy-routine.register` | Run when the daemon should start doing something on its own — the operator asks to schedule recurring work, watch an inbox directory, react to local git HEAD, or scan markdown files by frontmatter. Also dispatched by plugin install skills (`spec.install`) to wire their own routines instead of hand-writing settings JSON. Type-aware wizard; refuses to overwrite an existing routine without `--force`. |
| `lazy-routine.unregister` | Run when the operator asks to stop a daemon routine for good, or before re-registering one with a different shape (register refuses to overwrite). Idempotent on a name that is not registered; refuses to remove the built-in `lazy-expert.pump` without `--force`. |
| `lazy-runtime.preflight` | Run before wiring a new expert or MCP server into a live routine, and when a routine's expert spawns keep timing out, die instantly, or never produce a response. Emulates each expert launch with a trivial prompt (no real work) to expose the unresolvable agent, missing aspect/protocol, bad `mcp_config` path, or MCP server that hangs at init, then proposes a concrete fix and applies it only after the operator confirms. |
| `lazy-runtime.recover` | Run when the runtime daemon has stopped scheduling — routines no longer fire, or `.runtime/state.json` carries a `daemon_halted` block. Branches on the halt reason: `uncommitted_changes` walks the operator through commit / stash / discard of the dirt a routine left behind; `git_pull_diverged` / `git_push_failed` / `git_remote_unavailable` describes the remote-sync failure and waits for the operator to repair it externally. Ends by atomically clearing the halt so the daemon resumes. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agent-models](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/agent-models.md) — Assign model tiers to every agent in your vault, prune dead entries for deleted agents, and route dispatches automatically.
- [change-history](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/change-history.md) — Run-log housekeeping and change-history access — clean up orphaned log directories, distill commits into themed prose, and ask "why was X changed?" across every source at once.
- [experts](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/experts.md) — Dispatch jobs to named expert workers, keep the main session free, and collect results — including deferred and fail-closed outcomes.
- [git-coordination](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/git-coordination.md) — Protect your repo's git index from Claude Code — pathspec-only commits by default, an optional staging lock for concurrent sessions, and the two skills to inspect and break it.
- [guardian](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/guardian.md) — Catch secrets, PII, and internal paths before they reach a public repo; stop per-tool allow prompts for new MCP servers in one step.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/install-and-audit.md) — Bootstrap and verify lazycortex-core — the shared scaffolding layer every other plugin depends on.
- [memory](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/memory.md) — Per-expert long-term memory tracked in git — experts consult notes before primary work, write new notes as a side-effect of jobs, and consolidate via reflect passes.
- [runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/runtime.md) — Register, unregister, preflight, and recover routines in the per-repo serial daemon — five routine types keep the async team running in order, with a validator that catches broken expert configs before they run live.
- [add-memory-to-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/add-memory-to-expert.md) — Opt an existing expert into the memory subsystem, dispatch jobs to accumulate runs, run the first reflect pass, and verify the expert's first durable notes land in .memory/.
- [make-repo-public](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/make-repo-public.md) — Step-by-step guide to making a repo public safely — audit, fix secrets, set your public author identity, create the waiver file, and flip GitHub visibility.
- [setup-expert](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-expert.md) — Add a named expert role and dispatch your first async job — keep working while the daemon runs it, then collect the result.
- [setup-routine](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-routine.md) — Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
- [setup-runtime](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/walkthroughs/setup-runtime.md) — Bootstrap the per-repo runtime daemon and know how to recover it with /lazy-runtime.recover if the working tree or a remote sync halts it.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/troubleshooting.md) — Common failure modes across lazycortex-core skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/faq.md) — Non-obvious answers on install/setup, audit/doctor/optimize, expert runtime, memory, routines, git staging, MCP permissions, and change-history search.

(`mebius-san` resolves from `.guard-waivers.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-core.autocheckup` | Dispatch from a cross-project rollout loop (one agent per project), or directly when ONE repo's lazycortex config should be checked and mechanically repaired with no operator in the loop. Receives `repo=<absolute path>` in the prompt. Runs the read-only checks `lazy-core.checkup` orchestrates, then applies ONLY mechanically derivable fixes (install-managed mirror regeneration, missing dirs/registrations, derived-file drift, unpinned models whose tier is in default-tiers.json, pruning agent_models entries whose plugin agent file was deleted); everything content-shaped or preference-shaped is reported, never applied. Commits its fixes in the target repo. Sibling `lazy-core.autosetup` runs the install chain instead of the checks. |
| `lazy-core.autosetup` | Dispatch from a cross-project rollout loop (one agent per project), or directly when ONE repo's lazycortex config must be brought current with no operator in the loop — e.g. after a plugin update changed what install seeds. Receives `repo=<absolute path>` in the prompt. Executes every applicable `<namespace>.install` SKILL.md against that repo under a no-questions discipline: derivable or already-recorded decisions apply, question-gated steps are skipped and reported. Commits its changes in the target repo. NOT for first-time project setup — a repo with no recorded install decisions mostly reports `needs-interactive`. Sibling `lazy-core.autocheckup` checks and repairs instead of installing. |
| `lazy-log.bullets` | Use when one plugin is being released and its CHANGELOG.public.md needs a release block drafted from a commit range — dispatched by any release-drafting flow, or directly with plugin + range + version. Renders the `### <version> — <date> UTC` block of user-visible bullets: the per-release public counterpart to lazy-log.distill's running internal changelog. |
| `lazy-log.distill` | Use after meaningful commits land (per the lazy-log.logging cadence), or when the operator asks to catch the changelog up. Rewrites ./.logs/changelog.md as themed prose from .logs/commits.jsonl, throttled to 4h unless forced — the running internal narration, not lazy-log.bullets' per-release public block and not the read-only history searches of lazy-log.recall/summary/timeline. |
| `lazy-log.recall` | Use when the user asks why or when one specific thing changed — 'why was X changed?', 'when did we switch to Y?', 'what commit removed Z?'. Searches every change-history source (changelog, run logs, commits.jsonl, git log, memory) and returns ranked individual matches with git SHAs to jump to. Pick this over `lazy-log.summary` (thematic narrative of a whole topic) and `lazy-log.timeline` (dated what-happened-when list) when the answer is a particular change to point at. |
| `lazy-log.summary` | Use when the user wants the whole story of a feature, refactor, or area — 'how did the plugin system evolve', 'catch me up on the logging skills', 'explain the auth middleware migration'. Returns multi-paragraph prose clustered by sub-theme, deliberately not by date. Pick this over `lazy-log.recall` (ranked individual matches with SHAs) and `lazy-log.timeline` (dated what-happened-when list) when the answer is an explanation rather than a list. |
| `lazy-log.timeline` | Use when the user wants what happened when — 'what changed last week', 'everything on hooks since 2026-03-01', 'walk me through the last two weeks'. Returns one date-ordered list of changes matching a date range and/or topic, merged from changelog entries, commits, and AI run logs. Pick this over `lazy-log.recall` (ranked matches for one specific change) and `lazy-log.summary` (thematic narrative, no dates) when chronology is the point. |
| `lazy-runtime.doctor` | Dispatched hourly by the `lazy-runtime.doctor` routine when something looks stuck in the lazycortex-core runtime — a DEAD-marked expert job the pump keeps skipping, or a dirty-tree halt sitting in state.json for over an hour; not for direct use. Decides retry vs permanent-fail vs commit-the-system-noise on its own and applies the fix via recover.py primitives, never asking the operator. One context bundle in, one response.json out. |

## Commands

| Command | Description |
|---|---|
| `lazy-core.checkup` | One entry point that runs every read-only audit/doctor this plugin orchestrates against consumer config, merges findings into a per-plugin table, then prompts once for which mutating fix-flow to run. Read-only by default. |
| `lazy-core.help` | Show lazycortex-core purpose and a one-line summary of each skill it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-core.agent-writing.md` | Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing. |
| `lazy-core.git.md` | Protect the shared git index — the pathspec commit discipline and the staging-window mutex, both enforced by the lazy-core.git-guard hook. |
| `lazy-core.hook-writing.md` | Authoring contract for Claude Code lifecycle hooks — PreToolUse, PostToolUse, Stop, SessionStart, etc. Covers script discipline, trigger gating, branch determinism, loop guards, transactional skip, the no-dirty-tree clause, and logging. |
| `lazy-core.hygiene.md` | Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene. |
| `lazy-core.reference-writing.md` | Authoring contract for reference docs (protocols, schemas, contracts) under references/ at any scope. |
| `lazy-core.rule-writing.md` | Authoring contract for rule files. Mandatory frontmatter (description + paths scope OR always_loaded waiver), size budget, dot-namespace filename, no large code blocks, artifact-reference integrity, no narrative padding. |
| `lazy-core.scaffold.md` | Registry of authoring templates for any new artifact a plugin registers. |
| `lazy-core.skill-writing.md` | Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, no-dirty-tree clause, and the optional Failure-modes section. |
| `lazy-guard.security.md` | Security constraints that the lazy-guard.* scanners and pre-commit hook enforce — credential safety and public-repo readiness. |
| `lazy-log.logging.md` | Logging conventions for skills, agents, and commands. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-core.git-guard` | `Bash`, `mcp__git__git_add`, `mcp__git__git_commit`, `mcp__git__git_reset`, `Stop`, `SubagentStop` | Pre/PostToolUse + Stop/SubagentStop hook guarding the shared git index against agent sessions. |
| `lazy-core.model-router` | `Agent` | PreToolUse hook — route Agent dispatches to a configured model. |
| `lazy-guard.check-public` | `Bash`, `mcp__git__git_commit` | PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure leaks before |
| `lazy-guard.settings` | `Edit\|Write` | PreToolUse hook: guard Claude Code settings files against dangerous changes. |
| `lazy-log.commit-recorder` | `Bash`, `mcp__git__git_commit` | PostToolUse hook that records every successful git commit to `.logs/commits.jsonl`. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-core@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-core:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-core.agent-models
/lazy-core.agent-models-seed
/lazy-core.audit
/lazy-core.doctor
/lazy-core.git-status
/lazy-core.git-unlock
/lazy-core.install
/lazy-core.optimize
/lazy-core.scaffold-local
/lazy-core.scaffold-sync
/lazy-core.setup
/lazy-expert.cancel-job
/lazy-expert.collect-job
/lazy-expert.dispatch-job
/lazy-expert.list-jobs
/lazy-guard.allow-mcp
/lazy-guard.check-public
/lazy-log.clean
/lazy-memory.index
/lazy-memory.mark-persona
/lazy-memory.reflect
/lazy-memory.write
/lazy-repo.mark-public
/lazy-routine.offer-protocols
/lazy-routine.register
/lazy-routine.unregister
/lazy-runtime.preflight
/lazy-runtime.recover
```
