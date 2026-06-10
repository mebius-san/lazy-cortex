---
chapter_type: faq
summary: Answers to common questions about vault setup, Iconize, diagram render glue, plugin updates, and tag pages for lazycortex-obsidian.
last_regen: 2026-06-10
no_diagram: true
source_skills:
  - lazy-obsidian.install
  - lazy-obsidian.audit
  - lazy-obsidian.diagram-install
  - lazy-obsidian.iconize-config
  - lazy-obsidian.iconize-install
  - lazy-obsidian.iconize-sync
  - lazy-obsidian.update-plugin
  - lazy-obsidian.gen-tag-pages
---
# Frequently asked questions

## Do I need to run anything after enabling the plugin, or does it self-configure?

You need to run `/lazy-obsidian.install` once per project after enabling the plugin. Enabling adds the skills to Claude Code, but the vault setup — Dataview installation, Iconize scaffolding, and diagram render glue — runs only when you invoke that skill. It is idempotent, so running it again after a `/plugin update` is safe and picks up any template or CSS changes.

---

## `/lazy-obsidian.install` aborted saying the plugin is not installed. What happened?

The skill looks for a `lazycortex-obsidian@lazycortex` entry in `~/.claude/plugins/installed_plugins.json`. If that entry is absent or empty, the skill stops rather than guessing the paths. Add `"lazycortex-obsidian@lazycortex": true` under `enabledPlugins` in your `settings.json`, restart Claude Code, then re-run `/lazy-obsidian.install`.

---

## `/lazy-obsidian.install` says "plugin cache is empty". How do I fix it?

The plugin cache is the installed copy of the plugin's files. An empty cache usually means the initial download did not complete. Run `/plugin update lazycortex-obsidian@lazycortex` to refresh the cache, then re-run `/lazy-obsidian.install`.

---

## I ran `/lazy-obsidian.install` but icons are not showing up in Obsidian. What should I check?

Icons are painted by Iconize reading `iconize_icon` and `iconize_color` from each note's frontmatter. Three things are required: Iconize's `iconInFrontmatterEnabled` setting must be `true` with the field names set to `iconize_icon` and `iconize_color` (asserted automatically by `/lazy-obsidian.iconize-install`), the icon-map at `.claude/iconize/obsidian-icon-map.json` must have matchers that cover your notes, and `/lazy-obsidian.iconize-sync reconcile` must have been run to write the frontmatter. If the matchers are missing entries, run `/lazy-obsidian.iconize-config` to add them, then run `/lazy-obsidian.iconize-sync reconcile` to apply.

---

## How do I add a new icon rule for a folder or file type?

Run `/lazy-obsidian.iconize-config`. The wizard walks you through picking a registry, then adding a key with an icon name (Lucide PascalCase with `Li` prefix, or an emoji) and an optional color. After saving, run `/lazy-obsidian.iconize-sync reconcile` so the new rule is applied across all notes.

---

## Iconize shows icons on files but not on folders. Why?

Folder icons are written by the bundled `iconize-reloader` plugin, not by Iconize directly. The reloader watches folder-note frontmatter and bridges it into Iconize's `data.json`. Check that `iconize-reloader` is installed in your vault — run `/lazy-obsidian.iconize-install` (idempotent) to ensure all three hard dependencies (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader`) are present and current.

---

## `/lazy-obsidian.iconize-config` aborts saying the icon-map is not found. What do I do?

The icon-map at `.claude/iconize/obsidian-icon-map.json` is scaffolded by `/lazy-obsidian.iconize-install`. Run that skill first, then re-run `/lazy-obsidian.iconize-config`.

---

## `/lazy-obsidian.iconize-install` aborted with a hard dependency failure. What does that mean?

The skill installs three plugins — `obsidian-icon-folder`, `folder-notes`, and `iconize-reloader` — before scaffolding the icon-map. If any of the three fails (network error, registry lookup failure), the skill stops rather than leaving the vault in a half-installed state. Check network connectivity, run `/lazy-obsidian.update-plugin <id>` manually to see the underlying error, then re-run `/lazy-obsidian.iconize-install`.

