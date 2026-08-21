---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-wiki.install
  - lazy-wiki.configure
  - lazy-wiki.doctor
  - lazy-wiki.query
  - lazy-wiki.relink
  - lazy-wiki.structure
  - lazy-wiki.terms
  - lazy-wiki.domains
  - lazy-wiki.domain-sync
source_sha: e758792cb8f978c3f3e230b8233d46a2da076903
---
# Troubleshooting

## `/lazy-wiki.install` aborts: "lazycortex-wiki not enabled"

**Symptom**: Running `/lazy-wiki.install` immediately stops with the message "lazycortex-wiki not enabled — add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins` in your `settings.json` and run `/plugin install lazycortex/lazycortex-wiki`."

**Likely cause**: The plugin is not listed in `enabledPlugins` in your `~/.claude/settings.json`, so the installer cannot locate an entry for `lazycortex-wiki@lazycortex` in the installed-plugins registry.

**Fix**: Add `"lazycortex-wiki@lazycortex": true` under `enabledPlugins` in your global `~/.claude/settings.json`, restart Claude Code, and re-run `/lazy-wiki.install`.

---

## `/lazy-wiki.install` aborts: "lazycortex-core not installed"

**Symptom**: `/lazy-wiki.install` stops with "lazycortex-core not installed; install it before /lazy-wiki.install."

**Likely cause**: The installer could not find `default-tiers.json` from `lazycortex-core` — either the `lazycortex-core` plugin is not enabled, or its cache is absent.

**Fix**: Enable `lazycortex-core` in `enabledPlugins` (same `settings.json`) and restart Claude Code so the cache is populated, then re-run `/lazy-wiki.install`.

---

## `/lazy-wiki.install` aborts: "plugin cache is empty"

**Symptom**: `/lazy-wiki.install` stops with "Plugin cache is empty — run `/plugin update lazycortex-wiki@lazycortex` to refresh."

**Likely cause**: The plugin was enabled in settings but the local cache directory has not been populated, so the rule-file glob found nothing.

**Fix**: Run `/plugin update lazycortex-wiki@lazycortex` in Claude Code to fetch the plugin files, then re-run `/lazy-wiki.install`.

---

## The wiki curator never runs automatically after install

**Symptom**: `/lazy-wiki.install` completes, but nodes never get curated on their own after a commit — the wiki only updates when you run `/lazy-wiki.relink` by hand.

**Likely cause**: The project's background daemon is disabled. Install always registers the curator itself, but the routines that trigger it automatically — one that reacts to changed files, one that prunes links to deleted files, and one that does a weekly full rescan — only fire when the daemon is running, so their registration is skipped while it's off.

**Fix**: Enable the daemon via `/lazy-core.install` (Gate 1), then re-run `/lazy-wiki.install` to register the routines. Until then, use `/lazy-wiki.relink <scope-id>` whenever you want the scope brought up to date.

---

## `/lazy-wiki.configure` aborts: "Run `/lazy-wiki.install` first"

**Symptom**: Starting `/lazy-wiki.configure` produces the message "Run `/lazy-wiki.install` first" or "Run `/lazy-wiki.install` first — the `wiki` section is missing."

**Likely cause**: Either `lazy.settings.json` does not exist in the project yet, or it exists but is missing the top-level `wiki` key that `/lazy-wiki.install` seeds.

**Fix**: Run `/lazy-wiki.install` to create the settings file and seed the `wiki` section, then re-run `/lazy-wiki.configure`.

---

## `/lazy-wiki.configure` keeps re-asking for a scope id

**Symptom**: The scope id prompt repeats without accepting the value you entered.

**Likely cause**: The id you provided doesn't match the required format — it must start with a lowercase letter and contain only lowercase letters, digits, hyphens, or underscores (`^[a-z][a-z0-9_-]*$`). Uppercase letters, spaces, or leading digits cause the wizard to re-ask.

**Fix**: Enter a valid slug, for example `docs`, `codebase`, or `my-notes`.

---

## `/lazy-wiki.configure` keeps re-asking for path globs

**Symptom**: The path globs prompt repeats or rejects your input without saving the scope.

**Likely cause**: At least one path glob is required — a blank entry is not accepted. The wizard loops until a non-empty glob is provided.

