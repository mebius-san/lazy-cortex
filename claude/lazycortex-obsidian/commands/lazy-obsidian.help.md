---
description: "Run when the operator asks what lazycortex-obsidian can do to this repo's vault, or which verb handles folder icons, tag pages, or a community plugin — lists the vault surface: install, single-plugin update, the iconize install / config / sync trio, the semantic audit, and the tag-page generator agent."
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-obsidian** — bootstrap and manage an Obsidian vault (`.obsidian/`) from inside a repo. Ships a curated vault snapshot plus skills that bring the project's vault into alignment, and a manifest workflow that carries a vault's whole configuration as one tracked file instead of a hundred that the mobile app rewrites behind git's back. Also ships two standalone workers: iconize-sync (`bin/iconize_sync.py`, templates under `templates/iconize/`) and the vault-manifest worker (`bin/vault_manifest.py`).

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-obsidian.install` — root entry point. Syncs the plugin's rule templates into `.claude/rules/` (currently ships none), scaffolds the tag-page template used by `lazy-obsidian.gen-tag-pages` at `.claude/templates/lazy-obsidian.tag-page-template.md` (project scope only), installs Dataview via `/lazy-obsidian.update-plugin`, and offers to chain into `/lazy-obsidian.iconize-install`. Idempotent; detects install scope automatically.
- `lazy-obsidian.update-plugin` — primitive: install or update a single Obsidian vault community plugin by id. Version-aware (skip if current, install if missing, update if the remote is newer). Resolves the GitHub repo via the Obsidian community registry (or reads from a bundled source with `--bundled`). Deep-merges the opinionated override block for `<id>` from `plugin-settings.json` onto the vault's `data.json`. Registers the id in `community-plugins.json`. Called from `/lazy-obsidian.install` and `/lazy-obsidian.iconize-install`.
- `lazy-obsidian.iconize-install` — scaffold-into-vault wizard. Installs all three iconize-sync hard-dependency plugins via `/lazy-obsidian.update-plugin` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`), then scaffolds the icon-map registry from `templates/iconize/` and registers the repaint routine. Idempotent.
- `lazy-obsidian.iconize-config` — registry-editing wizard; add / remove / update entries in the declarative Iconize registry without hand-editing JSON.
- `lazy-obsidian.iconize-sync` — worker wrapper; applies the registry to each matched note's `iconize_icon` / `iconize_color` frontmatter via `bin/iconize_sync.py` (Iconize + the bundled `iconize-reloader` repaint from there); callable standalone or from other skills.
- `lazy-obsidian.capture` — snapshot the vault's whole `.obsidian/` configuration into the tracked `.obsidian.manifest.json` and commit it. Plugin settings, snippets, theme, palette, and top-level config travel as one reviewed file; per-device state, credentials, and Iconize's own database are deliberately left out.
- `lazy-obsidian.deploy` — rebuild `.obsidian/` from that manifest on a checkout that has none: every plugin at its latest release, the captured settings on top, snippets, theme, and the top-level config files. Never pins a version.
- `lazy-obsidian.audit` — read-only semantic audit of the plugin surface, delegated from `lazy-core.doctor`. Also reports how far a live vault's config has drifted from its manifest, when the repo carries one.

**Agents** (invoke by name via the Agent tool):

- `lazy-obsidian.gen-tag-pages` — regenerate Obsidian tag pages under `Tags/` from `tags:` frontmatter across every `.md` in the vault. Reads its template from `.claude/templates/lazy-obsidian.tag-page-template.md` (scaffolded by `lazy-obsidian.install`).

**Rules**: none. Vault-hygiene guidance is inlined into the individual install/iconize-install skills so it only loads when the skill runs, not on every session.

**Commands**:

- `lazy-obsidian.help` — this message.

<!-- help-block:start -->
**Documentation:**

- [vault-bootstrap](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/walkthroughs/vault-bootstrap.md) — Go from a bare repo to a fully-wired Obsidian vault — tag pages, Iconize sync, diagram glue, click-to-zoom — one chained install.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/troubleshooting.md) — Symptoms, likely causes, and fixes for lazycortex-obsidian — install, iconize, diagram render, plugin updates, tag pages, and vault manifest capture/deploy.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-obsidian/help/faq.md) — Answers to common questions about vault setup, Iconize, diagram render glue, the vault manifest, plugin updates, and tag pages for lazycortex-obsidian.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-obsidian/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for the full rationale, vault snapshot contents, and end-to-end workflow.
