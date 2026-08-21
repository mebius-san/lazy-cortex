---
chapter_type: block
summary: Bootstrap and maintain lazycortex-wiki — install, configure scopes plus vault-wide axes/domains/mirror/terms/structure, and audit everything for integrity.
last_regen: 2026-08-19
diagram_spec:
  anchor: "How the setup flow connects"
  request: "Flow diagram showing the install-and-audit lifecycle: lazy-wiki.install seeds the wiki/structure/terms settings sections (wiki carries a repository-wide tag_axes vocabulary seeded empty and an exclude list seeded with docs/structure.md), unions the doc-kind axis into that repository-wide vocabulary, composes the wiki.curator, wiki.terms-curator, and wiki.structure-curator experts unconditionally, and (daemon-gated) registers lazy-wiki.scan, lazy-wiki.scan-deletes, lazy-wiki.relink-weekly, and lazy-wiki.doctor-apply — plus the wiki.domain-writer expert and its two domain routines when wiki.domains is configured, and one lazy-wiki.mirror-sync.<scope-id> routine per scope carrying a mirror block → lazy-wiki.configure's six branches (default scope branch, domains, mirror, terms, structure, vault) each collect their own config one question at a time and write it into lazy.settings.json — the scope branch only narrows the vault's tag_axes vocabulary and adds exclusions on top of the vault's own exclude list, both edited directly via the vault branch — refreshing the navigation rule's Coverage section wherever scope paths changed → lazy-wiki.doctor audits the wiki scopes via the CLI, then (report-only) the terms scopes and the structure map by reading plus a curator dispatch in report mode, and applies only the fixable repairs after the operator confirms."
source_skills:
  - lazy-wiki.install
  - lazy-wiki.configure
  - lazy-wiki.doctor
source_sha: e758792cb8f978c3f3e230b8233d46a2da076903
---
# Bootstrap and maintain lazycortex-wiki

Getting `lazycortex-wiki` running in a project takes three ordered moves: install the plugin infrastructure, configure at least one scope — and, as you need them, the plugin's other facilities (the vault-wide axis vocabulary and exclusion list, domain-spec generation, a mirrored foreign repo, a terms dictionary, the project-structure map) — then audit everything to confirm it stays coherent. After setup these same three skills remain your go-to tools whenever you add a scope, wire up a new facility, onboard a new contributor, or want a health check after a large restructure.

## When you'd use this

- Starting fresh: you've enabled the plugin and want the git-watch and weekly-scan routines running, the `wiki.curator` (plus `wiki.terms-curator` and `wiki.structure-curator`) experts composed, and the navigation and structure rules synced.
- Adding a new scope to an existing install: run `/lazy-wiki.configure` to define the path globs, which axes of the vault's vocabulary this scope uses, exclude globs beyond the repository-wide list, the topics-index path, and the review-skip filter for the new area without touching the existing scopes. The mandatory `doc-kind` classification axis is already in the vault's vocabulary for you — it is never something you type in.
- Growing or trimming the vault's tag axis vocabulary, or the exclusions every scope inherits: run `/lazy-wiki.configure vault` to edit `tag_axes` and `exclude` directly, rather than through any one scope.
- Turning on domain-spec generation: run `/lazy-wiki.configure domains` to point the wiki at your code's `Domain(…)` markers and a dictionary of domain groups, so a docs tree gets generated and kept current.
- Mirroring a foreign repo's markdown into the vault: run `/lazy-wiki.configure mirror` against an existing scope so the mirrored files become ordinary wiki nodes, curated like anything local.
- Setting up a terms dictionary: run `/lazy-wiki.configure terms` so the documents in a scope share one agreed word per concept instead of drifting onto synonyms.
- Wiring the project-structure map: run `/lazy-wiki.configure structure` to define depth profiles and exclusions so three routines keep `docs/structure.md` current as files move.
- Verifying integrity after a large refactor or import: run `/lazy-wiki.doctor` to surface orphan topics, broken See-also links, stale glosses, and index desync in the wiki scopes — plus terminology drift in any terms dictionary and divergence in the structure map — before they accumulate.

## How it fits together

