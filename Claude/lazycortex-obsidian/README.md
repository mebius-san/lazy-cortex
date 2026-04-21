# lazycortex-obsidian

Obsidian vault bootstrap and configuration management for Claude Code

## Why this plugin

Obsidian vaults accumulate configuration over time — plugins, icons, themes, hotkeys, snippets — and that configuration is where most of the productivity lives. Sharing a vault baseline across machines or cloning someone else's repo usually means either committing a blanket-ignored `.obsidian/` (so the next clone has none of it) or committing the whole thing (so merge conflicts and stale plugin code ride along). Neither works.

`lazycortex-obsidian` ships a curated vault snapshot inside the plugin and a set of skills that bring a project's `.obsidian/` into alignment with it — safely, with per-plugin drift prompts, and without ever blanket-ignoring the vault. It also ships a standalone iconize-sync worker (`bin/iconize_sync.py`) with templates under `templates/obsidian-iconize/`, plus wizard skills for installing and configuring it.

## Who it's for

- **Developers who keep project docs in Obsidian** and want the same baseline (Iconize, Folder Notes, Templater, Git, Linter) on every repo they clone.
- **Teams standardizing on a vault template** who need new clones to pick up the config without manual setup.
- **AI-assisted workflows** that want the `obsidian-mcp` server wired into `.mcp.json` for every project, with `OBSIDIAN_VAULT_PATH="."` so it works on any machine.
- **Plugin authors** who need a programmatic way to paint folder/file icons via the Iconize plugin's `data.json` without running Obsidian, driven by a declarative registry the worker syncs on demand.

## Scenarios

- *"Fresh repo, no `.obsidian/` yet."* — `/lazy-obsidian.config` copies the curated snapshot, prompts for optional plugins, regenerates `community-plugins.json` in correct load order, wires `.gitignore`, sets the vault nickname, and optionally adds the MCP server.
- *"Repo already has a vault that's drifted."* — the same skill runs in audit mode, diffs each musthave plugin's `data.json` against the snapshot, and asks per plugin: overwrite / keep-local / merge-missing-keys.
- *"I want Iconize set up in this vault from scratch."* — `/lazy-obsidian.iconize-install` scaffolds the worker, registry, and config into the vault, copying from `templates/obsidian-iconize/`.
- *"I need to edit which folders get which icons."* — `/lazy-obsidian.iconize-configure` is a wizard for editing the Iconize registry (the declarative mapping of paths to icons).
- *"I need to apply the current registry to Iconize's `data.json`."* — `/lazy-obsidian.iconize-sync` wraps the worker (`bin/iconize_sync.py`) to reconcile the registry into `obsidian-icon-folder/data.json`, concurrent-safe.
- *"What does this plugin do?"* — `/lazy-obsidian.help`.

## Requirements

- **Claude Code** with plugin support.
- **Obsidian** (the app) — for the config to take effect. The skills run without Obsidian running.
- **git** — `lazy-obsidian.config` resolves the vault target via `git rev-parse --show-toplevel`.
- **Python 3** — the iconize-sync worker (`bin/iconize_sync.py`) is Python-stdlib only.
- **`jq`** — used by `lazy-obsidian.config` for merge-missing-keys and vault-nickname writes.
- **`lazycortex-core` (required)** — dependency declared in `plugin.json`; `lazy-obsidian.install` reuses the install pattern and `tool.doctor` validates the plugin surface.

## Quick start

1. Enable the plugin at **project scope** — `.obsidian/` and `.mcp.json` are repo-specific.
2. Restart Claude Code.
3. Run `/lazy-obsidian.install` once per project. The plugin ships no rules today — run the skill anyway to clean up rules from earlier versions if you're upgrading.
4. Run `/lazy-obsidian.config` to bootstrap or audit the vault. Re-run any time — it's idempotent.
5. Run `/lazy-obsidian.iconize-install` once to scaffold the Iconize worker, registry, and config into the vault (copied from `templates/obsidian-iconize/`).
6. Edit the registry via `/lazy-obsidian.iconize-configure`, then apply it with `/lazy-obsidian.iconize-sync` whenever you need to reconcile icons into `obsidian-icon-folder/data.json`.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills and agents for Claude Code

