---
chapter_type: faq
summary: Answers to common questions about vault setup, Iconize, diagram render glue, the vault manifest, plugin updates, and tag pages for lazycortex-obsidian.
last_regen: 2026-09-11
no_diagram: true
source_skills:
  - lazy-obsidian.install
  - lazy-obsidian.iconize-install
  - lazy-obsidian.iconize-config
  - lazy-obsidian.iconize-sync
  - lazy-obsidian.diagram-install
  - lazy-obsidian.gen-tag-pages
  - lazy-obsidian.update-plugin
  - lazy-obsidian.audit
  - lazy-obsidian.capture
  - lazy-obsidian.deploy
source_sha: 5a28d4bdd32d8e9cead0b771ea95d2cee4c8c212
---
# Frequently asked questions

## Do I need to run anything after enabling the plugin, or does it self-configure?

You need to run `/lazy-obsidian.install` once per project after enabling the plugin. Enabling adds the skills to Claude Code, but the vault setup — Dataview installation, Iconize scaffolding, CSS snippets, and diagram render glue — runs only when you invoke that skill. It is idempotent, so running it again after a `/plugin update` is safe and picks up any template or CSS changes.

---

## `/lazy-obsidian.install` aborted saying the plugin is not installed. What happened?

The skill looks for a `lazycortex-obsidian@lazycortex` entry in `~/.claude/plugins/installed_plugins.json`. If that entry is absent or empty, the skill stops rather than guessing the paths. Add `"lazycortex-obsidian@lazycortex": true` under `enabledPlugins` in your `settings.json`, restart Claude Code, then re-run `/lazy-obsidian.install`.

---

## `/lazy-obsidian.install` says "plugin cache is empty". How do I fix it?

The plugin cache is the installed copy of the plugin's files. An empty cache usually means the initial download did not complete. Run `/plugin update lazycortex-obsidian@lazycortex` to refresh the cache, then re-run `/lazy-obsidian.install`.

---

## I ran `/lazy-obsidian.install` but icons are not showing up in Obsidian. What should I check?

Icons are painted by Iconize reading `iconize_icon` and `iconize_color` from each note's frontmatter. Four things are required: Iconize's `iconInFrontmatterEnabled` setting must be `true` with the field names set to `iconize_icon` and `iconize_color` (asserted automatically by `/lazy-obsidian.iconize-install`), the icon-map at `.claude/iconize/obsidian-icon-map.json` must have matchers that cover your notes, the note's path must fall under one of the icon-map's `paint_roots` (see the question below if it doesn't), and `/lazy-obsidian.iconize-sync reconcile` must have been run to write the frontmatter. If the matchers are missing entries, run `/lazy-obsidian.iconize-config` to add them, then run `/lazy-obsidian.iconize-sync reconcile` to apply.

---

## Why does the icon frontmatter land in a separate commit after the one I just made?

Nothing repaints inside your commit: no hook stages into your index behind your back. Icons follow each note as it is written (the PostToolUse hook), and after a commit lands, the `lazy-obsidian.repaint` daemon routine repaints the affected directories and commits the result itself. If you want the fresh frontmatter folded into the commit you are about to make, run `/lazy-obsidian.iconize-sync reconcile` (or `reconcile-dirty`) before staging, then commit as usual.

---

## I upgraded the plugin and my repaint routine still behaves the old way. Do I need to re-register it by hand?

No — re-running `/lazy-obsidian.iconize-install` fixes it for you. The `lazy-obsidian.repaint` routine's `command`, `watch`, `ignore_halt`, and `git_author` fields are entirely composed by the plugin, so the skill now reads the registered routine back and compares it against what the current version would write; a mismatch (left over from an older plugin version) is refreshed silently — unregistered and re-registered — while your own `interval_sec` tuning is carried over untouched. The report line reads **refreshed** instead of the older **already-present** when this happens. No prompt, no manual `lazy-routine.unregister` / `lazy-routine.register` needed.

---

## After upgrading, the `lazy-obsidian.repaint` entry disappeared from `experts` in my `lazy.settings.json`. Is that a bug?

No — `/lazy-obsidian.iconize-install` removed it on purpose. Earlier plugin versions seeded the repaint routine's identity twice: once as the routine's own `git_author` (see the question above), and again as a duplicate `experts["lazy-obsidian.repaint"]` entry, because sibling coordinators used to recognize bot commits only by walking the `experts` table. They now read the routine registry too, so the duplicate is dead weight — and worse, an `experts` entry with no `agent` field permanently fails core's expert preflight, since nothing serves it as a role. Re-running `/lazy-obsidian.iconize-install` deletes that leftover key (report line **identity-pruned**) and leaves the routine's own `git_author` as the single record; a vault that never carried the duplicate reports **identity-absent** instead. Repaint commits are still recognized as bot commits either way — nothing about the previous question's behavior changes.

---

## I upgraded the plugin and my `.githooks/pre-commit` file is gone. Did something delete it?

Yes, intentionally. Versions of `lazy-obsidian.iconize-install` up to 2.x installed a pre-commit shim at `.githooks/pre-commit` and pointed `core.hooksPath` at `.githooks` so icons repainted before each commit. That approach is retired: commit-time repaint now belongs to the `lazy-obsidian.repaint` daemon routine, and the shim's old `sync-staged` subcommand no longer exists — a leftover shim would fail silently on every commit instead of doing anything useful. When you re-run `/lazy-obsidian.iconize-install` after upgrading, it detects the shim by its `HOOK_VERSION:` marker (proof the file is the plugin's own, never a hand-customized one), deletes it, and unsets `core.hooksPath` if `.githooks/` is now empty. A shim without that marker is left alone as foreign. Nothing else changes — icons still repaint the way the answer above describes.

