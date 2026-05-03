---
iconize_icon: LiInfo
iconize_color: "#fde68a"
---
# lazycortex-core

Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

> **Versioning** — On upgrade from a previous public release: a **patch bump** is safe to drop in. A **minor bump** means re-run `/lazy-core.install` to pick up new rules, settings, or templates. A **major bump** means user-data migration is required — see the release notes in [`CHANGELOG.public.md`](../../CHANGELOG.public.md).

## Why this plugin

Claude Code configs drift fast. Rule files bloat. `settings.json` fills with one-off permissions. MCP servers each add another round of allow prompts. And if the repo ever goes public, secrets and internal paths that no one was looking for will be the thing that ships.

`lazycortex-core` is the opinionated hygiene layer: it tells you what's actually loading into context, slims what's oversized, flags what's risky before the commit, and makes new MCP servers permissioned in one step.

## Who it's for

- **Claude Code users** who want to see (and shrink) their startup context footprint.
- **Maintainers of public-facing repos** who need a deterministic pre-commit check for secrets, PII, and internal paths.
- **Teams adopting MCP** that are tired of per-tool allow prompts.
- **Plugin authors** who want a consistent rules-and-settings baseline across their own plugins.

## Scenarios

- *"My Claude Code feels slow to start and loads too much."* — Run `/lazy-core.audit` to see sizes by category, then `/lazy-core.optimize` to slim oversized rule files and audit global settings for project-specific leakage.
- *"I'm about to make this repo public."* — Run `/lazy-repo.mark-public` for the end-to-end flow: security audit, guided resolution, waiver file, optional GitHub visibility flip.
- *"I just added a new MCP server and I'm drowning in allow prompts."* — Run `/lazy-guard.allow-mcp` and pick the server. It appends every `mcp__<server>__<tool>` entry to `permissions.allow` in the settings file at the server's scope (global vs. project vs. project-local).
- *"Something's weird with my project config."* — Run `/lazy-core.doctor` for a full health check across rules, agents, skills, settings, memory, hooks, and CLAUDE.md. It delegates to `lazy-guard.check-public` and `lazy-log.audit` when those plugins are installed.
- *"Has anything leaked into my public repo recently?"* — The `lazy-guard.check-public` hook activates automatically in any repo with a `.guard-waivers.json` and scans staged diffs on every commit. Blocks on secrets; warns on PII and paths.
- *"I want to control which Claude model each of my agents uses to balance cost and quality."* — Run `/lazy-core.agent-models` to assign each agent a tier (haiku for routine, sonnet for default, opus for hard work). The `Agent` PreToolUse hook (`agent-model-router`) reads your config and routes every dispatch to the right model automatically.
- *"I just enabled three lazycortex plugins — how do I install them all at once?"* — Run `/lazy-core.setup`. It auto-discovers enabled lazycortex plugins, resolves their dependency order, and runs each plugin's install skill in sequence so a fresh project reaches its baseline in one command.
- *"I asked Claude to create a new rule (or skill, or agent) and it started from a template, not a blank file."* — That's the `lazy-core.scaffold` rule (always-loaded) plus the `lazy-core.skill-writing`, `lazy-core.rule-writing`, and `lazy-core.agent-writing` path-scoped rules. Together they enforce template-first authoring with the canonical Execution-Discipline preamble, mandatory frontmatter, and outcome vocabulary baked in — so every new artifact is structurally sound on the first edit.
- *"Why does Claude refuse to add this to my global `~/.claude/`?"* / *"Why is my new skill named with a dot?"* — That's the `lazy-core.hygiene` rule (always-loaded). It enforces project-local default scope, dot-namespace naming for all artifacts, the split between tracked `settings.json` (enablement) and gitignored `settings.local.json` (permissions), and narrowest-scope MCP placement.
- *"How does the public-repo flow know what counts as a leak?"* — The `lazy-guard.security` rule (always-loaded) defines the FAIL-vs-WARN taxonomy (secrets always FAIL; PII, infrastructure literals, and local paths WARN with waivers), the `.guard-waivers.json` schema (including `public_scopes` and `public_author`), and the per-machine credential-isolation rules. It backs `/lazy-repo.mark-public` and the `lazy-guard.check-public` hook.
- *"I want to offload a long-running task to a Claude agent without hitting the subagent nesting limit."* — Run `/lazy-core.install` inside the repo. When asked whether to enable the expert runtime, answer yes. The wizard writes `run.sh`, `experts.settings.json`, and the `lazy-core.runtime` block. Start the daemon with `./run.sh`, then dispatch jobs via `/lazy-expert.dispatch-job` and collect results later with `/lazy-expert.collect-job`. See [`references/expert-protocols-contract.md`](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-core/references/expert-protocols-contract.md) for the protocol contract.
- *"I dispatched an expert job — how do I get the result?"* — Run `/lazy-expert.dispatch-job` with `kind`, `role`, and `request` fields (e.g., `{"kind": "doc-review", "role": "designer", "request": "Review docs/api.md"}`). Note the returned `job_id`. When the daemon has processed it, run `/lazy-expert.collect-job <job_id>` — status will be `done` and `response.json` will contain the result file paths.
- *"I have multiple expert jobs in flight — how do I see what's pending, running, or done?"* — Run `/lazy-expert.list-jobs` to list all jobs in the queue. Pass `expert=<name>` to filter by expert or `status=READY|IN_PROGRESS|DONE|FAILED` to narrow the view.
- *"I dispatched an expert job I no longer need — how do I stop it before the daemon picks it up?"* — Run `/lazy-expert.cancel-job <job_id>` to cancel any `READY` or `IN_PROGRESS` job. Use `/lazy-expert.list-jobs` first to confirm the `job_id` if needed.
- *"I want my plugin to run a periodic check via the runtime daemon."* — Run `/lazy-routine.register` with `name` (dot-namespaced, e.g. `acme-lint.tick`), `command` (the CLI invocation), and `interval_sec` (e.g. `300`). The routine is added to `lazy-core.runtime.routines` in `lazy.settings.json` and picked up on the daemon's next cycle. To remove it later, run `/lazy-routine.unregister acme-lint.tick`.

