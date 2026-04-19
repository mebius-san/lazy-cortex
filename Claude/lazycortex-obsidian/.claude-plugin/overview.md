## Why this plugin

Obsidian vaults accumulate configuration over time — plugins, icons, themes, hotkeys, snippets — and that configuration is where most of the productivity lives. Sharing a vault baseline across machines or cloning someone else's repo usually means either committing a blanket-ignored `.obsidian/` (so the next clone has none of it) or committing the whole thing (so merge conflicts and stale plugin code ride along). Neither works.

`lazycortex-obsidian` ships a curated vault snapshot inside the plugin and two skills that bring a project's `.obsidian/` into alignment with it — safely, with per-plugin drift prompts, and without ever blanket-ignoring the vault.

## Who it's for

- **Developers who keep project docs in Obsidian** and want the same baseline (Iconize, Folder Notes, Templater, Git, Linter) on every repo they clone.
- **Teams standardizing on a vault template** who need new clones to pick up the config without manual setup.
- **AI-assisted workflows** that want the `obsidian-mcp` server wired into `.mcp.json` for every project, with `OBSIDIAN_VAULT_PATH="."` so it works on any machine.
- **Plugin authors** who need a programmatic way to paint folder/file icons via the Iconize plugin's `data.json` without running Obsidian.

## Scenarios

- *"Fresh repo, no `.obsidian/` yet."* — `/lazy-obsidian.config` copies the curated snapshot, prompts for optional plugins, regenerates `community-plugins.json` in correct load order, wires `.gitignore`, sets the vault nickname, and optionally adds the MCP server.
- *"Repo already has a vault that's drifted."* — the same skill runs in audit mode, diffs each musthave plugin's `data.json` against the snapshot, and asks per plugin: overwrite / keep-local / merge-missing-keys.
- *"I need to paint these folders with icons programmatically."* — `/lazy-obsidian.iconize-file` is the mechanics-only primitive: set, clear, read, list, bulk-apply, or reconcile icon entries in `obsidian-icon-folder/data.json`, concurrent-safe.
- *"What does this plugin do?"* — `/lazy-obsidian.help`.

## Requirements

- **Claude Code** with plugin support.
- **Obsidian** (the app) — for the config to take effect. The skills run without Obsidian running.
- **git** — `lazy-obsidian.config` resolves the vault target via `git rev-parse --show-toplevel`.
- **Python 3** — the Iconize helper (`iconize.py`) is Python-stdlib only.
- **`jq`** — used by `lazy-obsidian.config` for merge-missing-keys and vault-nickname writes.
- **`lazycortex-core` (required)** — dependency declared in `plugin.json`; `lazy-obsidian.install` reuses the install pattern and `tool.doctor` validates the plugin surface.

## Quick start

1. Enable the plugin at **project scope** — `.obsidian/` and `.mcp.json` are repo-specific.
2. Restart Claude Code.
3. Run `/lazy-obsidian.install` once per project. The plugin ships no rules today — run the skill anyway to clean up rules from earlier versions if you're upgrading.
4. Run `/lazy-obsidian.config` to bootstrap or audit the vault. Re-run any time — it's idempotent.
5. Use `/lazy-obsidian.iconize-file` (or call it from another skill) whenever you need to touch icon entries.
