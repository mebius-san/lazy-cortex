---
description: Show lazycortex-obsidian purpose and a one-line summary of each skill it ships
---

Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-obsidian** — bootstrap and manage an Obsidian vault (`.obsidian/`) from inside a repo. Ships a curated vault snapshot plus skills that bring the project's vault into alignment — safely, with per-plugin drift prompts, and without blanket-ignoring `.obsidian/`. Also ships a standalone iconize-sync worker (`bin/iconize_sync.py`) with templates under `templates/obsidian-iconize/`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-obsidian.install` — sync the plugin's rule templates into `.claude/rules/` (currently ships none), scaffold the tag-page template used by `obsidian.gen-tag-pages` at `.claude/templates/obsidian.tag-page-template.md` (project scope only), warn if Dataview is missing, and clean up orphans from earlier versions. Idempotent; does not touch any `.obsidian/`.
- `lazy-obsidian.config` — greenfield bootstrap or audit-and-merge the project's `.obsidian/` against the bundled snapshot; per-plugin drift prompts; regenerates `community-plugins.json` in correct load order; updates `.gitignore`; prompts for vault nickname and MCP wiring.
- `lazy-obsidian.iconize-install` — scaffold-into-vault wizard; copies the Iconize worker, registry, and config from `templates/obsidian-iconize/` into the current vault. Idempotent.
- `lazy-obsidian.iconize-configure` — registry-editing wizard; add / remove / update entries in the declarative Iconize registry without hand-editing JSON.
- `lazy-obsidian.iconize-sync` — worker wrapper; applies the registry to `obsidian-icon-folder/data.json` via `bin/iconize_sync.py`; concurrent-safe; callable standalone or from other skills.
- `lazy-obsidian.audit` — read-only self-check of the plugin surface (forthcoming; ships in the next commit).

**Agents** (invoke by name via the Agent tool):

- `obsidian.gen-tag-pages` — regenerate Obsidian tag pages under `Tags/` from `tags:` frontmatter across every `.md` in the vault. Reads its template from `.claude/templates/obsidian.tag-page-template.md` (scaffolded by `lazy-obsidian.install`).

**Rules**: none. Vault-hygiene guidance is inlined into `lazy-obsidian.config/SKILL.md` so it only loads when the skill runs, not on every session.

**Commands**:

- `lazy-obsidian.help` — this message.

See `README.md` in the plugin for the full rationale, vault snapshot contents, and end-to-end workflow.
