---
description: Show lazycortex-obsidian purpose and a one-line summary of each skill it ships
---

Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-obsidian** — bootstrap and manage an Obsidian vault (`.obsidian/`) from inside a repo. Ships a curated vault snapshot plus skills that bring the project's vault into alignment — safely, with per-plugin drift prompts, and without blanket-ignoring `.obsidian/`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-obsidian.install` — sync the plugin's rule templates into `.claude/rules/` (currently ships none) and clean up orphans from earlier versions. Idempotent; does not touch any `.obsidian/`.
- `lazy-obsidian.config` — greenfield bootstrap or audit-and-merge the project's `.obsidian/` against the bundled snapshot; per-plugin drift prompts; regenerates `community-plugins.json` in correct load order; updates `.gitignore`; prompts for vault nickname and MCP wiring.
- `lazy-obsidian.iconize-file` — mechanics-only primitive for the Iconize plugin's `data.json`: set / clear / get / list / bulk-apply / reconcile icon entries; concurrent-safe; callable standalone or from other skills.

**Rules**: none. Vault-hygiene guidance is inlined into `lazy-obsidian.config/SKILL.md` so it only loads when the skill runs, not on every session.

**Commands**:

- `lazy-obsidian.help` — this message.

See `README.md` in the plugin for the full rationale, vault snapshot contents, and end-to-end workflow.
