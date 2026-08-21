---
name: lazy-obsidian.install
description: "Run when the operator asks to set up Obsidian for this repo or to wire up a fresh vault, and again after a plugin update so new artifacts land. Also the answer when tag pages render empty (Dataview missing), the tag-page template isn't in `.claude/templates/`, icons are unpainted, or diagrams render unstyled — at project scope this is the plugin family's root entry point and chains `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install`. Idempotent; install scope is detected, not asked."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(lazycortex-core *), AskUserQuestion, Skill, Agent
---
# Install lazycortex-obsidian

Bootstrap the plugin in the right scope. What this skill does, in one pass:

- Syncs rule templates shipped by the plugin into the matching rules directory — install-managed mirrors: stale copies are overwritten from the shipped source, orphans left in place.
- Scaffolds the tag-page template consumed by the `lazy-obsidian.gen-tag-pages` agent — project scope only, seeded once and never touched again.
- Neither path ever prompts.
- At project scope this skill is the root entry point for the plugin family: after the rule/template work it installs Dataview (needed by tag pages), syncs and enables every CSS snippet the plugin ships (the one writer of `appearance.json`'s `enabledCssSnippets` array), and runs `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install` so a fresh vault reaches a usable state.

The plugin currently ships **zero rules**. If you installed an earlier version of the plugin that shipped `lazy-obsidian.vault-hygiene.md`, this skill leaves it in place as a kept-orphan (it is never auto-deleted).

## Execution discipline (MANDATORY — read before any action)

This skill has 11 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Sync the tag-page template`
   - `Step 5 — Install Dataview`
   - `Step 6 — Run /lazy-obsidian.iconize-install`
   - `Step 6.5 — Sync + enable plugin snippets`
   - `Step 6.6 — Run /lazy-obsidian.diagram-install`
   - `Step 7 — Verify / Report`
   - `Step 8 — Seed lazy.settings.json`
   - `Step 9 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `installed`, `unchanged`, `merged`, `kept-orphan`, `chained`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

- Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran.
- The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`.
- Enablement is the source of truth for where config belongs.

Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

```
Bash(lazycortex-core detect-scope lazycortex-obsidian@lazycortex)
```

The command prints exactly one word:
- `project` — enabled in `<repo-root>/.claude/settings.json` (project wins even when the install record's scope is `user`, and when both scopes enable it); Steps 3–4 target `<repo-root>/.claude/`, and the project-scope-only Steps 5–6.5 run.
- `user` — enabled only in `~/.claude/settings.json` (or the fallback resolved there); Steps 3–4 target `~/.claude/`, and the project-scope-only steps skip.
- `not-installed` — `lazycortex-obsidian@lazycortex` is absent / has an empty array in `~/.claude/plugins/installed_plugins.json`; the plugin has never been installed on this machine.

The scope is derived — do NOT ask.

**Do NOT compare an entry's `projectPath` against the current working directory.** Step 2 targets `<repo-root>` (resolved in Step 2 — the `repo=` dispatch arg when headless, else `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Abort **only** on `not-installed` — the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-obsidian@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-obsidian`.

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-obsidian@lazycortex`.

For each source file `<installPath>/rules/<name>.md`, the rule destination by scope is:

| Scope | Rule destination |
|---|---|
| `user` | `~/.claude/rules/<name>.md` |
| `project` | `<repo-root>/.claude/rules/<name>.md` |

Project root (`<repo-root>`), by run kind:

1. Headless run — the invoking prompt carries `repo=<abs>` (e.g. from `lazy-core.autosetup`): `<repo-root>` **is** that path. Do **not** run `git rev-parse` — a dispatched agent's Bash cwd is the coordinator's repo, not the target.
2. Interactive run with no `repo=`: `<repo-root>` = `git rev-parse --show-toplevel`.
3. Not in a git repo: fall back to the current working directory — but warn the user.

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-obsidian@lazycortex` first.

## Step 3: Sync rule templates (file-sync policy)

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md`.
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-obsidian` → `lazy-obsidian`), plus every unique `<ns>.` prefix appearing in source rule filenames. When no rules ship, the owned namespace is just `lazy-obsidian`.
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace.
- Ensure the destination directory exists with `mkdir -p`.

### Per-rule decision (quiet file-sync)

Rules are install-managed mirrors: the plugin owns every byte, and a consumer who wants different content authors their own rule file rather than editing the mirror. So a target that differs from the shipped source is a stale copy, and the sync never prompts:

1. **Absent** — target missing, source present → `cp <source> <target>`. State **installed**.
2. **Byte-identical** — both present and equal → no action. State **unchanged**.
3. **Different** — both present and the bytes differ → overwrite from the shipped source, then re-compare to confirm the write landed. State **refreshed**, or **failed** when the target still differs afterwards.
4. **Orphan** — target present, source missing → leave it in place silently. State **kept-orphan**. Orphans are never deleted: the rule may still be relied on, and we can't prove removal is safe.

The verdict is a byte comparison, never an impression from reading the two files.

With zero source rules, nothing is written and orphans are silently kept. Users upgrading from an earlier version see `lazy-obsidian.vault-hygiene.md` reported as **kept-orphan** (the rule was retired when `lazy-obsidian.config` was removed; vault-plugin setup now lives in `/lazy-obsidian.update-plugin` + `/lazy-obsidian.iconize-install`) — the report notes it is retired so the user can delete it by hand.

### Namespace-scoped orphan handling

Orphan detection only considers target files whose filename starts with one of this plugin's owned namespaces (just `lazy-obsidian.*` today). Rules from other plugins and user-authored rules in unrelated namespaces are never reported as orphans.

## Step 4: Sync the tag-page template (project scope only)

The `lazy-obsidian.gen-tag-pages` agent reads its template from the consumer repo at a fixed path. This step scaffolds (and quietly re-syncs) that file. **Skip this step entirely when scope is `user`** — tag pages only make sense per-vault, so there is no global install mode.

### Paths

- Source: `<installPath>/templates/obsidian/tag-page-template.md`
- Target: `<repo-root>/.claude/templates/lazy-obsidian.tag-page-template.md`

Ensure `<repo-root>/.claude/templates/` exists with `mkdir -p` before any write.

### Per-file decision (seed, not mirror)

This file is **not** an install-managed mirror, and Step 3's overwrite-on-drift policy does not apply to it. The vault is expected to tailor its tag pages, and there is no `_local` override path for this template — the file itself is the customisation surface. So the shipped copy is a seed:

1. **Absent** — target missing → `cp <source> <target>` silently. State **installed**.
2. **Present** — whatever it contains → leave it byte-for-byte. State **kept-local**.

No comparison, no merge, no prompt, ever. Once the file exists it belongs to the vault, and a plugin update that changes the shipped default does not reach it. No orphan detection is needed — the plugin owns exactly one template file under this name.

A vault still carrying the pre-namespace name (`obsidian.tag-page-template.md`) is not this step's business: renaming a consumer file that drifted from the naming canon belongs to `lazy-core.doctor` / `lazy-core.autosetup`, which own that canonicalisation for every plugin at once. This step only ever seeds the canonical name.

### Agent availability

The agent itself (`lazy-obsidian.gen-tag-pages`) is shipped by the plugin at `<installPath>/agents/lazy-obsidian.gen-tag-pages.md` and becomes available automatically when the plugin is enabled — nothing to copy into the consumer repo. Only the template is project-local.

## Step 5: Install Dataview (project scope only)

Tag pages rely on the Dataview Obsidian plugin to render the `Index` section — it is a hard dependency for the vault setup, not an optional add-on. Skip this step entirely when scope is `user` — tag pages are a vault concern. No opt-in prompt: plugin enabled means full functionality, so the full vault setup installs Dataview unconditionally.

Invoke `/lazy-obsidian.update-plugin dataview` unconditionally — it is version-aware and idempotent (installs if missing, updates if the remote is newer, no-ops when current) and re-enforces the opinionated override block from `plugin-settings.json` on every run. Record its state tuple (`binary=... overrides=... community=...`) for the final report. Outcome: state tuple.

If `update-plugin` returns FAIL (registry unreachable, id missing), surface the failure and record `failed:<reason>` — without Dataview the `Summary` section still renders but the `Index` DataviewJS block stays blank. Re-running this skill later picks Dataview up once the network is available.

## Step 6: Run `/lazy-obsidian.iconize-install` (project scope only)

Skip this step ONLY when scope is `user` — iconize-sync is a vault concern.

No opt-in prompt: the full vault setup installs iconize-sync unconditionally (plugin enabled means full functionality). The child skill is itself quiet and idempotent — it installs Iconize + Folder Notes + iconize-reloader via `/lazy-obsidian.update-plugin`, scaffolds the icon-map + repaint routine, asserts Iconize frontmatter settings, manages its one `.gitignore` line, and version-checks its hard deps — silently re-running every state and prompting only on a genuine conflict. None of those states are observable from the icon-map file alone, so always run it; never short-circuit on a probe.

Invoke `/lazy-obsidian.iconize-install` as the next skill call, forwarding the target explicitly as `repo=<repo-root>` so the child mutates the target repo and not the coordinator's cwd. Record **chained** for the report.

## Step 6.5: Sync + enable plugin snippets (project scope only)

Skip this step ONLY when scope is `user` — CSS snippets are a vault concern.

Installs every CSS snippet the plugin ships and enables all of them with one `appearance.json` edit. This step used to live inside `/lazy-obsidian.diagram-install` (which owned only two of the snippets); now that `callouts.css` exists too, `install` owns the array so there's a single writer of `enabledCssSnippets` — `diagram-install` only declares its files, it no longer writes them.

### Sync (file-sync policy)

Enumerate `Glob ${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/*.css` — never hardcode the snippet list, so a plugin update that adds a new snippet lands here without an install-skill edit. `mkdir -p <vault>/snippets` first. For each `<name>.css`:

- Source: `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/<name>.css`.
- Target: `<vault>/snippets/<name>.css`.

These are quiet-sync artifacts — no per-file install prompt, no drift overwrite/keep prompt. The three cases:

- **Absent or byte-identical** (target missing, or present and equal to source) → `cp <source> <target>` silently (`mkdir -p` parents first). State **installed** (missing) or **unchanged** (identical). No prompt.
- **Locally changed, shipped delta applies cleanly** — the local file differs from source but the difference is confined to regions the shipped version did not change (the local edits and the shipped edits touch disjoint regions). Apply the shipped delta on top of the local edits silently. State **merged**.
- **Genuine conflict** — the local file and the shipped version changed the *same* region incompatibly, and there is no way to tell which should survive. This is the ONLY case that prompts. `AskUserQuestion`:
  - question: `<name>.css — conflicting edits in the same region. Which version wins for that region?`
  - description: ``**Conflicting region:**\n```diff\n<the conflicting hunk(s), both sides>\n```\n\nYou customized this snippet (e.g. tightened the selector, added per-theme tweaks) in the same place the shipped version changed. Merge-shipped takes the shipped version for that region; keep-local preserves yours and skips that part of the upstream change.``
  - options: **merge-shipped** / **keep-local**.
  - **merge-shipped** → write the shipped version for the conflicting region, keep non-conflicting local edits. State **merged**.
  - **keep-local** → leave the conflicting region as the user has it; still apply any non-conflicting shipped delta. State **kept-local**.

Use `Read` + `Write` so the merge stays visible. "Conflict" means same region changed incompatibly on both sides — not merely "bytes differ".

Outcome: per-snippet status word from `installed` / `unchanged` / `merged` / `kept-local`. Record for Step 7.

### Enable in appearance.json

Read `<vault>/appearance.json`. If missing or unparseable, treat its contents as `{}`.

- Ensure `enabledCssSnippets` exists as an array (create empty `[]` if absent).
- For each snippet `<name>` synced above:
  - If `<vault>/snippets/<name>.css` does not exist on disk, do NOT add the entry — pointing `enabledCssSnippets` at a missing file is dead config. Record per-snippet outcome **deferred** in this case. (The sync above always writes the file unless a conflict was kept-local in a way that removed it — normally the file is present.)
  - Otherwise, if the array does NOT contain `"<name>"`, append it.
- Atomic write (`appearance.json.tmp` → `mv`) only when the array changed.

Per-snippet outcome:
- `enabled` — added to the array this run.
- `already-enabled` — entry was already present.
- `deferred` — snippet file absent on disk; refused to register a stale entry.

Reload note: Obsidian does not watch `appearance.json` for changes mid-session. Step 7 tells the user to reload Obsidian (or click ↻ next to each snippet in Settings → Appearance → CSS snippets) when any snippet's outcome this step was **enabled**.

Outcome: per-snippet sync status + per-snippet enable status. Record for Step 7.

## Step 6.6: Run `/lazy-obsidian.diagram-install` (project scope only)

Skip this step ONLY when scope is `user` — diagram render glue is a vault concern.

No opt-in prompt: the full vault setup installs the diagram render glue unconditionally (plugin enabled means full functionality). The child skill is quiet and idempotent — it installs `mermaid-popup` via `/lazy-obsidian.update-plugin` with the calibrated zoom-ratio override, and leaves the legacy `mermaid-no-bg.css` snippet in place as a kept-orphan — silently re-running every state and prompting only on a genuine conflict. None of those states are observable from a probe alone, so always run it; never short-circuit.

Invoke `/lazy-obsidian.diagram-install` as the next skill call. Record **chained** for the report.

## Step 7: Verify

- Read back each installed rule file and confirm its `---` frontmatter parses.
- If the tag-page template was installed or updated this run, read back the target and confirm it still contains both `{{TAG_PATH}}` and `{{SUMMARY}}` substitution tokens. Warn (do not fail) if either is missing — the consumer may have customized them away intentionally.
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**installed**, **unchanged**, **refreshed**, **kept-orphan**, or **failed**) and target `<path>`
  - Tag-page template: state (**installed** or **kept-local**) and target `<path>` — omit when scope is `user`
  - Dataview install: `update-plugin` state tuple (`binary=... overrides=... community=...`) or **failed:`<reason>`** — omit when scope is `user`
  - iconize-install chain: **chained** — omit when scope is `user`. This line is mandatory in project scope; emit it unconditionally so a missing line is a visible gap in the report.
  - Snippets (Step 6.5) — one bullet per snippet: sync state (**installed** / **unchanged** / **merged** / **kept-local**) and appearance.json state (**enabled** / **already-enabled** / **deferred**), with target `<path>` — omit when scope is `user`.
  - diagram-install chain: **chained** — omit when scope is `user`. This line is mandatory in project scope; emit it unconditionally so a missing line is a visible gap in the report.

## Step 8: Seed lazy.settings.json

Seed the `agent_models.lazycortex` group with this plugin's shipped subagent (`lazy-obsidian.gen-tag-pages`) by dispatching the shared primitive — it owns the `default-tiers.json` locate, the `lazycortex-obsidian:`-prefix filter, and the non-destructive per-key semantics (absent→add, equal→unchanged, different→kept-local). There is no inline tier logic here.

Dispatch, passing the scope resolved in Step 1 (`project` | `user`):

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-obsidian scope=<scope>")
```

Fold the primitive's returned report block verbatim into this skill's Step 7 report. Surface its terminal outcomes:

- **`sot-missing`** — `lazycortex-core`'s `default-tiers.json` was not found → the primitive aborts; relay its message (`lazycortex-core not installed; install it before seeding lazycortex-obsidian tiers`) and do not fabricate seed lines.
- **`no-entries`** — the SOT lists no `lazycortex-obsidian:` agents → report it plainly (a maintainer must extend `default-tiers.json`); not an abort.

Step outcome: `seeded` (any entry added) or `unchanged`.

## Step 9: Log the run

Log to `./.logs/claude/lazy-obsidian.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Failure modes

- **`/lazy-obsidian.install` aborts: "plugin not installed"** — `lazycortex-obsidian@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-obsidian@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/lazy-obsidian.install` aborts: "plugin cache is empty"** — the plugin glob returned zero rule files → run `/plugin update lazycortex-obsidian@lazycortex` to refresh the cache, then re-run.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule or template files into the consumer repo. Re-run this skill after every plugin update to pick up changes.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **User scope is rule-only**: the tag-page template and Dataview check are project-only concerns (they require a vault).
- **Next steps shown to user**: if any rule was **installed** or **refreshed**, remind the user to restart Claude Code (rules are loaded on session start). If the tag-page template was **installed**, mention that it is now the vault's to customize and that future installs leave it alone. If any artifact was **kept-orphan**, note it is retired and can be deleted by hand. If Dataview reported **failed:**, remind them they can re-run `/lazy-obsidian.update-plugin dataview` later. If any Step 6.5 snippet outcome was **enabled**, remind: "Reload Obsidian (or click ↻ next to the snippet in Settings → Appearance → CSS snippets) — snippets won't apply mid-session." If any Step 6.5 snippet outcome was **kept-local**, remind: "you kept a conflicting region in one of the plugin's snippets — re-run later to pick up the upstream change once you've reconciled it." The iconize-install and diagram-install chains run automatically as part of the full vault setup — their own reports surface inline.
