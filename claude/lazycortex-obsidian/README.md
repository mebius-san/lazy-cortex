---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-obsidian

Obsidian vault bootstrap and configuration management for Claude Code

## Why this plugin

Obsidian vaults accumulate configuration over time — plugins, icons, themes, hotkeys, snippets — and that configuration is where most of the productivity lives. Sharing a vault baseline across machines or cloning someone else's repo usually means either committing a blanket-ignored `.obsidian/` (so the next clone has none of it) or committing the whole thing (so merge conflicts and stale plugin code ride along). Neither works.

`lazycortex-obsidian` ships a curated vault snapshot inside the plugin and a set of skills that bring a project's `.obsidian/` into alignment with it — safely, with per-plugin drift prompts, and without ever blanket-ignoring the vault. It also ships a standalone iconize-sync worker (`bin/iconize_sync.py`) with templates under `templates/iconize/`, plus wizard skills for installing and configuring it.

## Who it's for

- **Developers who keep project docs in Obsidian** and want the same baseline (Iconize, Folder Notes) on every repo they clone.
- **Teams standardizing on a vault template** who need new clones to pick up the config without manual setup.
- **AI-assisted workflows** that want the `obsidian-mcp` server wired into `.mcp.json` for every project, with `OBSIDIAN_VAULT_PATH="."` so it works on any machine.
- **Plugin authors** who need a programmatic way to paint folder/file icons by writing `iconize_icon` / `iconize_color` into note frontmatter, driven by a declarative registry the worker syncs on demand. Iconize itself paints the file-side icons live from frontmatter; the bundled `iconize-reloader` plugin bridges folder-note frontmatter into folder icons.

## Scenarios