## Expert runtime + runtime daemon

A generic, per-repo serial runtime daemon that drains a job queue and runs registered plugin routines — without hitting Claude Code's subagent nesting limit.

**What it is.** `bin/runner` is a long-lived process that reads daemon settings and the routine registry from `lazy.settings.json[lazy-core.runtime]`, runs each registered routine in serial order per its `interval_sec`, sleeps, and repeats. One daemon per repo guarantees no two routines ever contend over the working tree or git state.

**Built-in consumer: expert-pump.** The default routine drains `.claude/experts/.jobs/` — for each `READY` job it spawns a `claude --agent <X>` process, waits for completion, and writes `response.json` + `DONE`. Any plugin can register additional routines (e.g. `lazy-review.tick`).

**New public skills (6):**
- `lazy-expert.dispatch-job` — submit a job to a named expert's queue; validates payload against the protocol contract.
- `lazy-expert.collect-job` — poll a job for its result; returns `{status, response}`.
- `lazy-expert.cancel-job` — cancel a `READY` or `IN_PROGRESS` job.
- `lazy-expert.list-jobs` — list queue jobs, optionally filtered by expert name or status.
- `lazy-routine.register` — register a named routine in `lazy-core.runtime`; used by plugin install skills.
- `lazy-routine.unregister` — remove a routine from `lazy-core.runtime`; protects the built-in `expert-pump`.

**New shipped artifacts (8):** `bin/runtime_daemon.py`, `bin/runner`, `bin/expert_runtime.py`, `bin/expert_pump.py`, `bin/lazycortex-core` (CLI dispatcher), `bin/reference_resolver.py`, `templates/runtime/com.lazycortex.runtime.plist` (launchd), `templates/runtime/lazy-core-runtime.service` (systemd).

**Consumer opt-in.** Run `/lazy-core.install` — a new wizard phase asks whether to enable the runtime daemon for the current repo. On yes, it writes `run.sh`, `experts.settings.json`, and the `lazy-core.runtime` block in `lazy.settings.json`, and adds `.jobs/` to `.gitignore`.

## Requirements

- **Claude Code** with plugin support.
- **git** — the public-repo security flow and settings hooks assume a git repo.
- **Python 3** — bundled hook scripts (`lazy-guard.check-public`, `lazy-guard.settings`) are Python.
- **GitHub CLI (`gh`)** — optional, only needed if you want `lazy-repo.mark-public` to flip repo visibility for you.

## Quick start

1. Enable the plugin in `~/.claude/settings.json` (see Installation below).
2. Restart Claude Code.
3. Run `/lazy-core.install` inside each project (or once globally) to drop the `lazy-core.hygiene` and `lazy-guard.security` rule templates into `.claude/rules/`.
4. Run `/lazy-core.audit` to see what's currently loading. Run `/lazy-core.doctor` whenever the config feels off.
5. For public repos: create an empty `.guard-waivers.json` at the repo root to opt into pre-commit scanning.

## Skills

