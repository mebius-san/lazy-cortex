---
description: Show lazycortex-obsidian purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-obsidian** — bootstrap and manage an Obsidian vault (`.obsidian/`) from inside a repo. Ships a curated vault snapshot plus skills that bring the project's vault into alignment — safely, with per-plugin drift prompts, and without blanket-ignoring `.obsidian/`. Also ships a standalone iconize-sync worker (`bin/iconize_sync.py`) with templates under `templates/obsidian-iconize/`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-obsidian.install` — root entry point. Syncs the plugin's rule templates into `.claude/rules/` (currently ships none), scaffolds the tag-page template used by `obsidian.gen-tag-pages` at `.claude/templates/obsidian.tag-page-template.md` (project scope only), installs Dataview via `/lazy-obsidian.update-plugin`, and offers to chain into `/lazy-obsidian.iconize-install`. Idempotent; detects install scope automatically.
- `lazy-obsidian.update-plugin` — primitive: install or update a single Obsidian vault community plugin by id. Version-aware (skip if current, install if missing, update if the remote is newer). Resolves the GitHub repo via the Obsidian community registry (or reads from a bundled source with `--bundled`). Deep-merges the opinionated override block for `<id>` from `plugin-settings.json` onto the vault's `data.json`. Registers the id in `community-plugins.json`. Called from `/lazy-obsidian.install` and `/lazy-obsidian.iconize-install`.
- `lazy-obsidian.iconize-install` — scaffold-into-vault wizard. Installs all three iconize-sync hard-dependency plugins via `/lazy-obsidian.update-plugin` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`), then copies the worker, registry, protocol doc, and pre-commit shim from `templates/obsidian-iconize/` into the current vault. Idempotent.
- `lazy-obsidian.iconize-config` — registry-editing wizard; add / remove / update entries in the declarative Iconize registry without hand-editing JSON.
- `lazy-obsidian.iconize-sync` — worker wrapper; applies the registry to `obsidian-icon-folder/data.json` via `bin/iconize_sync.py`; concurrent-safe; callable standalone or from other skills.
- `lazy-obsidian.audit` — read-only semantic audit of the plugin surface, delegated from `lazy-core.doctor`.

**Agents** (invoke by name via the Agent tool):

- `obsidian.gen-tag-pages` — regenerate Obsidian tag pages under `Tags/` from `tags:` frontmatter across every `.md` in the vault. Reads its template from `.claude/templates/obsidian.tag-page-template.md` (scaffolded by `lazy-obsidian.install`).

**Rules**: none. Vault-hygiene guidance is inlined into the individual install/iconize-install skills so it only loads when the skill runs, not on every session.

**Commands**:

- `lazy-obsidian.help` — this message.

See `README.md` in the plugin for the full rationale, vault snapshot contents, and end-to-end workflow.