- *"Fresh repo, new vault."* — `/lazy-obsidian.install` is the one-stop entry point: syncs plugin rules and the tag-page template, installs Dataview for tag-page rendering, and offers to chain into `/lazy-obsidian.iconize-install` so the vault reaches a usable state in a single pass.
- *"I need a single Obsidian plugin installed or refreshed."* — `/lazy-obsidian.update-plugin <id>` resolves the plugin via the Obsidian community registry, fetches `manifest.json` / `main.js` / `styles.css` from the latest GitHub release, deep-merges the opinionated override block for `<id>` onto the vault's `data.json`, and registers the id in `community-plugins.json`. Version-aware; no-ops when the vault is current. Bundled plugins (today: `iconize-reloader`) install with `--bundled` from `templates/obsidian/plugins/<id>/`.
- *"I want Iconize set up in this vault from scratch."* — `/lazy-obsidian.iconize-install` installs all three iconize-sync hard-dependency plugins via `/lazy-obsidian.update-plugin` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`), then scaffolds the worker, registry, protocol doc, and pre-commit shim into the vault.
- *"I need to edit which folders get which icons."* — `/lazy-obsidian.iconize-config` is a wizard for editing the Iconize registry (the declarative mapping of paths to icons).
- *"I need to apply the current registry to my notes."* — `/lazy-obsidian.iconize-sync` wraps the worker (`bin/iconize_sync.py`) to reconcile the registry into each matched note's `iconize_icon` / `iconize_color` frontmatter; Iconize and the bundled `iconize-reloader` repaint from there.
- *"What does this plugin do?"* — `/lazy-obsidian.help`.

## Blocks

- **iconize** — Folder-icon system for the vault: a declarative path→icon registry, a wizard to edit it, and a sync worker that paints each note's `iconize_icon` / `iconize_color` frontmatter. Members: lazy-obsidian.iconize-install, lazy-obsidian.iconize-config, lazy-obsidian.iconize-sync.
- **diagram-rendering** — Render glue for the lazycortex-diagram engine inside Obsidian: mermaid / ascii fit CSS snippets plus click-to-zoom for fences. Members: lazy-obsidian.diagram-install.
- **tag-pages** — Generate and refresh Obsidian tag pages from the tags used across the vault's notes, keeping the `Tags/` hierarchy in sync. Members: lazy-obsidian.gen-tag-pages.
- **install-and-audit** — Bootstrap the vault (rules, tag-page template, Dataview, chained iconize + diagram install), install or refresh an individual community plugin by id, and audit vault config. Members: lazy-obsidian.install, lazy-obsidian.audit, lazy-obsidian.update-plugin.

## Walkthroughs

- **vault-bootstrap** — Take a fresh repo to a fully wired Obsidian vault in one pass. Path: lazy-obsidian.install → lazy-obsidian.iconize-install → lazy-obsidian.diagram-install.

## Requirements

- **Claude Code** with plugin support.
- **Obsidian** (the app) — for the config to take effect. The skills run without Obsidian running.
- **git** — `lazy-obsidian.update-plugin` resolves the vault target via `git rev-parse --show-toplevel`.
- **Python 3** — the iconize-sync worker (`bin/iconize_sync.py`) is Python-stdlib only.
- **`jq`** — used by `lazy-obsidian.update-plugin` for deep-merging the opinionated override block onto plugin `data.json`.
- **`curl`** — used by `lazy-obsidian.update-plugin` to resolve the Obsidian community registry and fetch plugin binaries from GitHub releases.
- **`lazycortex-core` (required)** — dependency declared in `plugin.json`; `lazy-obsidian.install` reuses the install pattern.

## Quick start

1. Enable the plugin at **project scope** — `.obsidian/` and `.mcp.json` are repo-specific.
2. Restart Claude Code.
3. Run `/lazy-obsidian.install` once per project. It syncs plugin rules and the tag-page template, installs Dataview, and offers to chain into `/lazy-obsidian.iconize-install` — a single entry point for the whole vault bootstrap. Re-run any time; idempotent.
4. If you skipped the iconize chain, run `/lazy-obsidian.iconize-install` later to scaffold the Iconize worker, registry, protocol doc, and pre-commit shim.
5. Edit the registry via `/lazy-obsidian.iconize-config`, then apply it with `/lazy-obsidian.iconize-sync` whenever you need to reconcile icons into note frontmatter (Iconize + the bundled `iconize-reloader` repaint from there).
6. Need to install or refresh a single vault plugin out-of-band? Use `/lazy-obsidian.update-plugin <id>` (`--bundled` for plugins shipped inside this LazyCortex plugin).

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-obsidian.audit` | Semantic audit for the lazycortex-obsidian plugin. Verifies iconize-sync artifacts stay coherent: worker version constants match template HOOK_VERSION markers, icon-map template parses at the current schema with no retired keys, protocol template's `owner_skill` points at an existing skill, hook templates carry parseable version markers. Phase 8 covers the diagram render glue: mermaid-fit.css + ascii-fit.css presence + selector shape, mermaid-popup override block in plugin-settings.json, no stale palette CSS. Read-first; presents findings, then asks which to fix. Delegated from `lazy-core.doctor` Phase 3. |
| `lazy-obsidian.diagram-install` | Scaffold the Obsidian render glue for the lazycortex-diagram engine into a vault: install the `mermaid-fit.css` and `ascii-fit.css` snippets, enable them in `appearance.json`, and install the `mermaid-popup` community plugin (click-to-zoom for mermaid fences) via `/lazy-obsidian.update-plugin`. Quiet file-sync — writes silently when absent or unchanged, merges silently when the shipped delta doesn't contradict local edits, and asks only on a genuine conflict. Re-runnable; idempotent. Project-scope only (no global mode — Obsidian render glue is per-vault). Detects and silently keeps the legacy `mermaid-no-bg.css` snippet (made redundant by the engine's theme directive). |
| `lazy-obsidian.iconize-config` | Interactively add, edit, or remove registry entries in the local `.claude/iconize/obsidian-icon-map.json` (roles, steps, requests, or any custom registry). Re-runnable. Writes back JSON with stable formatting. Use when the resolver misses a role/step/etc. — this skill is the canonical way to seed the missing registry entry without hand-editing. |
| `lazy-obsidian.iconize-install` | Scaffold the iconize-sync system into an Obsidian vault: local icon-map, pre-commit shim, and a `.gitignore` entry for Iconize's live `data.json` (it's rewritten on every icon click and by the bundled iconize-reloader plugin — runtime state, not source). Quiet file-sync — writes/merges silently when absent, unchanged, or non-conflicting; asks only on a genuine same-region conflict. Orphans (a retired vault-local protocol doc, stale worker-written PostToolUse entries) are left in place silently, never deleted. Migrates icon-map schema in place. Re-runnable; idempotent. Must be run from the consumer vault's git root. Installs all three iconize-sync hard-dependency plugins — `obsidian-icon-folder` (Iconize), `folder-notes`, and the bundled `iconize-reloader` — via the `/lazy-obsidian.update-plugin` primitive, which also deep-merges opinionated settings from `plugin-settings.json`. PostToolUse is plugin-shipped — no consumer settings.json mutation. |
| `lazy-obsidian.iconize-sync` | Resolve Obsidian file/folder icons from a declarative icon-map and write the result into each note's `iconize_icon` / `iconize_color` frontmatter keys. The worker never touches `.obsidian/plugins/obsidian-icon-folder/data.json` — Iconize itself paints non-folder-note icons live from frontmatter, and the bundled `iconize-reloader` plugin bridges folder-note frontmatter into folder-keyed `data.json` entries. Driven by `.claude/iconize/obsidian-icon-map.json`. Subcommands: `sync`, `sync-staged`, `reconcile`, `reconcile-plugin`, `reconcile-dirty`, `install-hooks`, `check-versions`. Callable from `.githooks/pre-commit`, Claude Code's PostToolUse hook, and Claude Code's Stop hook. |
| `lazy-obsidian.install` | Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none) and scaffolds the tag-page template used by the `lazy-obsidian.gen-tag-pages` agent (project scope only) via quiet file-sync — writes/merges silently, asks only on a genuine conflict, leaves orphans in place. At project scope it is the root entry point for the plugin family: installs the Dataview Obsidian plugin into `<repo-root>/.obsidian/` via `/lazy-obsidian.update-plugin` (Dataview renders the `Index` section of tag pages) and runs `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install` so the full vault setup completes in one pass (no per-chain opt-in — plugin enabled means full functionality). Idempotent — safe to re-run. Detects install scope automatically. |
| `lazy-obsidian.update-plugin` | Install or update a single Obsidian vault community plugin by id. Version-aware: skip if current, install if missing, update if the remote is newer. Resolves the GitHub repo via the Obsidian community registry (or reads from a bundled source in `<installPath>/templates/obsidian/plugins/<id>/` when `--bundled` is passed). Fetches `manifest.json` / `main.js` / `styles.css` with backup-safe writes. Deep-merges the opinionated override block for `<id>` from `<installPath>/templates/obsidian/plugin-settings.json` onto `<vault>/plugins/<id>/data.json`. Registers `<id>` in `<vault>/community-plugins.json`. Primitive called from `/lazy-obsidian.install` (for `dataview`) and `/lazy-obsidian.iconize-install` (for `obsidian-icon-folder`, `folder-notes`, `iconize-reloader`). |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [diagram-rendering](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/diagram-rendering.md) — Wire the lazycortex-diagram engine's CSS snippets and click-to-zoom plugin into your Obsidian vault so mermaid and ASCII diagrams render correctly in Reading Mode.
- [iconize](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/iconize.md) — Scaffold, configure, and run the iconize-sync system to keep Obsidian file and folder icons in sync with your vault's frontmatter-driven icon registry.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/install-and-audit.md) — Install, keep current, and audit the lazycortex-obsidian plugin — vault bootstrap, Obsidian plugin management, and semantic integrity checks in one pass.
- [tag-pages](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/tag-pages.md) — Keep a Tags/ folder in sync with every tag used across your vault — pages created, updated, and pruned automatically.
- [vault-bootstrap](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/walkthroughs/vault-bootstrap.md) — Go from a bare repo to a fully-wired Obsidian vault — Iconize sync, diagram render glue, and click-to-zoom — in a single chained install pass.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/troubleshooting.md) — Symptoms, likely causes, and fixes for lazycortex-obsidian — install, iconize, diagram render, plugin updates, and tag pages.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/faq.md) — Answers to common questions about vault setup, Iconize, diagram render glue, plugin updates, and tag pages for lazycortex-obsidian.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-obsidian/help/`.

## Agents

| Agent | Description |
|---|---|
| `lazy-obsidian.gen-tag-pages` | Use this agent to generate or update Obsidian tag pages from tags used across the vault's notes. Scans all `.md` files for `tags:` frontmatter, then creates/updates/removes tag pages under `Tags/` keeping the folder hierarchy matching the tag hierarchy. Template is read from the consumer repo at `.claude/templates/obsidian.tag-page-template.md` (bootstrap via `lazy-obsidian.install`). |

## Commands

| Command | Description |
|---|---|
| `lazy-obsidian.help` | Show lazycortex-obsidian purpose and a one-line summary of each skill it ships |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `iconize_sync` | `Stop`, `Write\|Edit` | Generic iconize-sync worker for the lazycortex-obsidian plugin. |

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
/lazy-obsidian.diagram-install
/lazy-obsidian.iconize-config
/lazy-obsidian.iconize-install
/lazy-obsidian.iconize-sync
/lazy-obsidian.install
/lazy-obsidian.update-plugin
```