---

## How do I add a new icon rule for a folder or file type?

Run `/lazy-obsidian.iconize-config`. The wizard walks you through picking a registry, then adding a key with an icon name (Lucide PascalCase with `Li` prefix, or an emoji) and an optional color. After saving, run `/lazy-obsidian.iconize-sync reconcile` so the new rule is applied across all notes.

---

## Why didn't a note's icon go away after I removed its matching rule?

That's expected: `reconcile` and `sync` only rewrite a note when its resolved icon actually changes to a new value. A note that no matcher claims any more keeps whatever `iconize_icon` / `iconize_color` it already carries — no subcommand strips those keys automatically, because another manager could have written them and a blind clear would destroy that. If you want the icon gone, remove the two keys from the note's frontmatter by hand.

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

## Why don't the templates under a plugin's `templates/` tree (or my vault's `.claude/templates/`) ever get icons?

Iconize-sync never paints a template tree, on purpose. A scaffolding template — a plugin's own `claude/<plugin>/templates/**`, or the consumer-side `.claude/templates/**` override tree — carries the same frontmatter shape as the notes it scaffolds, so a frontmatter-keyed matcher would fire on the template itself. Painting it would dirty a shipped source file on every reconcile and bake a stale icon into every note scaffolded from it afterwards. So every path under a template tree resolves to no match, and `reconcile` never even enumerates it. This exemption applies even inside a directory that is otherwise open to painting.

If you upgraded from a version that predates this behavior, a template may still carry stale `iconize_icon` / `iconize_color` keys painted by an earlier worker run — no-match keeps frontmatter rather than stripping it, so nothing removes them automatically. Strip the two keys by hand from the affected `.md` files under your template trees once; notes scaffolded from them afterwards then take their icon from the matchers as expected.

---

## Why are icons only painted under `specs/` and not across the rest of the vault?

Painting is scoped by `paint_roots`, a top-level key in `.claude/iconize/obsidian-icon-map.json` listing the repo-relative directory prefixes the worker is allowed to touch. Outside those prefixes the worker never reads or writes a note at all — no matcher runs, no frontmatter is parsed, nothing is written, and any `iconize_icon` / `iconize_color` the note already carries (for example one written by a sibling plugin) is left exactly as it stands. A prefix claims a path only across a directory boundary, so `specs` covers `specs/product/design.md` but never `specsheets/design.md`.