`/lazy-wiki.install` is the foundation. It detects whether the plugin is enabled at project or user scope, resolves the path for `lazy.settings.json`, creates the `~/.claude/templates/wiki/` (or `.claude/templates/wiki/`) directory, and syncs both rules the plugin ships — `lazy-wiki.navigation` and `lazy-wiki.structure` — into the consumer's rules directory. It seeds the `wiki`, `structure`, and `terms` settings sections (each idempotent — never overwritten once present); the `wiki` section carries a repository-wide axis vocabulary (`tag_axes`, seeded empty) that every scope only ever narrows from, and a repository-wide exclusion list (`exclude`, seeded with `docs/structure.md`) that every scope's own exclusions sit on top of — neither is a per-scope list. Install unconditionally unions the `doc-kind` classification axis, the mandatory dimension that says what a node is by form (`design`, `skill`, `rule`, …), into that repository-wide vocabulary — this runs again on every re-install, so the axis is already there before any scope exists, and a scope reaches it by narrowing the vault's vocabulary rather than declaring its own. It seeds agent-model tier entries for the curators and the domain-spec writer from `lazycortex-core`'s defaults, and composes three curator experts unconditionally — `wiki.curator`, `wiki.terms-curator`, and `wiki.structure-curator` (the latter two carry `can_commit_in_repo: true`, since they write the dictionary and the structure map directly into the working tree). Only the **routines** are gated on whether the project runs the background daemon: when the gate is open, install registers a git-watch routine (`lazy-wiki.scan`) that processes changed files on every commit, a companion (`lazy-wiki.scan-deletes`) that prunes See-also links pointing at deleted nodes and rebuilds the topic index, a weekly full-scan (`lazy-wiki.relink-weekly`), and a daily sanitizer (`lazy-wiki.doctor-apply`) that applies only the doctor's pure index/link repairs across every scope and commits what it fixed. When `wiki.domains` is configured, install additionally composes the `wiki.domain-writer` expert and — daemon permitting — registers the two domain routines (`lazy-wiki.domain-scan` on every commit, `lazy-wiki.domain-full` weekly as insurance against a missed wake). For every scope carrying a `mirror` block, install registers that scope's own `lazy-wiki.mirror-sync.<scope-id>` schedule routine. As part of the install, it adds `Bash(lazycortex-wiki *)` to the project's `settings.local.json` allow-list so curator subprocesses dispatched by the daemon's `dontAsk` permission mode can reach the plugin CLI without being silently denied. The skill is idempotent: re-running it never overwrites values you've already customised, and if no scopes exist yet it points you at `/lazy-wiki.configure` rather than launching it for you.

`/lazy-wiki.configure` is the wizard, and it has grown six mutually exclusive branches — the plain invocation edits a **scope**; `domains`, `mirror`, `terms`, `structure`, and `vault` configure the plugin's other facilities. Every branch collects one question at a time and orients you first with a short summary of what it governs, so you're never answering in vocabulary you haven't seen defined.

