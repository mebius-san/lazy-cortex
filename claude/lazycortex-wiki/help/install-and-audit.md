---
chapter_type: block
summary: Bootstrap lazycortex-wiki in a project — install, configure scopes, run integrity audits, and orient yourself with the built-in help command.
last_regen: 2026-07-16
diagram_spec:
  anchor: "How the setup flow connects"
  request: "Flow diagram showing the install-and-audit lifecycle: wiki.install seeds settings and registers the expert plus the three daemon-gated routines (wiki.scan for changed files, wiki.scan-deletes for deleted files/link pruning, wiki.relink-weekly for the full rescan) → wiki.configure wizard collects scope id/paths/exclude_paths/tag_axes/topics_index/filter (review-skip) and writes to lazy.settings.json → wiki.doctor audits the scope and optionally applies fixable repairs. wiki.help is shown as an optional orientation step available at any point."
source_skills:
  - lazy-wiki.install
  - lazy-wiki.configure
  - lazy-wiki.doctor
  - lazy-wiki.help
---
# Bootstrap and maintain lazycortex-wiki

Getting `lazycortex-wiki` running in a project takes three ordered moves: install the plugin infrastructure, configure at least one scope, then audit that scope to confirm everything is coherent. After setup these same skills remain your go-to tools whenever you add a scope, onboard a new contributor, or want a health check after a large restructure. The `lazy-wiki.help` command rounds out the block as an always-available orientation reference.

## When you'd use this

- Starting fresh: you've enabled the plugin and want to get the git-watch and weekly-scan routines running, the `wiki-curator` expert registered, and the navigation rule synced.
- Adding a new scope to an existing install: run `/wiki.configure` to define the path globs, tag axes, topics-index path, and review-skip filter for the new area without touching the existing scopes.
- Verifying integrity after a large refactor or import: run `/wiki.doctor` to surface orphan topics, broken See-also links, stale glosses, and index desync before they accumulate.
- Quick orientation mid-session: invoke `/lazy-wiki.help` to get a compact listing of every skill, agent, and command in the plugin.

## How it fits together

`/wiki.install` is the foundation. It detects whether the plugin is enabled at project or user scope, resolves the path for `lazy.settings.json`, creates the `~/.claude/templates/wiki/` (or `.claude/templates/wiki/`) directory, syncs the `lazy-wiki.navigation` rule into the consumer's rules directory, seeds the `wiki` settings section, seeds agent-model tier entries for the curator from `lazycortex-core`'s defaults, and registers the three routines — a git-watch routine (`wiki.scan`) that processes changed files on every commit, a companion git-watch routine (`wiki.scan-deletes`) that reacts to deleted files by pruning See-also links pointing at the deleted node and rebuilding the topic index, and a weekly full-scan routine (`wiki.relink-weekly`). It also composes the `wiki-curator` expert entry. As part of the install, it adds `Bash(lazycortex-wiki *)` to the project's `settings.local.json` allow-list so that curator subprocesses invoked by the daemon's `dontAsk` permission mode can reach the plugin CLI without being silently denied. The skill is idempotent: re-running it never overwrites values you've already customised; it asks about drift before overwriting any rule that has diverged from the shipped version. After install, if no scopes exist yet it offers to launch `/wiki.configure` immediately.

`/wiki.configure` is the scope wizard. You run it once per logical area of the repository. It walks you through one question at a time — scope id, path globs (markdown documents, code files, or both), optional exclude paths, tag axes that define the closed coordinate dimensions for topic classification, the path to the scope's `topics.md` index, and a review-skip filter. The filter step asks whether documents currently under review (`review_active: true`, set by `lazycortex-review`) should be excluded from wiki curation while review is open; they re-enter the wiki automatically once review closes. The default is yes. The resulting filter is mirrored into the `wiki.scan` routine's own `filter` block, so changed files are dropped at the daemon level — before `process-file` runs — while review is active. The resulting scope entry lands in `lazy.settings.json[wiki.scopes]` under the id you chose. Re-running with the same id enters edit mode: existing values are shown and you can keep or change each one.

