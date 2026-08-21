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
- *"I want Iconize set up in this vault from scratch."* — `/lazy-obsidian.iconize-install` installs all three iconize-sync hard-dependency plugins via `/lazy-obsidian.update-plugin` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`), then scaffolds the icon-map registry and repaint routine into the vault.
- *"I need to edit which folders get which icons."* — `/lazy-obsidian.iconize-config` is a wizard for editing the Iconize registry (the declarative mapping of paths to icons).
- *"I need to apply the current registry to my notes."* — `/lazy-obsidian.iconize-sync` wraps the worker (`bin/iconize_sync.py`) to reconcile the registry into each matched note's `iconize_icon` / `iconize_color` frontmatter; Iconize and the bundled `iconize-reloader` repaint from there.
- *"What does this plugin do?"* — `/lazy-obsidian.help`.

## Blocks

- **iconize** — Folder-icon system for the vault: a declarative path→icon registry, a wizard to edit it, and a sync worker that paints each note's `iconize_icon` / `iconize_color` frontmatter. Members: lazy-obsidian.iconize-install, lazy-obsidian.iconize-config, lazy-obsidian.iconize-sync.
- **diagram-rendering** — Click-to-zoom for diagram fences in Obsidian (the `mermaid-popup` vault plugin). The mermaid/ascii fit CSS snippets it declares are installed and enabled by `lazy-obsidian.install`'s shared snippet step, not by this skill. Members: lazy-obsidian.diagram-install.
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
4. If you skipped the iconize chain, run `/lazy-obsidian.iconize-install` later to scaffold the Iconize registry and repaint routine.
5. Edit the registry via `/lazy-obsidian.iconize-config`, then apply it with `/lazy-obsidian.iconize-sync` whenever you need to reconcile icons into note frontmatter (Iconize + the bundled `iconize-reloader` repaint from there).
6. Need to install or refresh a single vault plugin out-of-band? Use `/lazy-obsidian.update-plugin <id>` (`--bundled` for plugins shipped inside this LazyCortex plugin).

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-obsidian.audit` | Run when the operator asks to audit the lazycortex-obsidian plugin, or when its machinery misbehaves after an update — icons stop being painted, the icon-map is rejected as the wrong schema, or mermaid/ascii fences render unstyled in the vault. Checks the plugin's own shipped artifacts (worker version constants, icon-map template, the Iconize settings block, the render-glue CSS), not any one vault's installed state. Read-first; presents findings, then asks which to fix. |
| `lazy-obsidian.diagram-install` | Run when the operator asks to make click-to-zoom work on lazycortex diagrams in Obsidian, or when they report that clicking a mermaid diagram doesn't zoom. Installs the `mermaid-popup` vault plugin. Does NOT install the fit-CSS snippets (mermaid fences overflowing the column, sitting on a white box, or clipped ASCII diagrams) — those are installed and enabled by `/lazy-obsidian.install`'s shared snippet step; run that instead for those symptoms. Project scope only, idempotent, and chained from `/lazy-obsidian.install`. |
| `lazy-obsidian.iconize-config` | Use when the iconize resolver misses a value — a role, step, or request status with no icon — or when the operator wants to change or drop one. Wizard over the vault's local `.claude/iconize/obsidian-icon-map.json`; the canonical way to seed a registry entry instead of hand-editing that JSON. Requires `lazy-obsidian.iconize-install` to have run first. |
| `lazy-obsidian.iconize-install` | Run when the operator asks to set up folder and file icons in this Obsidian vault, or when `/lazy-obsidian.iconize-sync` refuses because the icon-map is missing, or the Iconize / folder-notes / iconize-reloader vault plugins aren't there. Scaffolds the vault-side pieces (icon-map, gitignore entry, schema migration, repaint routine) and installs those three plugins. Chained from `/lazy-obsidian.install`; idempotent, and must be run from the vault's git root. |
| `lazy-obsidian.iconize-sync` | Use when a note's or folder's icon is stale and must be re-resolved from the icon-map — after editing `.claude/iconize/obsidian-icon-map.json`, after a bulk frontmatter or stage change, or when files were written via Bash and bypassed the hooks (`reconcile-dirty`). Also invoked non-interactively by the plugin's PostToolUse hook and the `lazy-obsidian.repaint` daemon routine. Writes only `iconize_icon` / `iconize_color` frontmatter — never Iconize's `data.json`. |
| `lazy-obsidian.install` | Run when the operator asks to set up Obsidian for this repo or to wire up a fresh vault, and again after a plugin update so new artifacts land. Also the answer when tag pages render empty (Dataview missing), the tag-page template isn't in `.claude/templates/`, icons are unpainted, or diagrams render unstyled — at project scope this is the plugin family's root entry point and chains `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install`. Idempotent; install scope is detected, not asked. |
| `lazy-obsidian.update-plugin` | Dispatched by `/lazy-obsidian.install` (for `dataview`) and `/lazy-obsidian.iconize-install` (for `obsidian-icon-folder`, `folder-notes`, `iconize-reloader`) to put one community plugin into the vault. Also run it directly when the operator asks to install, refresh, or update a single Obsidian plugin by id in this repo's vault, or when a vault plugin is reported as out of date. Version-aware — no-ops when the vault is already current; `--bundled` installs from the plugin's own bundled source instead of GitHub. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [vault-bootstrap](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/walkthroughs/vault-bootstrap.md) — Go from a bare repo to a fully-wired Obsidian vault — tag pages, Iconize sync, diagram glue, click-to-zoom — one chained install.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/troubleshooting.md) — Symptoms, likely causes, and fixes for lazycortex-obsidian — install, iconize, diagram render, and plugin updates.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/faq.md) — Answers to common questions about vault setup, Iconize, diagram render glue, plugin updates, and tag pages for lazycortex-obsidian.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-obsidian.gen-tag-pages` | Use when tags were added, renamed, or removed on the vault's notes and the pages under `Tags/` no longer match — or when the operator asks to regenerate tag pages. Scans all `.md` files for `tags:` frontmatter, then creates/updates/removes tag pages under `Tags/` keeping the folder hierarchy matching the tag hierarchy. Template is read from the consumer repo at `.claude/templates/lazy-obsidian.tag-page-template.md` (bootstrap via `lazy-obsidian.install`). <example> Context: New notes were added with new tags, or tags were added/removed from existing notes user: "Regenerate tag pages" assistant: "I'll use the lazy-obsidian.gen-tag-pages agent to regenerate the Obsidian tag pages" </example> |

## Commands

| Command | Description |
|---|---|
| `lazy-obsidian.help` | Run when the operator asks what lazycortex-obsidian can do to this repo's vault, or which verb handles folder icons, tag pages, or a community plugin — lists the vault surface: install, single-plugin update, the iconize install / config / sync trio, the semantic audit, and the tag-page generator agent. |

## Rules

| Rule | Description |
|---|---|
| `lazy-obsidian.markdown.md` | Markdown constructs Obsidian interprets as structure — what to escape when writing into a vault so notes do not gain phantom tags, lose their frontmatter, or grow unintended dataview fields. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `iconize_sync` | `Write|Edit` | PostToolUse hook: resolve and write iconize_icon/iconize_color frontmatter for an edited markdown note via the icon-map registry. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-obsidian@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-obsidian:<skill.name>`.

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