- **Scope branch** (`/lazy-wiki.configure`) — the one you run first. It walks you through the scope id, path globs (markdown, code, or both), exclude paths beyond the repository-wide `wiki.exclude` list, which of the vault's tag axes this scope narrows to (leave it blank and the scope speaks the whole vocabulary — a scope can only narrow the vault's axes, never widen them or invent one of its own), the `topics.md` index path, and the review-skip filter (documents currently under review, `review_active: true`, are left out of curation until review closes — default yes). A `folder_note: false` sub-filter is seeded automatically alongside it: a note named after its own folder is a navigation node, not a document, and stays out of the wiki on every path. Re-running with the same id enters edit mode. After writing the scope, it refreshes the `## Coverage` section of the installed `lazy-wiki.navigation` rule — one bullet per scope built from that scope's `paths`/`exclude_paths` — and commits the rule when it's tracked.
- **Domains branch** (`/lazy-wiki.configure domains`) — sets `wiki.domains`: which code globs to scan for `Domain(…)` markers, the path of the domain-groups dictionary (seeded from a skeleton template if it doesn't exist yet), the output directory for the generated docs tree, and the language to write them in (detected from your existing specs and offered as the default). It warns when a configured wiki scope's globs already reach the output directory, since the tree is excluded from every scope structurally and such a glob claims nothing there.
- **Mirror branch** (`/lazy-wiki.configure mirror`) — nests a `mirror` block inside an **existing** scope: the source repo's git URL and branch, which markdown globs to pull (plus excludes for the source's own service files), and the vault directory the mirror lands in. It adds `<mirror_path>/**` to that scope's `paths` automatically, so the mirrored files become curated nodes without a second configuration step, and refreshes the navigation rule's Coverage the same way the scope branch does.
- **Terms branch** (`/lazy-wiki.configure terms`) — create, edit, or remove one scope of the `terms` section: which documents the dictionary serves, where the dictionary file lives (created empty if absent, never truncated if it exists), and `source_exclude` — documents the dictionary still serves but never learns terms from (the dictionary itself, the standard tool-report globs, and optionally plan documents). It refuses a `paths` overlap with another terms scope up front, since one document can only belong to one dictionary, and automatically adds the dictionary file to any wiki scope's `exclude_paths` that would otherwise cover it. It also registers the scope's own `lazy-wiki.terms-scan-<id>` git-watch routine (daemon-gated).
- **Structure branch** (`/lazy-wiki.configure structure`) — sets `depth_profiles` (named classes of globs, each with a depth of `file`, `dir`, or `brief`) and the `exclude` list for the fixed-path project-structure map, `docs/structure.md` (which is always kept in its own exclude list, so the map never describes itself). It registers three git-watch routines — for changed, deleted, and renamed files — since `renamed_files` exposes different placeholders than the other two and needs its own request template.
- **Vault branch** (`/lazy-wiki.configure vault`) — edits the two repository-wide keys directly rather than through any one scope: `tag_axes`, the closed axis vocabulary the whole vault classifies against, and `exclude`, the glob list unioned into every scope's `exclude_paths`. `doc-kind` and `docs/structure.md` stay put no matter what you type — dropping either here is undone by the next `/lazy-wiki.install` run — and removing any other axis is flagged before it's written, since every node already tagged on that axis goes unknown and every scope narrowed to it silently loses it.