`/wiki.doctor` audits a single scope or every configured scope. In its default read-only pass it surfaces findings at three severities — `FAIL`, `WARN`, `INFO` — and labels which ones are fixable. Fixable findings are: orphan topics and index desync (repaired by rebuilding the topic index), broken See-also lines (dropped), and stale glosses (refreshed). Report-only findings cover broken repo keys, missing node summaries, unknown tag axes, near-duplicate axis values, broken `<wiki>` blocks in code files, and overlapping scope globs. After showing findings, the skill asks whether to apply the fixable repairs; it writes tracked files only after you confirm. `wiki.scan-deletes` already handles the everyday case of a single deleted node between doctor runs, so a clean scope should rarely surface stale See-also links from deletions — `/wiki.doctor` remains the backstop for anything the daemon missed (daemon disabled, deletion outside the watched branch, and so on).

`/lazy-wiki.help` is a zero-tool command that prints a compact reference of every skill, agent, and command the plugin ships. No state is read or written; invoke it any time you want a quick reminder of what's available.

## Common adjustments

**Changing the scope's path globs, tag axes, or review-skip filter** — run `/wiki.configure` again with the same scope id. Edit mode shows the current values so you can update only what you need.

**Checking one scope rather than all** — pass the scope id: `/wiki.doctor <scope-id>`. Omit it to audit every configured scope in sequence.

**Updating the navigation rule after a plugin upgrade** — re-run `/wiki.install`. The drift-detection step in Step 4 will detect the version difference and offer to overwrite the rule with the latest shipped version.

**Changing the agent-model tier for the curator** — run `/lazy-core.agent-models` to adjust the tier; `lazy-wiki.install` seeds the defaults but never overwrites a value you've already set.

## How the setup flow connects

<!-- /lazy-diagram.draw lands the fence here; do not author a code block manually. -->

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  wikiInstall[wiki.install]
  seedSettings[Seed settings]
  registerExpert[Register expert + routines]
  wikiScanChanged[wiki.scan - changed files]
  wikiScanDeletes[wiki.scan-deletes - deleted files, link pruning]
  wikiRelinkWeekly[wiki.relink-weekly - full rescan]
  wikiConfigure[wiki.configure wizard]
  writeSettings[Write lazy.settings.json]
  wikiDoctor{wiki.doctor audits scope}
  applyFixes[Apply fixable repairs]
  doneReady[Scope ready]
  wikiHelp[wiki.help orientation]

  wikiInstall -->|seeds| seedSettings
  seedSettings -->|registers| registerExpert
  registerExpert -->|gates| wikiScanChanged
  registerExpert -->|gates| wikiScanDeletes
  registerExpert -->|gates| wikiRelinkWeekly
  registerExpert -->|next| wikiConfigure
  wikiConfigure -->|collects scope id, paths, exclude_paths, tag_axes, topics_index, filter| writeSettings
  writeSettings -->|audits| wikiDoctor
  wikiDoctor -->|fixable| applyFixes
  wikiDoctor -->|healthy| doneReady
  applyFixes -->|repaired| doneReady
  wikiInstall -.->|orientation optional| wikiHelp
  wikiHelp -.->|resume| wikiConfigure

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px

  class wikiInstall entry
  class wikiDoctor guard
  class seedSettings action
  class registerExpert action
  class wikiScanChanged action
  class wikiScanDeletes action
  class wikiRelinkWeekly action
  class wikiConfigure action
  class writeSettings action
  class applyFixes action
  class wikiHelp action
  class doneReady success
```

## See also

- **audit** block — once scopes are running, the `wiki.doctor` skill also appears in the `audit` block alongside the broader integrity tooling.
- **curation** block — after setup, the `wiki.relink-doc` and `wiki.relink-all` skills drive the actual per-node curation; the `wiki-curator` expert registered here is what they dispatch.
</content>