**Fix**: Enter at least one path glob, for example `docs/**/*.md` or `src/**/*.py`. Multiple globs can be comma-separated. If you want to cover the whole repo, use `**/*.md` as a starting point and refine later by re-running `/lazy-wiki.configure` in edit mode.

---

## `/lazy-wiki.configure` offers no tag axes to pick from

**Symptom**: While creating a scope, the tag-axes step offers nothing to choose from, and the scope is saved without any axis narrowed from the vault vocabulary.

**Likely cause**: `lazy.settings.json[wiki.tag_axes]` — the vault-wide vocabulary every scope narrows from — is empty, so the wizard has no axis to present.

**Fix**: Run `/lazy-wiki.install` (it unions the mandatory `doc-kind` axis into `wiki.tag_axes`), or run `/lazy-wiki.configure vault` to declare the vocabulary yourself. Then re-run `/lazy-wiki.configure` for the scope so it can pick axes from the populated list.

---

## `/lazy-wiki.configure` keeps re-asking for the topics index path

**Symptom**: The `topics.md` path prompt repeats or rejects your input without saving the scope.

**Likely cause**: A relative file path is required for `topics_index` — a blank entry is not accepted. The file itself doesn't need to exist yet; the wizard only rejects an empty answer.

**Fix**: Enter a relative path for the scope's topic index, for example `wiki/docs-topics.md`. `/lazy-wiki.relink` creates the file on its first run if it doesn't already exist.

---

## `/lazy-wiki.configure` reports `absent` for the navigation-rule Coverage refresh

**Symptom**: `/lazy-wiki.configure` finishes creating or editing a scope, but its Phase 9 outcome reads `absent` instead of `refreshed` or `unchanged` — the Coverage section was not touched.

**Likely cause**: Phase 9 refreshes the `## Coverage` section of the installed `lazy-wiki.navigation` rule, which is what every session reads to decide whether a question must route through `/lazy-wiki.query`. `absent` means neither `<repo-root>/.claude/rules/lazy-wiki.navigation.md` nor `~/.claude/rules/lazy-wiki.navigation.md` exists — the rule itself was never installed, so sessions get no coverage trigger at all, regardless of how many scopes you've configured.

**Fix**: Run `/lazy-wiki.install`, which syncs the `lazy-wiki.navigation` rule into place, then re-run `/lazy-wiki.configure` so Phase 9 can fill in the Coverage section for your configured scopes.

---

## `/lazy-wiki.configure mirror` aborts: "no scopes configured"

**Symptom**: Running `/lazy-wiki.configure mirror` stops immediately, reporting that no scopes are configured.

**Likely cause**: The mirror block configures an existing scope's mirror settings — it nests inside a scope rather than standing on its own, so there must be at least one scope already created before a mirror can be attached to it.

**Fix**: Create the scope first with `/lazy-wiki.configure`, then re-run `/lazy-wiki.configure mirror` to attach the mirror settings (source url/branch, source globs, excludes, mirror directory) to it.

---

## `/lazy-wiki.configure terms` aborts: "the `terms` section is missing"

**Symptom**: Running `/lazy-wiki.configure terms` stops with a message that the `terms` section is missing from `lazy.settings.json`.

**Likely cause**: The project's `lazy.settings.json` predates the terms dictionary mechanism, or `/lazy-wiki.install` has not been re-run since it was added — the top-level `terms` key was never seeded.

**Fix**: Run `/lazy-wiki.install` to seed the `terms` section, then re-run `/lazy-wiki.configure terms` to create your first terms scope.

---

## `/lazy-wiki.configure terms` re-asks for path globs on an overlapping scope

**Symptom**: Entering path globs for a new terms scope re-prompts instead of saving, even though the globs themselves look well-formed.

**Likely cause**: Another terms scope already serves a document matched by the new globs. One document belongs to exactly one dictionary, so an overlap is rejected rather than silently letting a document feed two dictionaries.

**Fix**: Narrow the new scope's globs so they don't overlap an existing terms scope, or edit the colliding scope instead of creating a new one.

---

## A terms scope reports `skipped-daemon-disabled` after `/lazy-wiki.configure terms`

**Symptom**: `/lazy-wiki.configure terms` finishes creating or updating a scope, but the routine-registration outcome reads `skipped-daemon-disabled` instead of `registered`.

**Likely cause**: The project does not run the background daemon, so the routine that dispatches the terms curator on a document change is never registered — the same daemon dependency as the wiki curator's own routines.

