---
description: Show lazycortex-obsidian purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-obsidian** — bootstrap and manage an Obsidian vault (`.obsidian/`) from inside a repo. Ships a curated vault snapshot plus skills that bring the project's vault into alignment — safely, with per-plugin drift prompts, and without blanket-ignoring `.obsidian/`. Also ships a standalone iconize-sync worker (`bin/iconize_sync.py`) with templates under `templates/iconize/`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-obsidian.install` — root entry point. Syncs the plugin's rule templates into `.claude/rules/` (currently ships none), scaffolds the tag-page template used by `lazy-obsidian.gen-tag-pages` at `.claude/templates/obsidian.tag-page-template.md` (project scope only), installs Dataview via `/lazy-obsidian.update-plugin`, and offers to chain into `/lazy-obsidian.iconize-install`. Idempotent; detects install scope automatically.
- `lazy-obsidian.update-plugin` — primitive: install or update a single Obsidian vault community plugin by id. Version-aware (skip if current, install if missing, update if the remote is newer). Resolves the GitHub repo via the Obsidian community registry (or reads from a bundled source with `--bundled`). Deep-merges the opinionated override block for `<id>` from `plugin-settings.json` onto the vault's `data.json`. Registers the id in `community-plugins.json`. Called from `/lazy-obsidian.install` and `/lazy-obsidian.iconize-install`.
- `lazy-obsidian.iconize-install` — scaffold-into-vault wizard. Installs all three iconize-sync hard-dependency plugins via `/lazy-obsidian.update-plugin` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`), then copies the worker, registry, protocol doc, and pre-commit shim from `templates/iconize/` into the current vault. Idempotent.
- `lazy-obsidian.iconize-config` — registry-editing wizard; add / remove / update entries in the declarative Iconize registry without hand-editing JSON.
- `lazy-obsidian.iconize-sync` — worker wrapper; applies the registry to each matched note's `iconize_icon` / `iconize_color` frontmatter via `bin/iconize_sync.py` (Iconize + the bundled `iconize-reloader` repaint from there); callable standalone or from other skills.
- `lazy-obsidian.audit` — read-only semantic audit of the plugin surface, delegated from `lazy-core.doctor`.

**Agents** (invoke by name via the Agent tool):

- `lazy-obsidian.gen-tag-pages` — regenerate Obsidian tag pages under `Tags/` from `tags:` frontmatter across every `.md` in the vault. Reads its template from `.claude/templates/obsidian.tag-page-template.md` (scaffolded by `lazy-obsidian.install`).

**Rules**: none. Vault-hygiene guidance is inlined into the individual install/iconize-install skills so it only loads when the skill runs, not on every session.

**Commands**:

- `lazy-obsidian.help` — this message.

<!-- help-block:start -->
**Documentation:**

- [diagram-rendering](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/diagram-rendering.md) — Wire the lazycortex-diagram engine's CSS snippets and click-to-zoom plugin into your Obsidian vault so mermaid and ASCII diagrams render correctly in Reading Mode.
- [iconize](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/iconize.md) — Scaffold, configure, and run the iconize-sync system to keep Obsidian file and folder icons in sync with your vault's frontmatter-driven icon registry.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/install-and-audit.md) — Install, keep current, and audit the lazycortex-obsidian plugin — vault bootstrap, Obsidian plugin management, and semantic integrity checks in one pass.
- [tag-pages](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/tag-pages.md) — Keep a Tags/ folder in sync with every tag used across your vault — pages created, updated, and pruned automatically.
- [vault-bootstrap](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/walkthroughs/vault-bootstrap.md) — Go from a bare repo to a fully-wired Obsidian vault — Iconize sync, diagram render glue, and click-to-zoom — in a single chained install pass.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/troubleshooting.md) — Symptoms, likely causes, and fixes for lazycortex-obsidian — install, iconize, diagram render, plugin updates, and tag pages.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/faq.md) — Answers to common questions about vault setup, Iconize, diagram render glue, plugin updates, and tag pages for lazycortex-obsidian.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-obsidian/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for the full rationale, vault snapshot contents, and end-to-end workflow.