| Skill | Description |
|---|---|
| `lazy-core.agent-models` | Interactively assign model tiers (haiku/sonnet/opus/inherit) to every dispatchable subagent missing from `lazy.settings.json`. Auto-routes each entry to its structurally-correct scope: `_user.*` → global file, `_project.*` → project file, `_builtin.*` → global (override with `--scope=project\|global`). Cheap, standalone, idempotent — safe to re-run. Invoked directly or by `lazy-core.optimize` Phase 7. |
| `lazy-core.audit` | Quick read-only audit of what gets loaded into conversation context at startup plus skill-writing, agent-writing, and rule-writing compliance. Shows sizes, loading behavior, optimization opportunities, Execution-Discipline preamble presence, no-Optional headings, narrative-padding heuristics, and rule-file frontmatter/size/code-block/scope enforcement. No changes made. |
| `lazy-core.doctor` | Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, checks that installed plugins are at the latest marketplace version, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off. |
| `lazy-core.install` | Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, syncs authoring templates into `.claude/templates/core/`, bootstraps the scaffold registry, seeds runtime defaults, and offers expert wizard and daemon supervisor setup. Idempotent — safe to re-run. Detects install scope automatically. |
| `lazy-core.optimize` | Optimize Claude Code context loading for the current project. Slims oversized rules files by moving reference material to agent definitions, audits global settings for project-specific leakage and moves entries to local settings. Run when startup feels slow or after adding new rules/agents. |
| `lazy-core.setup` | Meta-installer that runs every applicable plugin install + post-install configurator for the current project. Discovers `<namespace>.install` skills in enabled plugins and any skill carrying `lazy_setup_phase:` frontmatter, builds an ordered plan, runs each child, and reports results. Idempotent — safe to re-run after every plugin update or on a fresh project. Use after `/plugin update`, on a fresh clone, or after enabling a new plugin. Optional `--dry-run` previews the plan without executing. |
| `lazy-expert.cancel-job` | Cancel an expert job by removing its directory. Confirms via AskUserQuestion for non-done jobs. Wraps expert_runtime.cancel_job. |
| `lazy-expert.collect-job` | Collect the result of a dispatched expert job. Wraps expert_runtime.collect_job and returns {status, response?}. |
| `lazy-expert.dispatch-job` | Dispatch a job to a named expert queue. Wraps expert_runtime.dispatch_job and returns {job_id, queue_path}. |
| `lazy-expert.list-jobs` | List expert queue jobs, optionally filtered by expert name or status. Wraps expert_runtime.list_jobs. |
| `lazy-guard.allow-mcp` | Register tools of one or more MCP servers in Claude Code settings using a 3-bucket classifier — safe/reversible tools into permissions.allow (no prompt), truly destructive tools into permissions.ask (always prompt), and medium-risk tools skipped entirely so Claude Code prompts once per call and the user decides. Writes to settings.local.json (gitignored) by default to keep personal permissions out of tracked settings shared with teammates. For globally defined servers, asks whether to register at the global scope (~/.claude/settings.local.json) or per-project (./.claude/settings.local.json). Also strips redundant mcp__ entries from paired tracked settings.json after promotion. Optionally installs a SessionStart preload hook (in gitignored settings.local.json — a personal optimization, not universal enablement) that tells the agent to resolve the server's tool schemas via ToolSearch at session start — eliminates the deferred-loading round-trip that otherwise causes drift to Bash equivalents. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar. |
| `lazy-guard.check-public` | Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs. |
| `lazy-repo.mark-public` | Use when preparing a local/private repo — or a subtree inside one — to become public. Runs the full lazy-guard.check-public audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub. Accepts an optional scope argument to mark a subtree public (e.g., `claude/**`) without touching GitHub visibility. |
| `lazy-routine.register` | Register a named routine in lazy.settings.json. Wraps expert_runtime.register_routine. Used by plugin install skills. |
| `lazy-routine.unregister` | Remove a named routine from lazy.settings.json. Wraps expert_runtime.unregister_routine. Protects the built-in lazy-expert.pump routine. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

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

## Commands

| Command | Description |
|---|---|
| `lazy-core.checkup` | One entry point that runs every read-only audit/doctor in this repo (consumer + author trios), merges findings into a per-plugin table, then prompts once for which mutating fix-flow to run. Read-only by default. |
| `lazy-core.help` | Show lazycortex-core purpose and a one-line summary of each skill it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-core.agent-writing` | Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing. |
| `lazy-core.hygiene` | Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene. |
| `lazy-core.rule-writing` | Authoring contract for rule files. Mandatory frontmatter (description + paths scope OR always_loaded waiver), size budget, dot-namespace filename, no large code blocks, artifact-reference integrity, no narrative padding, plugin-vs-local scoping. |
| `lazy-core.scaffold` | Registry of authoring templates for any new artifact a plugin registers. |
| `lazy-core.skill-writing` | Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, the plugin audit-skill contract, and the plugin help-command contract. |
| `lazy-guard.security` | Security constraints that the lazy-guard.* scanners and pre-commit hook enforce — credential safety and public-repo readiness. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-core.agent-model-router` | `Agent` | PreToolUse hook — route Agent dispatches to a configured model. |
| `lazy-guard.check-public` | `Bash`, `mcp__git__git_commit` | PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure leaks before committing to a public repo. |
| `lazy-guard.settings` | `Edit\|Write` | PreToolUse hook: guard Claude Code settings files against dangerous changes. |

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
/lazy-core.checkup
/lazy-core.doctor
/lazy-core.help
/lazy-core.install
/lazy-core.optimize
/lazy-core.setup
/lazy-expert.cancel-job
/lazy-expert.collect-job
/lazy-expert.dispatch-job
/lazy-expert.list-jobs
/lazy-guard.allow-mcp
/lazy-guard.check-public
/lazy-repo.mark-public
/lazy-routine.register
/lazy-routine.unregister
```