**Fix**: `/lazy-wiki.terms` still answers lookups against whatever the dictionary already holds — reading is unaffected. To keep the dictionary itself current without the daemon, run the terms section of `/lazy-wiki.doctor` by hand after documents change, or enable the daemon via `/lazy-core.install` (Gate 1) and re-run `/lazy-wiki.configure terms` to register the routine.

---

## `/lazy-wiki.query` reports "No wiki scopes configured"

**Symptom**: `/lazy-wiki.query "<question>"` exits immediately with "No wiki scopes configured — run `/lazy-wiki.install` and `/lazy-wiki.configure` first."

**Likely cause**: `lazy.settings.json` is absent or `wiki.scopes` is empty — no scope has been defined for this repository.

**Fix**: Run `/lazy-wiki.install` (if not done), then `/lazy-wiki.configure` to define at least one scope, and re-run the query.

---

## `/lazy-wiki.query` returns "No wiki material matched this question"

**Symptom**: The query completes without error but reports "No wiki material matched this question." — no answer, no sources.

**Likely cause**: Either the `topics.md` file for the configured scope does not yet exist on disk (the scope was configured but never linked), or none of the topics in the index are relevant to the question.

**Fix**: Run `/lazy-wiki.relink` for the scope to build the initial `topics.md` and classify and link all nodes in the scope. After the relink completes, re-run the query. If the index already exists but the question genuinely has no coverage, the answer reflects real absence — consider whether the relevant documentation is in scope.

---

## `/lazy-wiki.doctor` reports "no wiki scopes configured"

**Symptom**: Running `/lazy-wiki.doctor` (without a scope id) outputs "no wiki scopes configured" and stops.

**Likely cause**: No scopes have been created yet — `/lazy-wiki.install` ran but `/lazy-wiki.configure` was skipped, so `lazy.settings.json[wiki.scopes]` is empty.

**Fix**: Run `/lazy-wiki.configure` to create at least one scope, then re-run `/lazy-wiki.doctor`.

---

## `/lazy-wiki.doctor` reports "unknown scope '<id>'"

**Symptom**: Running `/lazy-wiki.doctor <id>` outputs "unknown scope '<id>'" and stops.

**Likely cause**: The scope id passed to `/lazy-wiki.doctor` does not match any key in `lazy.settings.json[wiki.scopes]` — it was misspelled, or the scope has not been created yet.

**Fix**: Run `/lazy-wiki.configure` to create a scope with the intended id, or re-invoke `/lazy-wiki.doctor` with a scope id that already exists. The configured scope ids are visible by re-running `/lazy-wiki.configure`, which lists them in edit mode.

---

## `/lazy-wiki.doctor` reports `domain-output-in-scope`

**Symptom**: `/lazy-wiki.doctor` flags a finding named `domain-output-in-scope` for a scope.

**Likely cause**: The scope's `paths` glob reaches into the generated domain-spec tree (`docs/domains/` by default). That tree is excluded from every wiki scope structurally — it's `/lazy-wiki.domain-sync`'s output, not a wiki-curated node — so the glob claims coverage over files nothing there ever populates, and no file ends up with two writers only because the check catches the overlap first.

**Fix**: Narrow the scope's `paths` glob via `/lazy-wiki.configure` so it no longer reaches the domain-spec output directory, and matches only the material the scope is meant to curate.

---

## `/lazy-wiki.relink` reports "unknown scope '<id>'"

**Symptom**: `/lazy-wiki.relink <id>` stops with "unknown scope '<id>'".

**Likely cause**: The scope id is not present in `lazy.settings.json[wiki.scopes]` — it was not created with `/lazy-wiki.configure`, or was removed.

**Fix**: Run `/lazy-wiki.configure` to define the scope, then re-run `/lazy-wiki.relink <id>`.

---

## `/lazy-wiki.relink` produces `anchor-lost` mode unexpectedly

**Symptom**: The relink report shows `planned:anchor-lost` rather than `planned:incremental`, and processes many more nodes than expected.

**Likely cause**: The `wiki_synced_sha` anchor commit became unreachable — typically because of a rebase, `git reset --hard`, a squash, a `git gc`, or a shallow clone that pruned the commit the anchor pointed to. The planner falls back to a content-hash backstop (`wiki_src_hash`) to determine what needs relinking.