`/lazy-obsidian.iconize-install` seeds this key on a fresh icon-map, and adds it to an existing one that does not carry it yet, with a single entry: your spec content root from `spec.vault_root` in `.claude/lazy.settings.json`, defaulting to `specs` when that setting is absent. An icon-map already carrying an authored `paint_roots` is never rewritten. To paint additional areas of the vault, add more prefixes to the `paint_roots` array by hand — `/lazy-obsidian.iconize-config` manages registry entries, not this key. Narrowing the list later does not clean up icons already painted in an area it no longer covers; removing those is a manual edit. If your icon-map predates this key entirely and you have not re-run `/lazy-obsidian.iconize-install` since, `paint_roots` stays absent and the whole vault remains in scope, exactly as before.

---

## Mermaid diagrams look wrong in Obsidian (text invisible, diagram overflowing the column). What should I check?

Run `/lazy-obsidian.install`. Its shared snippet step syncs three CSS snippets — `mermaid-fit.css`, `ascii-fit.css`, and `callouts.css` — into `<vault>/snippets/` and enables all of them with a single `appearance.json` write; `mermaid-fit.css` and `ascii-fit.css` are the ones that fit diagrams to the editor column and pick up the theme text color. If the snippets were already installed but are not taking effect, reload Obsidian or click the refresh icon next to each snippet in Settings → Appearance → CSS snippets — Obsidian does not watch `appearance.json` for changes mid-session. For click-to-zoom specifically, see the next question — that part is handled separately by `/lazy-obsidian.diagram-install`.

---

## `/lazy-obsidian.diagram-install` failed on `mermaid-popup`. Do I need to re-run the whole thing?

No. `/lazy-obsidian.diagram-install` today only installs the `mermaid-popup` click-to-zoom plugin — it declares the fit-CSS snippets but does not install or enable them (that is `/lazy-obsidian.install`'s shared snippet step, so there is a single writer of `appearance.json`'s snippet array). So a `mermaid-popup` failure does not affect diagram fit or theme color at all; those keep working via the CSS snippets alone once `/lazy-obsidian.install` has enabled them. Click-to-zoom is unavailable until the plugin installs, but nothing else is affected. Once the network is available, run `/lazy-obsidian.update-plugin mermaid-popup` on its own to finish that part.

---

## How do I install or refresh a single vault plugin without re-running the full setup?

Run `/lazy-obsidian.update-plugin <id>`. It is version-aware: it no-ops when the vault is current, installs when the plugin is missing, and updates when the remote is newer. For plugins bundled inside this LazyCortex plugin (currently `iconize-reloader`), add `--bundled`. Pass `--dry-run` to preview the state tuple without writing anything.

---

## `/lazy-obsidian.update-plugin` aborts with "not in the Obsidian community registry". What happened?

Either the id is misspelled, or you are trying to install a plugin that ships bundled inside this LazyCortex plugin (such as `iconize-reloader`) without the `--bundled` flag. Check the id against the Obsidian community plugins list. For bundled plugins, add `--bundled`.

---

## I ran `/plugin update lazycortex-obsidian@lazycortex`. Do I need to do anything else?

Yes. The plugin update refreshes the plugin cache but does not automatically re-sync rule templates, CSS snippets, or the icon-map template into your consumer repos. Re-run `/lazy-obsidian.install` in each project to pick up any updated templates — including the CSS snippets, since `/lazy-obsidian.install`'s shared snippet step is the one writer of `appearance.json`'s enabled-snippets array. That step also drops any `enabledCssSnippets` entry naming a snippet this plugin used to ship and no longer does — the dead file was removed from the vault but the array entry stayed, so a stale pointer no longer lingers after an upgrade that retires a snippet; the report line reads **retired: `<name>`** when that happens. If only the `mermaid-popup` override changed, running `/lazy-obsidian.diagram-install` on its own is sufficient for that part.

---

## How do I share my vault's Obsidian configuration across machines or with teammates?

