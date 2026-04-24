---
iconize_icon: LiInfo
iconize_color: "#22c55e"
---
# lazycortex-core

Core skills and agents for Claude Code

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
| `lazy-core.install` | Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory. Idempotent — safe to re-run. Detects install scope automatically. |
| `lazy-core.optimize` | Optimize Claude Code context loading for the current project. Slims oversized rules files by moving reference material to agent definitions, audits global settings for project-specific leakage and moves entries to local settings. Run when startup feels slow or after adding new rules/agents. |
| `lazy-guard.allow-mcp` | Register tools of one or more MCP servers in Claude Code settings using a 3-bucket classifier — safe/reversible tools into permissions.allow (no prompt), truly destructive tools into permissions.ask (always prompt), and medium-risk tools skipped entirely so Claude Code prompts once per call and the user decides. Writes to settings.local.json (gitignored) by default to keep personal permissions out of tracked settings shared with teammates. For globally defined servers, asks whether to register at the global scope (~/.claude/settings.local.json) or per-project (./.claude/settings.local.json). Also strips redundant mcp__ entries from paired tracked settings.json after promotion. Optionally installs a SessionStart preload hook (in gitignored settings.local.json — a personal optimization, not universal enablement) that tells the agent to resolve the server's tool schemas via ToolSearch at session start — eliminates the deferred-loading round-trip that otherwise causes drift to Bash equivalents. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar. |
| `lazy-guard.check-public` | Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs. |
| `lazy-repo.mark-public` | Use when preparing a local/private repo — or a subtree inside one — to become public. Runs the full lazy-guard.check-public audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub. Accepts an optional scope argument to mark a subtree public (e.g., `claude/**`) without touching GitHub visibility. |

## Commands

| Command | Description |
|---|---|
| `lazy-core.help` | Show lazycortex-core purpose and a one-line summary of each skill it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-core.agent-writing` | Authoring contract for agents (subagents dispatched via the Agent tool). Covers frontmatter requirements, single-response execution model, reporting contract, tool-allowlist hygiene, and cross-references to the shared Execution-Discipline preamble in lazy-core.skill-writing. |
| `lazy-core.hygiene` | Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene. |
| `lazy-core.rule-writing` | Authoring contract for rule files. Mandatory frontmatter (description + paths scope OR always_loaded waiver), size budget, dot-namespace filename, no large code blocks, artifact-reference integrity, no narrative padding, plugin-vs-local scoping. |
| `lazy-core.skill-writing` | Authoring contract for skills, commands, and runnable scripts. Covers Execution-Discipline preamble, no-Optional headings, outcome vocabulary, narrative-padding ban, waiver mechanism, parallel-scan coordinator pattern, and the plugin audit-skill contract. |
| `lazy-guard.security` | Security constraints that the lazy-guard.* scanners and pre-commit hook enforce — credential safety and public-repo readiness. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-core.agent-model-router` | `Agent` | PreToolUse hook — route Agent dispatches to a configured model. |
| `lazy-guard.check-public` | `Bash`, `mcp__git__git_commit` | PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure leaks before committing to a public repo (or the public subtree of a repo). |
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
/lazy-core.doctor
/lazy-core.help
/lazy-core.install
/lazy-core.optimize
/lazy-guard.allow-mcp
/lazy-guard.check-public
/lazy-repo.mark-public
```
