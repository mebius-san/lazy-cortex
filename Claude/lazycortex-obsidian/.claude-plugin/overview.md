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