Run `/lazy-obsidian.capture` after changing anything under `.obsidian/` — a plugin installed, a setting tweaked, a snippet added, the theme switched. It snapshots the whole `.obsidian/` surface into one tracked, reviewable file, `.obsidian.manifest.json`, and commits it. On any other checkout — a fresh clone, a machine that has never opened this vault — run `/lazy-obsidian.deploy`, which reads that manifest and rebuilds `.obsidian/`: every plugin fetched at its latest release, your captured settings layered on top, snippets, and top-level config files. A theme it only names — install that once from Obsidian's Appearance settings. Deploy always ends with a reminder to open Obsidian once, since plugins run their own settings migrations on first launch. Both skills take an optional positional argument for the repo root; omit it and they use the current repo.

---

## Why does `/lazy-obsidian.capture` list some settings as "omitted" instead of recording them?

That is deliberate, not an error. The manifest worker refuses to write anything that looks like a secret — an API key, a password — into `.obsidian.manifest.json`, because the manifest is a tracked, committed file. The `secrets_omitted` list names exactly what was left out; enter each of those values by hand in Obsidian on any machine you deploy the manifest to. `/lazy-obsidian.deploy` surfaces the same list in its own report as a reminder.

---

## I already track `.obsidian/**` directly in git. Do I need to switch to the manifest?

Not required, but recommended — a hundred-odd files, several of them rewritten wholesale by the mobile app or by a plugin's own schema migrations, invite merge conflicts on files nobody meant to touch by hand. `/lazy-obsidian.capture` never untracks `.obsidian/` or edits `.gitignore` for you; it only tells you, once, in its summary, the two commands for the one-time migration: add `.obsidian/` to `.gitignore`, then `git rm -r --cached .obsidian`. Run those by hand when you're ready, then rely on capture/deploy going forward.

---

## `/lazy-obsidian.deploy` says a plugin was "served from cache" instead of the latest release. Is that a problem?

Only temporarily. It means GitHub was unreachable, or the plugin's latest release lacked the expected binary assets, so deploy fell back to a vendored copy instead of failing outright. Re-run `/lazy-obsidian.deploy` later once the network is back to pull the real latest release. Nothing else about the deployed vault is affected in the meantime.

---

## Tag pages are not being created. The agent reports a missing template.

The tag-page template at `.claude/templates/lazy-obsidian.tag-page-template.md` is scaffolded by `/lazy-obsidian.install`. Run it at project scope, then re-run the `lazy-obsidian.gen-tag-pages` agent. If you have customized the template and want to keep your changes, the install skill merges silently unless there is a genuine same-region conflict.

---

## The audit reports "vault manifest drift". What does that mean?

`/lazy-obsidian.audit` compares your live `.obsidian/` config against `.obsidian.manifest.json`, but only when that manifest exists — a vault that has never run `/lazy-obsidian.capture` is skipped with outcome `no-manifest`, which is not a failure. When drift is found, it means the live vault and the recorded manifest disagree, and the audit never guesses which side is right — it presents each entry and lets you choose: run `/lazy-obsidian.capture` if the live vault is correct and should be recorded, or `/lazy-obsidian.deploy` if the manifest is correct and the live vault should be restored from it. A separate `warnings` list (not drift) covers things like a plugin whose installed version moved past what its settings were captured under, or credentials the manifest can never carry.

---

## Does `/lazy-obsidian.audit` check anything besides vault-manifest drift?

No — it is scoped to that one check. Earlier versions also verified the plugin's own shipped artifacts (worker version constants, icon-map template schema, protocol docs, CSS snippet contracts); those checks now live in the plugin maintainer's own tooling, not in a skill you run against your vault. If you hit a problem that looks like a shipped-artifact defect rather than vault drift — icons stop painting, snippets are missing, the icon-map is rejected as the wrong schema — the fix is still `/lazy-obsidian.install` or `/lazy-obsidian.iconize-install`, not `/lazy-obsidian.audit`; see the questions above for icons, snippets, and the icon-map.

---

## Can I run this plugin at global scope (`~/.claude/settings.json`) as well as project scope?

You can enable the plugin globally so the skills are available in every project. However, the vault setup steps — Dataview, Iconize, CSS snippets, diagram render glue, and the tag-page template — are project-only concerns. Running `/lazy-obsidian.install` at user scope syncs rule templates only; it skips vault setup automatically. To get the full vault setup in a project, run `/lazy-obsidian.install` at project scope in that project's directory.
