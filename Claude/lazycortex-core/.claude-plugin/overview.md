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
