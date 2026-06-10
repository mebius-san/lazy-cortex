---
iconize_icon: LiInfo
iconize_color: "#fde68a"
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

- **install-and-audit** — Bootstrap and verify the lazycortex-core plugin in your project. Covers what `/lazy-core.install` drops (rules, authoring templates, the `lazy.settings.json` scaffold, optional expert-runtime + daemon-supervisor wizard) and the deeper checks `/lazy-core.audit`, `/lazy-core.doctor`, and `/lazy-core.optimize` perform. Plus `/lazy-core.setup`, the meta-installer that chains every enabled plugin's install in dependency order. Members: lazy-core.install, lazy-core.audit, lazy-core.doctor, lazy-core.optimize, lazy-core.setup.
- **guardian** — Public-repo guardrails and MCP permission management. Catches secrets, PII, and internal paths before they ship; classifies new MCP servers' tools so consumers stop drowning in allow prompts. Members: lazy-repo.mark-public, lazy-guard.check-public, lazy-guard.allow-mcp.
- **runtime** — Per-repo serial daemon that drives the async team. Routines and expert jobs run in order without contending over the working tree; the recovery skill restores the daemon after a halt. Members: lazy-routine.register, lazy-routine.unregister, lazy-runtime.recover.
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

1. Enable the plugin in `~/.claude/settings.json` (see the README for the marketplace + `enabledPlugins` block).
2. Restart Claude Code.
3. Run `/lazy-core.install` inside each project (or once globally) to drop the always-loaded `lazy-core.hygiene` and `lazy-guard.security` rules, sync authoring templates, and seed `lazy.settings.json`.
4. Run `/lazy-core.audit` to see what is currently loading; run `/lazy-core.doctor` whenever the config feels off.
5. For public repos: run `/lazy-repo.mark-public` to set up `.guard-waivers.json` and opt into pre-commit scanning.

## Skills