**Fix**: This is expected recovery behaviour, not an error. Let the relink complete normally — it will process the nodes identified by the content-hash backstop and write a fresh anchor at the current HEAD when it commits. Future incremental relinking will work from this new anchor.

---

## A curator subagent errors during `/lazy-wiki.relink` and a node is skipped

**Symptom**: During `/lazy-wiki.relink`, the skill reports one or more nodes as skipped with a curator error, then continues. The skipped nodes are not classified or linked.

**Likely cause**: The curator subagent encountered a problem applying curation to a specific node — for example, a malformed `apply-node` input, a schema violation in the node's existing wiki frontmatter, or a file the curator could not read.

**Fix**: The remaining nodes in the run are unaffected. The skipped node will be picked up automatically on the next `/lazy-wiki.relink` run (it will appear in the plan's `classify[]` or `link[]` set again). If the same node is skipped repeatedly, inspect that node's wiki frontmatter for unexpected values and run `/lazy-wiki.doctor` to surface any `broken-wiki-block` findings.

---

## `/lazy-wiki.relink` Step 6 reports "unchanged" and creates no commit

**Symptom**: The relink run completes all steps but reports `unchanged` at Step 6 — no commit is created.

**Likely cause**: An idempotent re-run produced no byte changes to any node or `topics.md`. This happens when the scope is already fully in sync, or when the run's classify and link work yielded no mutations (e.g. nodes were already curated at the same content hash).

**Fix**: No action needed. The scope is in sync. If you expected changes, verify that the target nodes fall within the scope's path globs by re-running `/lazy-wiki.configure` in edit mode to review the configured glob patterns.

---

## A deleted node's See-also links linger in other nodes

**Symptom**: You deleted a node file, but other nodes in the scope still carry a "See also" link pointing at the now-missing path.

**Likely cause**: Nothing has pruned the dangling link yet. When the background daemon is running, deletions are picked up automatically — a dedicated routine watches for deleted files and, on its next poll, drops the dangling See-also lines and rebuilds `topics.md`. Without the daemon, or before its next poll, no automatic pass has happened.

**Fix**: With a running daemon, wait for the next poll (roughly a minute) — the deletion is pruned and committed on its own. Without a daemon, run `/lazy-wiki.relink <scope-id>`, whose pruning step drops links to any deleted nodes as part of the normal relink pass. You can also run `/lazy-wiki.doctor <scope-id>` and confirm the fixable "broken See-also" finding, which drops the dangling lines directly.

---

## `/lazy-wiki.structure` (or `/lazy-wiki.configure structure`) aborts: "No `structure` section"

**Symptom**: Running `/lazy-wiki.structure rebuild` or `/lazy-wiki.structure query` stops immediately with a message that the `structure` section is missing.

**Likely cause**: `lazy.settings.json` has no top-level `structure` key — the project-structure map was never set up in this repository.

**Fix**: Run `/lazy-wiki.configure structure` to collect depth profiles and exclusions and write the section, then re-run `/lazy-wiki.structure rebuild` to build the initial map.

---

## `/lazy-wiki.structure query` reports "No structure map yet"

**Symptom**: `/lazy-wiki.structure query [<path>]` reports that no map exists yet, instead of returning a slice of `docs/structure.md`.

**Likely cause**: The `structure` section is configured, but `docs/structure.md` has never actually been generated — the git-watch routines only keep an existing map current, they never create it.

**Fix**: Run `/lazy-wiki.structure rebuild` once to walk the tracked tree and write the initial map. After that, the query mode and the routines both work against a real file.

---

## `/lazy-wiki.structure query <path>` reports "`<path>` is not in the map"

**Symptom**: Querying a specific path returns "not in the map" even though the file clearly exists in the repository.

**Likely cause**: The path is new since the map was last built, it matches an `exclude` glob in `lazy.settings.json[structure]`, or the map is otherwise stale relative to the tree.

**Fix**: Run `/lazy-wiki.structure rebuild` to resync the map with the current tree, or check the `exclude` list via `/lazy-wiki.configure structure` if the path is being deliberately left out.

---

## `/lazy-wiki.domains` reports "Domain service not configured"

**Symptom**: `/lazy-wiki.domains` stops with a message that the domain service is not configured, instead of returning a matched slice of the domain-spec tree.

**Likely cause**: `wiki.domains` is absent from `lazy.settings.json`, or it's configured but the domain-spec tree has never actually been generated.

**Fix**: Run `/lazy-wiki.configure domains` to set the code globs, dictionary path, output tree, and language, then run `/lazy-wiki.domain-sync` (or wait for the daemon routine) to generate the tree, and re-run the query.

---

## `/lazy-wiki.domains` group query reports "not in the domain tree"

**Symptom**: Looking up a group key returns that it's not in the domain tree.

**Likely cause**: The group key is new, the tree hasn't been regenerated since it was introduced in code, or the key is misspelled.

**Fix**: Check `<output>/domains.md` (`docs/domains/domains.md` by default) for the current list of generated groups, correct the key, or run `/lazy-wiki.domain-sync` to pick up a newly introduced group.

---

## `/lazy-wiki.domains` group query reports "not a section of this doc"

**Symptom**: Asking for a specific section (e.g. `Contracts`) of a group's generated doc returns that the section isn't present.

**Likely cause**: `Terms`, `Principles`, and `Mechanics` always exist on a generated group doc, but `Contracts` exists only when the code's `Domain(…)` blocks for that group carry attributed `Contract:` annotations. Asking for `Contracts` on a group with none legitimately fails.

**Fix**: Re-query with a section that's actually present on that doc — the failure names the sections it does have, so check that list first.

---

## `/lazy-wiki.domains` term query reports "not found"

**Symptom**: Looking up a specific term across the domain tree returns that it wasn't found anywhere.

**Likely cause**: The term genuinely isn't referenced in any generated doc yet, or the tree is stale relative to the code's `Domain(…)` blocks.

**Fix**: Run `/lazy-wiki.domain-sync` to refresh the tree from the current code, then re-run the term query.

---

## `/lazy-wiki.domain-sync` exits saying `wiki.domains` is not configured

**Symptom**: Running `/lazy-wiki.domain-sync` exits non-zero immediately, reporting that `wiki.domains` is not configured.

**Likely cause**: The `wiki.domains` section is missing from `lazy.settings.json` — domain-spec generation was never set up for this repository.

**Fix**: Run `/lazy-wiki.configure domains` to set code globs, dictionary path, output tree, and language, then re-run `/lazy-wiki.domain-sync`.

---

## `/lazy-wiki.domain-sync` reports groups under `unknown_groups`

**Symptom**: The `/lazy-wiki.domain-sync` report lists one or more groups under `unknown_groups` instead of generating or updating their docs.

**Likely cause**: Code carries `Domain(<group>)` markers whose group name isn't in the dictionary yet — a genuinely new group, a block still filed under `Domain(unfiled):`, or a dictionary rename that left the old group name behind in code.

**Fix**: For one or two groups, add the group to the dictionary by hand and re-run `/lazy-wiki.domain-sync`. When several groups are reported at once, or the blocks sit under `unfiled`, run `/lazy-python.knowledge-sweep` instead — it grows the dictionary with you and refiles the code's blocks under the accepted group names before the next sync. `/lazy-wiki.doctor` also flags this condition.

---

## `/lazy-wiki.domain-sync` drops a doc under `unlisted_docs`

**Symptom**: A previously generated group doc under the output tree disappears after a `/lazy-wiki.domain-sync` run, and the run's report lists it under `unlisted_docs`.

**Likely cause**: The group was renamed or removed from the dictionary since the doc was last generated, so the doc is no longer regenerable and the sync run removed it as orphaned.

**Fix**: If the removal was unintentional, restore the group key in the dictionary and re-run `/lazy-wiki.domain-sync` to bring the doc back. If the rename was intentional, let `/lazy-python.knowledge-sweep` refile the code's `Domain(…)` blocks under the new group name so the doc regenerates under its new identity.

---

## A `/lazy-wiki.domain-sync` writer subagent errors and a group is skipped

**Symptom**: During `/lazy-wiki.domain-sync`, one or more groups are reported as skipped with a writer error, and their docs are not updated this run.

**Likely cause**: The domain-spec writer hit an unreadable source file or malformed dispatch data for that group.

**Fix**: The remaining groups in the run are unaffected. The skipped group is re-detected and retried on the next `/lazy-wiki.domain-sync` run — no manual intervention is needed unless the same group keeps failing, in which case check that the source files its `Domain(…)` blocks live in are readable.