`/lazy-wiki.doctor` audits a single scope or every configured wiki scope, and — in the same run — the terms dictionaries and the structure map, if either is configured. For wiki scopes it surfaces findings at three severities (`FAIL`, `WARN`, `INFO`) and labels which are fixable: orphan topics and index desync (repaired by rebuilding the topic index), non-canonical See-also link paths (rewritten to the canonical target), broken See-also lines (dropped), and stale glosses (refreshed). Everything else — including the domain-generation checks (a stale hash, an unknown group, a missing gloss, a scope glob reaching the structurally-excluded output tree) and the mirror checks (an orphaned clone, local edits a sync would overwrite, `paths` not covering `mirror_path`) — is report-only. For terms scopes and the structure map, the audit pairs two kinds of check: configuration and format problems the skill judges directly by reading (a missing dictionary file, overlapping scope globs, a routine whose filter no longer matches, `docs/structure.md` missing from the repository-wide `wiki.exclude` while some scope's `paths` still cover it), and meaning problems it hands to the owning curator in report mode — `wiki.terms-curator` returns divergence / missing / duplicate / dead terms, `wiki.structure-curator` returns entries the map and the tree disagree on. Neither curator writes anything in this mode. After showing every finding, the skill asks whether to apply the fixable wiki repairs; terms and structure findings are never batch-applied — each is decided with you one at a time, since which word is "right" is a judgment call, not a default, and a document under active review or inside an upstream mirror is never touched either way.

## Common adjustments

**Changing a scope's path globs, which vault axes it narrows to, or its review-skip filter** — run `/lazy-wiki.configure` again with the same scope id. Edit mode shows the current values so you can update only what you need; the navigation rule's Coverage section refreshes to match automatically.

**Growing, trimming, or renaming the vault's tag axis vocabulary, or its repository-wide exclusions** — run `/lazy-wiki.configure vault`; it shows the current `tag_axes` and `exclude`, keeps `doc-kind` and `docs/structure.md` in place regardless of what you type, and warns you before writing a set that drops an axis some node already carries.

**Adjusting domain-spec generation** — run `/lazy-wiki.configure domains` again; it shows the current code globs, dictionary path, output directory, and language and lets you change any of them.

**Changing a mirror's source or destination** — run `/lazy-wiki.configure mirror` again against the same scope; re-running install afterwards registers the schedule routine if it isn't already.

**Editing a terms dictionary's scope, or removing one** — run `/lazy-wiki.configure terms`; the remove path offers to keep or delete the dictionary file and cleans up the wiki-side `exclude_paths` entry it had added.

**Reshaping the structure map's classes or depths** — run `/lazy-wiki.configure structure`; existing classes are offered for keep/change/remove before you're asked about new ones.

**Checking one scope rather than all** — pass the scope id: `/lazy-wiki.doctor <scope-id>`. Omit it to audit every configured wiki scope, plus every terms scope and the structure map, in one pass.

**Updating the rules after a plugin upgrade** — re-run `/lazy-wiki.install`. The drift-detection step will detect the version difference and offer to overwrite the rule with the latest shipped version.

**Changing the agent-model tier for a curator or the domain writer** — run `/lazy-core.agent-models` to adjust the tier; `lazy-wiki.install` seeds the defaults but never overwrites a value you've already set.

## How the setup flow connects

<!-- /lazy-diagram.draw lands the fence here; do not author a code block manually. -->

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  wikiInstall["/lazy-wiki.install seeds wiki settings, composes wiki.curator, syncs the lazy-wiki.navigation rule, registers lazy-wiki.scan, lazy-wiki.scan-deletes, lazy-wiki.relink-weekly"]
  driftGuard{"Navigation rule already installed with drift?"}
  confirmOverwrite["Operator confirms rule overwrite"]
  wikiConfigureWizard["/lazy-wiki.configure wizard collects scope id, path globs, exclude_paths, tag_axes, topics_index, review-skip filter"]
  writeScope["Write scope into lazy.settings.json, new or edit mode"]
  coverageGuard{"Navigation rule installed?"}
  refreshCoverage["Refresh Coverage section from scope paths and exclude_paths, commit rule if tracked"]
  wikiDoctor["/lazy-wiki.doctor audits scope, reports FAIL, WARN, INFO findings"]
  repairGuard{"Operator confirms repairs?"}
  applyRepairs["Apply fixable repairs"]
  wikiHelp["/lazy-wiki.help optional orientation"]

  wikiInstall -->|check rule| driftGuard
  driftGuard -->|drift found| confirmOverwrite
  driftGuard -->|no drift| wikiConfigureWizard
  confirmOverwrite -->|approved| wikiConfigureWizard
  wikiConfigureWizard -->|submit scope| writeScope
  writeScope -->|refresh coverage| coverageGuard
  coverageGuard -->|absent| wikiInstall
  coverageGuard -->|present| refreshCoverage
  refreshCoverage -->|scope ready| wikiDoctor
  wikiDoctor -->|findings reported| repairGuard
  repairGuard -->|confirmed| applyRepairs
  repairGuard -->|declined| wikiDoctor
  wikiInstall -->|optional| wikiHelp
  wikiConfigureWizard -->|optional| wikiHelp
  wikiDoctor -->|optional| wikiHelp

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px

  class wikiInstall entry
  class driftGuard,coverageGuard,repairGuard guard
  class confirmOverwrite,wikiConfigureWizard,writeScope,refreshCoverage,wikiDoctor,wikiHelp action
  class applyRepairs success
```

## See also

- **audit** block — once scopes are running, the `wiki.doctor` skill also appears in the `audit` block alongside the broader integrity tooling.
- **curation** block — after setup, the `wiki.relink-doc` and `wiki.relink-all` skills drive the actual per-node curation; the `wiki.curator` expert registered here is what they dispatch.
- **domains** block — once `/lazy-wiki.configure domains` is set up, this is where you query the generated domain-spec tree it produces.
- **terms** block — once `/lazy-wiki.configure terms` is set up, this is where writers consult the dictionary this block builds.
- **structure** block — once `/lazy-wiki.configure structure` is set up, this is where you query the project-structure map the registered routines keep current.