| Skill | Description |
|---|---|
| `lazy-core.agent-models` | Interactively assign model tiers (haiku/sonnet/opus/default) to every dispatchable subagent missing from `lazy.settings.json`. Auto-routes each entry to its structurally-correct scope: `_user.*` → global file, `_project.*` → project file, `_builtin.*` → global (override with `--scope=project\|global`). Cheap, standalone, idempotent — safe to re-run. Invoked directly or by `lazy-core.optimize` Phase 7. |
| `lazy-core.audit` | Quick read-only audit of what gets loaded into conversation context at startup plus skill-writing, agent-writing, rule-writing, and logging compliance. Shows sizes, loading behavior, optimization opportunities, Execution-Discipline preamble presence, no-Optional headings, narrative-padding heuristics, rule-file frontmatter/size/code-block/scope enforcement, and logging-rule installation state. No changes made. |
| `lazy-core.doctor` | Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, checks that installed plugins are at the latest marketplace version, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off. |
| `lazy-core.git-status` | Read-only inspect of the lazy-core.git staging lock. Prints holder, age, liveness, and whether the lock is currently breakable. No state mutation. |
| `lazy-core.git-unlock` | Manually break the lazy-core.git staging lock. Asks before acting (AskUserQuestion). Use only when /lazy-core.git-status shows a lock that the hook's break-the-lock heuristics will not auto-break. |
| `lazy-core.install` | Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, syncs authoring templates into `.claude/templates/core/`, bootstraps the scaffold registry, seeds runtime defaults, registers experts (always — they are dispatch-routing config, not daemon-only), and — behind two remembered gates (project-level `daemon.enabled`, per-checkout `daemon.run_here`) — sets up the daemon routines + supervisor. Idempotent and quiet on re-run — every decision is persisted and never re-asked; an enabled plugin installs its whole surface. Detects install scope automatically. |
| `lazy-core.optimize` | Optimize Claude Code context loading for the current project. Slims oversized rules files by moving reference material to agent definitions, audits global settings for project-specific leakage and moves entries to local settings. Run when startup feels slow or after adding new rules/agents. |
| `lazy-core.scaffold-local` | Manage `_local` scaffold entries in the consumer repo: add a new repo-specific template type (group + kind + globs) or remove an existing one. Safe path to author `_local` entries without hand-editing the fragile registry YAML. |
| `lazy-core.scaffold-sync` | Install-time helper: copies a plugin's authoring templates into the consumer's `.claude/templates/<group>/` directories and upserts the corresponding scaffold-registry entries. Invoked by a plugin's install skill via Skill dispatch. |
| `lazy-core.setup` | Meta-installer that runs every applicable plugin install + post-install configurator for the current project. Discovers `<namespace>.install` skills in enabled plugins and any skill carrying `lazy_setup_phase:` frontmatter, builds an ordered plan, runs each child, and reports results. Idempotent — safe to re-run after every plugin update or on a fresh project. Use after `/plugin update`, on a fresh clone, or after enabling a new plugin. Optional `--dry-run` previews the plan without executing. |
| `lazy-expert.cancel-job` | Cancel an expert job by removing its directory. Confirms via AskUserQuestion for non-done jobs. Wraps expert_runtime.cancel_job. |
| `lazy-expert.collect-job` | Collect the result of a dispatched expert job. Wraps expert_runtime.collect_job and returns {status, response?}. |
| `lazy-expert.dispatch-job` | Dispatch a job to a named expert queue. Wraps expert_runtime.dispatch_job and returns {job_id, queue_path}. |
| `lazy-expert.list-jobs` | List expert queue jobs, optionally filtered by expert name or status. Wraps expert_runtime.list_jobs. |
| `lazy-guard.allow-mcp` | Register tools of one or more MCP servers in Claude Code settings using a 3-bucket classifier — safe/reversible tools into permissions.allow (no prompt), truly destructive tools into permissions.ask (always prompt), and medium-risk tools skipped entirely so Claude Code prompts once per call and the user decides. Writes to settings.local.json (gitignored) by default to keep personal permissions out of tracked settings shared with teammates. For globally defined servers, asks whether to register at the global scope (~/.claude/settings.local.json) or per-project (./.claude/settings.local.json). Also strips redundant mcp__ entries from paired tracked settings.json after promotion. Optionally installs a SessionStart preload hook (in gitignored settings.local.json — a personal optimization, not universal enablement) that tells the agent to resolve the server's tool schemas via ToolSearch at session start — eliminates the deferred-loading round-trip that otherwise causes drift to Bash equivalents. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar. |
| `lazy-guard.check-public` | Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs. |
| `lazy-log.clean` | Interactive housekeeping for `./.logs/claude/`. Classifies each subdirectory against the live set of canonical skills/agents/commands; offers merge / distill-to-memory / delete / leave per orphan, batched by pattern when a cluster of anonymous folders (e.g. `task-N`) would otherwise produce dozens of prompts. Read-first — no folder is touched until the user has approved every action. |
| `lazy-memory.index` | Operator / audit-side rebuild of `.memory/.tags/` and every `.memory/<expert>/.tags/` from current notes' frontmatter. Recovery tool — `lazy-memory.write` keeps tag files in sync atomically; this skill exists for hand-edited memory trees and drift recovery. |
| `lazy-memory.mark-persona` | Opt one expert into the memory subsystem by appending `lazycortex-core:lazy-memory.persona-aspect` to its `aspects[]` in `lazy.settings.json[experts][<expert>]`. Idempotent — re-running on an already-marked expert is a no-op. |
| `lazy-memory.reflect` | Dispatch a single `kind=reflect` job for one persona-marked expert. The expert reviews recent `.logs/claude/<self>/*.md` runs + current `.memory/<self>/*.md` and consolidates via `lazy-memory.write`. Refuses non-persona-marked experts. |
| `lazy-memory.write` | Atomic memory-note writer for persona-marked experts. Writes one note under `.memory/<expert>/`, regenerates touched `.tags/` files (local + global), optionally drops consolidated log files, then commits the change atomically under the memory-bot identity (`memory.<expert>`). The only blessed writer of .memory/. |
| `lazy-repo.mark-public` | Use when preparing a local/private repo — or a subtree inside one — to become public. Runs the full lazy-guard.check-public audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub. Accepts an optional scope argument to mark a subtree public (e.g., `claude/**`) without touching GitHub visibility. |
| `lazy-routine.register` | Register a named routine in lazy.settings.json. Type-aware wizard (subprocess / inbox / schedule / git / md-scan). Wraps expert_runtime.register_routine with closed-set validation. Used by plugin install skills. |
| `lazy-routine.unregister` | Remove a named routine from lazy.settings.json. Wraps expert_runtime.unregister_routine. Protects the built-in lazy-expert.pump routine. |
| `lazy-runtime.recover` | Recover the lazycortex-core runtime daemon from a halt — either a working-tree halt (uncommitted_changes) or a remote-sync halt (git_pull_diverged, git_push_failed, git_remote_unavailable). Branches on the halt reason: walks the operator through dirt cleanup for tree halts, or through manual repair guidance for remote-sync halts. Atomically clears the daemon_halted block from state.json once the precondition holds. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agent-models](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/agent-models.md) — Assign haiku/sonnet/opus tiers to every agent in your vault and let the model-router hook route each dispatch automatically.
- [change-history](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/change-history.md) — Run-log housekeeping and change-history access — clean up orphaned log directories, distill commits into themed prose, and ask "why was X changed?" across every source at once.
- [experts](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/experts.md) — Dispatch jobs to named expert workers, keep the main session free, and collect results when the daemon finishes them.
- [git-coordination](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/git-coordination.md) — Inspect and manually break the per-repo staging lock that prevents concurrent Claude Code sessions from corrupting each other's git index changes.
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
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/help/faq.md) — Answers to non-obvious questions about skill selection, upgrade flows, settings placement, plugin composition, agent routing, MCP scope decisions, the expert runtime, memory subsystem, routine types, git coordination, change-history agents, and run-log housekeeping.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-core/help/`.

## Agents

| Agent | Description |
|---|---|
| `lazy-log.bullets` | Convert one plugin's commit range into a user-facing CHANGELOG release block. Reads commits via git, drops internal-only commits by Conventional-commits type, rewrites the rest as outcome-led bullets grouped by scope, and returns the rendered `### <version> — <date> UTC` block ready to prepend to CHANGELOG.public.md. Dispatch from any release-drafting flow that needs commit-subjects → user-bullets translation. |
| `lazy-log.distill` | Convert raw commit entries from .logs/commits.jsonl into themed functional prose in ./.logs/changelog.md. Output is theme-first (## <theme>) with one paragraph per day (### YYYY-MM-DD); same-day re-runs rewrite today's paragraph in place; touched theme blocks bump to the top. Throttled to once per 4h via mtime(.logs/changelog.md). Invoke after meaningful commits (see lazy-log.logging rule) or on demand. |
| `lazy-log.recall` | Search all change-history sources (run logs, changelog, raw commit log, git history, memory) for a query. Returns ranked matches with git SHAs so the user can jump to the actual commit. Use when the user asks 'why was X changed?' or 'when did we change Y?' |
| `lazy-log.summary` | Synthesize a multi-paragraph summary of all changes related to a topic across time (not chronological). Use when the user wants to understand 'the whole story' of a feature, refactor, or area of the codebase. |
| `lazy-log.timeline` | Generate a chronological timeline view of all changes matching a date range or topic. Combines changelog entries, commits, and AI run logs. Use when the user wants a 'what happened when' view. |
| `lazy-runtime.doctor` | Autonomous runtime doctor — triages DEAD expert jobs and dirty-tree halts older than 1 hour, decides retry vs permanent-fail vs commit-system-noise, applies fixes via recover.py primitives. Dispatched hourly by the `lazy-runtime.doctor` routine. Receives one context bundle per invocation; produces one response.json with the actions taken. |

## Commands

| Command | Description |
|---|---|
| `lazy-core.checkup` | One entry point that runs every read-only audit/doctor this plugin orchestrates against consumer config, merges findings into a per-plugin table, then prompts once for which mutating fix-flow to run. Read-only by default. |
| `lazy-core.help` | Show lazycortex-core purpose and a one-line summary of each skill it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-core.agent-writing.md` | Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing. |
| `lazy-core.git.md` | Serialize git staging across concurrent Claude Code sessions sharing one checkout — honor the lazy-core.git-guard hook and the lock file under .git/lazy-git.lock. |
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
| `lazy-core.git-guard` | `Bash`, `mcp__git__git_add`, `mcp__git__git_commit`, `mcp__git__git_reset`, `Stop`, `SubagentStop` | Pre/PostToolUse + Stop/SubagentStop hook: serialize git staging across Claude Code sessions and refuse to end a turn with a non-empty git index. |
| `lazy-core.model-router` | `Agent` | PreToolUse hook — route Agent dispatches to a configured model. |
| `lazy-guard.check-public` | `Bash`, `mcp__git__git_commit` | PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure leaks before they ship. |
| `lazy-guard.settings` | `Edit\|Write` | PreToolUse hook: guard Claude Code settings files against dangerous changes. |
| `lazy-log.commit-recorder` | `Bash`, `mcp__git__git_commit` | PostToolUse hook that records every successful git commit to `.logs/commits.jsonl`. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-core@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-core:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-core.agent-models
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
/lazy-routine.register
/lazy-routine.unregister
/lazy-runtime.recover
```