## Skills

| Skill | Description |
|---|---|
| `lazy-obsidian.audit` | Semantic audit for the lazycortex-obsidian plugin. Verifies iconize-sync artifacts stay coherent: worker version constants match template HOOK_VERSION markers, icon-map template parses and covers at least one authored-doc + one status-file matcher, protocol template's `owner_skill` points at an existing skill, hook templates carry parseable version markers. Read-first; presents findings, then asks which to fix. Delegated from `lazy-core.doctor` Phase 3. |
| `lazy-obsidian.config` | Bootstrap or audit the current project's Obsidian vault against the plugin's curated snapshot. Greenfield mode (no .obsidian/) copies the full snapshot. Audit mode (existing .obsidian/) diffs each musthave plugin's data.json and asks per-plugin whether to overwrite, keep local, or merge missing keys. Prompts for each optional plugin, regenerates community-plugins.json in correct load order, updates .gitignore with the canonical Obsidian block, and optionally wires the obsidian-mcp server into .mcp.json. Idempotent — safe to re-run. |
| `lazy-obsidian.iconize-configure` | Interactively add, edit, or remove registry entries in the local `.claude/obsidian-iconize/icon-map.json` (roles, steps, requests, or any custom registry). Re-runnable. Writes back JSON with stable formatting. Use when the resolver misses a role/step/etc. — this skill is the canonical way to seed the missing registry entry without hand-editing. |
| `lazy-obsidian.iconize-install` | Scaffold the iconize-sync system into an Obsidian vault: protocol doc, local icon-map, and pre-commit shim. Per-file wizard — asks before creating, shows diff on drift, offers deletion for orphans, strips legacy worker-written PostToolUse entries, migrates icon-map schema. Re-runnable; idempotent. Must be run from the consumer vault's git root. PostToolUse is plugin-shipped — no consumer settings.json mutation. |
| `lazy-obsidian.iconize-sync` | Resolve Obsidian file/folder icons from frontmatter and write them to the Iconize plugin's `data.json`. Driven by a local declarative icon-map (`.claude/obsidian-iconize/icon-map.json`). Subcommands: `sync`, `sync-staged`, `reconcile`, `install-hooks`, `check-versions`. Callable from `.githooks/pre-commit` and Claude Code's PostToolUse hook. |
| `lazy-obsidian.install` | Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none), scaffolds the tag-page template used by the `obsidian.gen-tag-pages` agent (project scope only), and cleans up orphaned rules from previous versions. Idempotent — safe to re-run. Detects install scope automatically. Does not mutate any Obsidian vault — that's `lazy-obsidian.config`. |

## Agents

| Agent | Description |
|---|---|
| `obsidian.gen-tag-pages` | Use this agent to generate or update Obsidian tag pages from tags used across the vault's notes. Scans all `.md` files for `tags:` frontmatter, then creates/updates/removes tag pages under `Tags/` keeping the folder hierarchy matching the tag hierarchy. Template is read from the consumer repo at `.claude/templates/obsidian.tag-page-template.md` (bootstrap via `lazy-obsidian.install`). |

## Commands

| Command | Description |
|---|---|
| `lazy-obsidian.help` | Show lazycortex-obsidian purpose and a one-line summary of each skill it ships |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `iconize_sync` | `Write\|Edit` | PostToolUse hook: after a Markdown file is written or edited, invoke `bin/iconize_sync.py sync` so Obsidian Iconize `data.json` stays in sync with the local icon-map. |

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
    "lazycortex-obsidian@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-obsidian:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-obsidian.audit
/lazy-obsidian.config
/lazy-obsidian.help
/lazy-obsidian.iconize-configure
/lazy-obsidian.iconize-install
/lazy-obsidian.iconize-sync
/lazy-obsidian.install
```
