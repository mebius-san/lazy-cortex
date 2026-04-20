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
- *"Regenerate tag pages from note frontmatter."* — the `obsidian.gen-tag-pages` agent scans every `.md` file for `tags:` frontmatter and creates, keeps, or deletes tag pages under `Tags/` from a project-local template scaffolded by `/lazy-obsidian.install`.
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
| `lazy-obsidian.iconize-configure` | Wizard for editing the Iconize registry — the declarative mapping of vault paths to icons that the sync worker reconciles into Iconize's `data.json`. Adds, removes, and updates entries without hand-editing JSON. |
| `lazy-obsidian.iconize-install` | Scaffold-into-vault wizard. Copies the iconize-sync worker, registry, and config into the current vault from `templates/obsidian-iconize/`. Idempotent — safe to re-run. |
| `lazy-obsidian.iconize-sync` | Wrapper around the standalone worker at `bin/iconize_sync.py`. Applies the registry to `.obsidian/plugins/obsidian-icon-folder/data.json` — concurrent-safe (mtime guard + retry). Preserves `settings`, `rules`, and `recentlyUsedIcons`. Callable standalone or as a primitive from other skills. |
| `lazy-obsidian.install` | Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none), scaffolds the tag-page template used by the `obsidian.gen-tag-pages` agent (project scope only), and cleans up orphaned rules from previous versions. Idempotent — safe to re-run. Detects install scope automatically. Does not mutate any Obsidian vault — that's `lazy-obsidian.config`. |

## Agents

| Agent | Description |
|---|---|
| `obsidian.gen-tag-pages` | Regenerate Obsidian tag pages from `tags:` frontmatter across every `.md` file in the vault. Six-phase flow (collect → compute parent tags → inventory → diff → delete stale → create new → report). Reads its template from `.claude/templates/obsidian.tag-page-template.md` in the consumer repo (scaffolded by `lazy-obsidian.install`), substituting `{{TAG_PATH}}` and `{{SUMMARY}}`. Never overwrites existing tag pages; cleans up empty directories after stale deletions. |

## Commands

| Command | Description |
|---|---|
| `lazy-obsidian.help` | Show lazycortex-obsidian purpose and a one-line summary of each skill it ships |

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
/lazy-obsidian.iconize-configure
/lazy-obsidian.iconize-install
/lazy-obsidian.iconize-sync
/lazy-obsidian.install
```