---

## Do I need to commit `.obsidian/plugins/obsidian-icon-folder/data.json`?

No. That file is runtime state — Iconize rewrites it on every icon click and the `iconize-reloader` plugin rewrites it whenever folder-note frontmatter changes. Committing it produces noisy diffs and merge conflicts. `/lazy-obsidian.iconize-install` adds it to `.gitignore` automatically. If you see it as tracked, run `git rm --cached .obsidian/plugins/obsidian-icon-folder/data.json` — the skill never does this automatically because it is a history-touching action.

---

## Mermaid diagrams look wrong in Obsidian (text invisible, diagram overflowing the column). What should I check?

Run `/lazy-obsidian.diagram-install`. It syncs two CSS snippets (`mermaid-fit.css` and `ascii-fit.css`) into `<vault>/snippets/`, enables them in `appearance.json`, and installs the `mermaid-popup` plugin for click-to-zoom. If the snippets were already installed but snippets are not taking effect, reload Obsidian or click the refresh icon next to each snippet in Settings → Appearance → CSS snippets — Obsidian does not watch `appearance.json` for changes mid-session.

---

## `/lazy-obsidian.diagram-install` failed on `mermaid-popup`. Do I need to re-run the whole thing?

No. The skill treats `mermaid-popup` as non-blocking — the CSS snippets alone cover diagram fit and theme color. Click-to-zoom is unavailable until the plugin is installed, but other rendering is unaffected. Once the network is available, run `/lazy-obsidian.update-plugin mermaid-popup` on its own to finish that part.

---

## How do I install or refresh a single vault plugin without re-running the full setup?

Run `/lazy-obsidian.update-plugin <id>`. It is version-aware: it no-ops when the vault is current, installs when the plugin is missing, and updates when the remote is newer. For plugins bundled inside this LazyCortex plugin (currently `iconize-reloader`), add `--bundled`. Pass `--dry-run` to preview the state tuple without writing anything.

---

## `/lazy-obsidian.update-plugin` aborts with "not in the Obsidian community registry". What happened?

Either the id is misspelled, or you are trying to install a plugin that ships bundled inside this LazyCortex plugin (such as `iconize-reloader`) without the `--bundled` flag. Check the id against the Obsidian community plugins list. For bundled plugins, add `--bundled`.

---

## I ran `/plugin update lazycortex-obsidian@lazycortex`. Do I need to do anything else?

Yes. The plugin update refreshes the plugin cache but does not automatically re-sync rule templates, CSS snippets, or the icon-map template into your consumer repos. Re-run `/lazy-obsidian.install` in each project to pick up any updated templates. If only CSS snippets changed, running `/lazy-obsidian.diagram-install` on its own is sufficient for that part.

---

## Tag pages are not being created. The agent reports a missing template.

The tag-page template at `.claude/templates/obsidian.tag-page-template.md` is scaffolded by `/lazy-obsidian.install`. Run it at project scope, then re-run the `lazy-obsidian.gen-tag-pages` agent. If you have customized the template and want to keep your changes, the install skill merges silently unless there is a genuine same-region conflict.

---

## The audit reports a FAIL about version coherence or the icon-map schema. What should I fix first?

Run `/lazy-obsidian.audit` to see the grouped report. For schema failures (worker version constants mismatching hook templates, or `schema_version` outside the supported set), re-running `/lazy-obsidian.iconize-install` migrates the icon-map in place and brings hook templates up to date. For diagram render glue failures (missing CSS snippets, wrong `mermaid-popup` override block), re-running `/lazy-obsidian.diagram-install` resolves them. The audit presents findings one at a time and asks whether to fix, waive, or skip each.

---

## Can I run this plugin at global scope (`~/.claude/settings.json`) as well as project scope?

You can enable the plugin globally so the skills are available in every project. However, the vault setup steps — Dataview, Iconize, diagram render glue, and the tag-page template — are project-only concerns. Running `/lazy-obsidian.install` at user scope syncs rule templates only; it skips vault setup automatically. To get the full vault setup in a project, run `/lazy-obsidian.install` at project scope in that project's directory.
