---
name: lazy-wiki.configure
description: "Use when the user wants to add a wiki scope, change which paths the wiki covers, edit an existing scope's globs, axes, exclusions, or topics-index path — or set up domain-spec generation (`/lazy-wiki.configure domains`: code globs, dictionary, output tree, language) — or mirror a foreign repo's markdown into a scope (`/lazy-wiki.configure mirror`: source url/branch, source globs, excludes, mirror directory) — or set up a terms dictionary (`/lazy-wiki.configure terms`: which documents it serves, where the dictionary file lives, which documents are term sources) — or configure the project-structure map (`/lazy-wiki.configure structure`: depth profiles, exclusions, the three scan routines) — or edit the vault-wide wiki keys themselves (`/lazy-wiki.configure vault`: the `tag_axes` vocabulary every scope narrows from, the `exclude` globs every scope inherits). Wizard over .claude/lazy.settings.json[wiki.scopes] / [wiki.tag_axes] / [wiki.exclude] / [wiki.domains] / [terms.scopes] / [structure], one question per turn via AskUserQuestion; also refreshes the Coverage section of the installed navigation rule."
allowed-tools: Read, Edit, Write, AskUserQuestion, Skill, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(git ls-files *), Bash(git commit *), Bash(cp *), Bash(test *), Bash(rm *), Agent
---
# lazy-wiki.configure

Interactive wizard. Creates or edits a scope entry in `lazy.settings.json[wiki.scopes]` for the current repo — or, invoked as `/lazy-wiki.configure domains`, the `wiki.domains` section that drives domain-spec generation (see **Domains branch** below) — or, invoked as `/lazy-wiki.configure mirror`, an existing scope's nested `mirror` block that mirrors a foreign repo's markdown into the vault (see **Mirror branch** below) — or, invoked as `/lazy-wiki.configure terms`, a scope of the `terms` section that drives the terms dictionary (see **Terms branch** below) — or, invoked as `/lazy-wiki.configure structure`, the `structure` section that drives the project-structure map (see **Structure branch** below) — or, invoked as `/lazy-wiki.configure vault`, the repository-wide keys of the `wiki` section itself: the axis vocabulary `wiki.tag_axes` every scope narrows from, and the exclusion list `wiki.exclude` every scope inherits (see **Vault branch** below). Each field is collected one question at a time via `AskUserQuestion`. This wizard only collects **genuine project config that cannot be derived** — the topics-index path, scope globs, exclude globs, classification axes, and review-skip filter. There is no install-scope question (the wizard always edits the current repo's `lazy.settings.json`) and no environment probe.

**Read-first.** Re-running for an existing scope `id` (or for an existing `wiki.domains` section) enters edit mode: each persisted value is read from `lazy.settings.json` first and shown as the current value; pressing Enter keeps it untouched. A field is re-asked only to let the operator change it — never to re-collect a value already on record.

Prerequisite: `/lazy-wiki.install` has run (the `wiki` settings section exists).

## Execution discipline (MANDATORY — read before any action)

This skill has six mutually exclusive branches; exactly one runs per invocation. The **scope branch** (default) has 9 ordered steps plus Report; the **domains branch** (argument `domains`, or the operator asks to configure domain specs) has 5 ordered steps plus Report; the **mirror branch** (argument `mirror`, or the operator asks to mirror a foreign repo into the wiki) has 5 ordered steps plus Report; the **terms branch** (argument `terms`, or the operator asks to set up a terms dictionary) has 7 ordered steps plus Report; the **structure branch** (argument `structure`, or the operator asks to configure the structure map) has 5 ordered steps plus Report; the **vault branch** (argument `vault`, or the operator asks to edit the axis vocabulary or the repository-wide exclusions) has 4 ordered steps plus Report. The executing agent MUST NOT skip, merge, reorder, or silently omit any step of the chosen branch. To make dropped steps structurally impossible:

1. **Before calling any other tool**, decide the branch from the invocation, then call `TaskCreate` with exactly one task per step of that branch — no merging, no abbreviation, no renaming, and no tasks from another branch. The scope branch's canonical list (use these titles verbatim; each other branch's list is in its own section below):
   - `Phase 1 — Verify install + load settings`
   - `Phase 2 — Collect scope id`
   - `Phase 3 — Collect paths globs`
   - `Phase 4 — Collect exclude_paths`
   - `Phase 5 — Collect tag_axes`
   - `Phase 6 — Collect topics_index`
   - `Phase 7 — Collect filter`
   - `Phase 8 — Write back + log`
   - `Phase 9 — Refresh navigation-rule Coverage`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `verified` / `collected` / `skipped-per-user-choice` / `written` / `logged` / `refreshed` / `unchanged` / `absent` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.
5. **Orient before the branch's first `AskUserQuestion`.** Print two to four lines naming what the section governs, which artifact it produces and where that artifact lives, and what the values being collected mean — the vocabulary of the questions ahead (`depth_profiles` classes and their three depths, `source_exclude` versus `exclude_paths`, `tag_axes`, a `mirror` block). An operator who has not read this SKILL.md cannot answer a question phrased in its internal vocabulary, and a guessed answer is written to settings as a decision. Say it once per invocation, before the first question; do not repeat it per question.

## Phase 1 — Verify install + load settings

Run `Bash(git rev-parse --show-toplevel)` to get `<repo-root>`. `Read` `<repo-root>/.claude/lazy.settings.json`. If the file is absent, abort: *"Run `/lazy-wiki.install` first."* If the file exists but has no `wiki` key, abort: *"Run `/lazy-wiki.install` first — the `wiki` section is missing."* Hold the parsed object in memory.

Outcome: `verified`.

## Phase 2 — Collect scope id

`AskUserQuestion`: *"Scope id (alphanumeric + hyphens/underscores, e.g. `docs` or `codebase`)?"*

Validate: must match `^[a-z][a-z0-9_-]*$`. Re-ask until valid.

If an entry already exists at `wiki.scopes[<id>]`, inform the user: *"Scope `<id>` already exists — entering edit mode. Existing values will be shown; press Enter to keep them."* Hold edit-mode flag.

Outcome: `collected`.

## Phase 3 — Collect paths globs

`AskUserQuestion`:
- New mode: *"Path glob(s) that define this scope — comma-separated (e.g. `docs/**/*.md, src/**/*.py`):"*
- Edit mode: *"Path glob(s) for scope `<id>` (current: `<current paths joined>`; comma-separated, Enter to keep):"*

Split on commas, trim whitespace, discard empty entries. Must have at least one entry; re-ask if empty. Hold as an array.

Outcome: `collected`.

## Phase 4 — Collect exclude_paths

`AskUserQuestion`:
- New mode: *"Exclude glob(s) to omit from the scope — comma-separated, or leave blank for none (e.g. `**/.obsidian/**, **/node_modules/**`):"*
- Edit mode: *"Exclude glob(s) for scope `<id>` (current: `<current exclude_paths joined or "none">`; comma-separated, blank to clear, Enter to keep):"*

Split on commas, trim, discard empty entries. Empty input means no `exclude_paths` key (or clear existing). Hold as an array (may be empty).

**The scope list is additive on top of `wiki.exclude`.** The section-level `wiki.exclude` list is unioned into every scope's exclusions, so what is collected here is only what this scope excludes *beyond* the repository-wide set — never a repetition of it. Two entries in particular are already covered and must not be re-collected here: `docs/structure.md` (the fixed-path project-structure map, seeded into `wiki.exclude` by `/lazy-wiki.install`), and the generated domain-spec tree, which is derived from `wiki.domains.output` and excluded structurally without being declared anywhere. Edit the repository-wide list itself with `/lazy-wiki.configure vault`.

Outcome: `collected`.

## Phase 5 — Collect tag_axes

The axis vocabulary belongs to the repository, not to the scope: `wiki.tag_axes` declares the closed set for the whole vault, and a scope's own `tag_axes` list only **narrows** it to the axes this scope actually uses. A scope can never widen the vocabulary — an axis the repository does not declare is not offered here and cannot be added here.

Read `wiki.tag_axes` from the settings loaded in Phase 1 and offer exactly those axes. An empty vocabulary means there is nothing to narrow — say so, skip the question, hold an empty array, and point at `/lazy-wiki.configure vault`, which is where the vocabulary is authored.

`AskUserQuestion`:
- New mode: *"Which of the vault's tag axes does this scope use — `<repository tag_axes joined>` — comma-separated, or blank for all of them:"*
- Edit mode: *"Tag axes for scope `<id>` (vault vocabulary: `<repository tag_axes joined>`; current narrowing: `<current tag_axes joined or "all">`; comma-separated, blank for all, Enter to keep):"*

Split on commas, trim, discard empty entries. Lowercase-normalise each axis slug. Drop — and name — any entry outside the vault vocabulary rather than writing it: it would be silently ignored on every dispatch. Blank input means the scope uses the full vocabulary; hold it as an empty array.

Outcome: `collected`.

## Phase 6 — Collect topics_index

`AskUserQuestion`:
- New mode: *"Path to the scope's `topics.md` index file, relative to the repo root (e.g. `wiki/docs-topics.md`):"*
- Edit mode: *"Topics index path for scope `<id>` (current: `<current topics_index>`; Enter to keep):"*

Trim whitespace. Must be non-empty; re-ask if blank. The file need not exist yet — it is created on first full scan.

Outcome: `collected`.

## Phase 7 — Collect filter

The per-scope `filter` excludes a node from the wiki on the fly (the node is not curated, not indexed, not linked while it matches). Two sub-filters: `frontmatter` — the common case is standing down on documents currently under review; `folder_note` — a note named after its own folder (`sync/sync.md`) renders as the folder itself under the folder-notes convention, so it is a structural navigation node, not a document to curate.

`folder_note: false` is not asked — it is the structural default for every scope. Seed it whenever the key is absent (new scope, or an edit-mode scope whose filter predates it); never overwrite an operator's explicit `true`, which selects folder notes exclusively.

`AskUserQuestion` collects the review-skip half only:
- New mode: *"Skip documents that are currently in review? While `review_active: true` (set by lazycortex-review) is present, the document is left out of the wiki and re-enters when review closes. (yes / no)"*
- Edit mode: *"Review-skip filter for scope `<id>` (current: `<"on" when filter.frontmatter.review_active present, else "off">`; yes keeps it on, no clears it):"*

- **yes** → hold `{ "frontmatter": { "review_active": { "not_in": [true] } }, "folder_note": false }`.
- **no** → hold `{ "folder_note": false }` (clears any existing frontmatter sub-filter in edit mode).

Default: **yes**. Richer predicates (other frontmatter keys, `in` allow-lists) follow the same schema as a routine's `filter` block and are hand-editable in `lazy.settings.json` — this wizard only collects the review-skip default.

Outcome: `collected`.

## Phase 8 — Write back + log

Build the scope object:

```json
{
  "paths": ["<...>"],
  "tag_axes": ["<...>"],
  "topics_index": "<path>"
}
```

`tag_axes` is the narrowing held by Phase 5, not a vocabulary of its own — an empty array means the scope uses every axis `wiki.tag_axes` declares. Add `"exclude_paths"` only if the collected array is non-empty. Add `"filter"` as held by Phase 7 — always present, since `folder_note` is seeded there; in edit mode carry over any operator-authored sub-filter the wizard does not collect.

Write the updated settings back: set `lazy.settings.json[wiki.scopes][<id>]` to the constructed object. Preserve all other keys. Use `Write` to the target file.

Then log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` — two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-wiki.configure)` then `Write` tool. Log frontmatter: `git_sha` (`Bash(git rev-parse HEAD)`), `git_branch` (`Bash(git rev-parse --abbrev-ref HEAD)`), `date` (UTC), `input: "scope_id=<id>"`.

Outcome: `written` and `logged`.

## Phase 9 — Refresh navigation-rule Coverage

The `## Coverage` section of the installed `lazy-wiki.navigation` rule is what every session reads to decide whether a question must route through `/lazy-wiki.query`. It is derived from the scope globs collected above, so it goes stale the moment `paths` or `exclude_paths` change.

Locate the installed rule: `<repo-root>/.claude/rules/lazy-wiki.navigation.md`, falling back to `~/.claude/rules/lazy-wiki.navigation.md`. Neither present → outcome `absent` (the rule was never installed; `/lazy-wiki.install` owns that).

`Edit` the section body — everything between the `## Coverage` heading and the next `##` — replacing it wholesale with one bullet per scope in `lazy.settings.json[wiki.scopes]`, in id order:

`- **<id>** — <glob>, <glob> (excluding <glob>, <glob>)`

Drop the parenthetical when the scope declares no `exclude_paths`. Replace, never append — a second run must produce the same section, not a longer one. Touch nothing else in the rule. Body already identical → outcome `unchanged`.

The rule is a tracked file in most repos, so commit it in the same execution per `lazy-core.skill-writing § 6`. Check with `Bash(git ls-files --error-unmatch <path>)`; on success `Bash(git commit -m "chore(wiki): refresh navigation Coverage for scope <id>" -- <path>)`. Untracked (exit non-zero) → leave it in the worktree, no commit.

Outcome: `refreshed`, `unchanged`, or `absent`.

## Domains branch — `/lazy-wiki.configure domains`

Configures `lazy.settings.json[wiki.domains]` — the section that drives domain-spec generation (`Domain(…)` blocks in code → docs under the output tree). Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Domains 1 — Verify install + load settings`
- `Domains 2 — Collect code globs`
- `Domains 3 — Collect dictionary path + seed`
- `Domains 4 — Collect output + language`
- `Domains 5 — Write back + log + pointers`
- `Report`

### Domains 1 — Verify install + load settings

Same as Phase 1: resolve `<repo-root>`, read `lazy.settings.json`, abort with *"Run `/lazy-wiki.install` first."* when the file or its `wiki` key is missing. If `wiki.domains` already exists, announce edit mode (persisted values shown, Enter keeps them).

Outcome: `verified`.

### Domains 2 — Collect code globs

`AskUserQuestion`:
- New mode: *"Code glob(s) to scan for `Domain(…)` blocks — comma-separated (e.g. `src/**/*.py`):"*
- Edit mode: *"Code glob(s) (current: `<current code joined>`; comma-separated, Enter to keep):"*

Split on commas, trim, discard empty entries. Must have at least one entry; re-ask if empty. Hold as an array.

Outcome: `collected`.

### Domains 3 — Collect dictionary path + seed

`AskUserQuestion`:
- New mode: *"Path of the domain-groups dictionary (Enter for the default `docs/guidelines/domain-groups.md`):"*
- Edit mode: *"Dictionary path (current: `<current dictionary>`; Enter to keep):"*

Then **ensure the dictionary exists** — the configurator owns this guarantee: `Bash(test -f <repo-root>/<dictionary>)`; when absent, seed it from the skeleton template shipped by this plugin — `Bash(mkdir -p <dictionary-parent-dir>)` then `Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/domain-groups.md <repo-root>/<dictionary>)` — and tell the operator it holds a sample group to replace. An existing file is never touched (idempotent; `/lazy-python.knowledge-sweep` is the other creator and builds a populated one).

Outcome: `collected` + `dictionary-<seeded|already-present>`.

### Domains 4 — Collect output + language

`AskUserQuestion` (output):
- New mode: *"Output directory for the generated domain-spec tree (Enter for the default `docs/domains`):"*
- Edit mode: *"Output directory (current: `<current output>`; Enter to keep):"*

**Overlap warning:** check every `wiki.scopes` entry's `paths` globs against the chosen output directory; when a glob covers files under it, warn — *"Scope `<id>` glob `<glob>` reaches `<output>`, which is excluded from every scope regardless — the glob claims nothing there. Narrow it so the scope says what it actually covers."* Warn only. The generated tree is derived from this very setting and excluded structurally, so the warning is about a misleading glob, never about a contested file: handing the tree to the wiki is not something a scope can do.

`AskUserQuestion` (language): sample a few of the vault's authored spec/doc files to judge the language they are written in, and propose it as the default — *"Language for the generated domain docs (Enter for `<detected>`, the language this vault's specs are written in):"*. Edit mode shows the current value instead.

Outcome: `collected` (+ `overlap-warned` when the warning fired).

### Domains 5 — Write back + log + pointers

Build the section and set `lazy.settings.json[wiki.domains]`:

```json
{
  "code": ["<...>"],
  "dictionary": "<path>",
  "output": "<path>",
  "language": "<language>"
}
```

Preserve all other keys; write with `Write`. Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "domains"`).

Print two pointers (no questions):
- *"Run `/lazy-wiki.install` to register the `wiki.domain-writer` expert and the domain routines (daemon repos); `/lazy-wiki.domain-sync` is the manual run."*
- *"To backfill `Domain(…)` markers across existing code — or re-file them after a dictionary change — run `/lazy-python.knowledge-sweep`."*

Outcome: `written` and `logged`.

## Mirror branch — `/lazy-wiki.configure mirror`

Configures the nested `mirror` block of an **existing** scope in `lazy.settings.json[wiki.scopes][<id>]` — the block that drives `lazycortex-wiki mirror-sync <id>`: the source repo is cloned into the gitignored runtime dir and its markdown lands under `mirror_path` as ordinary wiki nodes. Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Mirror 1 — Verify install + pick scope`
- `Mirror 2 — Collect url + branch`
- `Mirror 3 — Collect source_paths + exclude`
- `Mirror 4 — Collect mirror_path`
- `Mirror 5 — Write back + log + pointers`
- `Report`

### Mirror 1 — Verify install + pick scope

Same as Phase 1: resolve `<repo-root>`, read `lazy.settings.json`, abort with *"Run `/lazy-wiki.install` first."* when the file or its `wiki` key is missing. Then `AskUserQuestion`: *"Which scope gets the mirror block?"* — offer the existing `wiki.scopes` ids. The scope MUST already exist; when `wiki.scopes` is empty, abort: *"No scopes configured — create one with `/lazy-wiki.configure` first."* If the chosen scope already carries a `mirror` block, announce edit mode (persisted values shown, Enter keeps them).

Outcome: `verified`.

### Mirror 2 — Collect url + branch

`AskUserQuestion` (url): *"Git URL of the source repository?"* — must be non-empty; re-ask if blank. Then (branch): *"Branch to mirror (Enter for the source's default branch)?"* — blank means no `branch` key (the clone follows the source's default).

Outcome: `collected`.

### Mirror 3 — Collect source_paths + exclude

`AskUserQuestion` (source_paths): *"Glob(s) of markdown to mirror, relative to the source repo root — comma-separated (e.g. `docs/domains/**`); only `.md` files under them are mirrored:"* — must have at least one entry; re-ask if empty.

Then (exclude): *"Exclude glob(s), comma-separated, or blank for none. Put the source's service files here — e.g. a generated index like `docs/domains/domains.md` that would otherwise become a node and go to pointless curation:"* — empty input means no `exclude` key.

Outcome: `collected`.

### Mirror 4 — Collect mirror_path

`AskUserQuestion`: *"Directory in this vault where the mirror lands (repo-relative)?"* — **required, no default**; re-ask until non-empty. Files land at `<mirror_path>/<source-relative-path>`.

Outcome: `collected`.

### Mirror 5 — Write back + log + pointers

Set `lazy.settings.json[wiki.scopes][<id>].mirror` to:

```json
{
  "url": "<url>",
  "branch": "<branch, key omitted when blank>",
  "source_paths": ["<...>"],
  "exclude": ["<...>", "(key omitted when empty)"],
  "mirror_path": "<path>"
}
```

Then add the glob `<mirror_path>/**` to the same scope's `paths` array when it is not already there — the mirror files become nodes only through `paths`, and this wizard owns that wiring (`/lazy-wiki.doctor` flags the desync as `mirror-paths-uncovered`). Preserve all other keys; write with `Write`. Because `paths` changed, refresh the navigation rule's `## Coverage` per the Phase 9 recipe (same locate/replace/commit rules).

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "mirror scope_id=<id>"`).

Print two pointers (no questions):
- *"Re-run `/lazy-wiki.install` to register the daemon schedule routine; the manual run is `Bash(lazycortex-wiki mirror-sync <id>)` from any session — fetch, sync, commit, and the git-watch `lazy-wiki.scan` picks the changed files up for curation."*
- *"Mirror bodies are written by the sync — hand-edits to a mirrored node's body are overwritten; operator state lives in the pin keys and survives."*

Outcome: `written`, `logged`, and `coverage-<refreshed|unchanged|absent>`.

## Terms branch — `/lazy-wiki.configure terms`

Configures one scope of `lazy.settings.json[terms.scopes]` — the terms dictionary that keeps one concept from growing a second name. A scope declares which documents the dictionary serves, which file holds it, and which of those documents are **not** term sources. Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Terms 1 — Verify install + pick scope + mode`
- `Terms 2 — Collect paths globs`
- `Terms 3 — Collect dictionary file + create`
- `Terms 4 — Collect source_exclude`
- `Terms 5 — Write back + exclude from wiki scopes`
- `Terms 6 — Register the scan routine`
- `Terms 7 — Log + pointers`
- `Report`

### Terms 1 — Verify install + pick scope + mode

Same as Phase 1: resolve `<repo-root>`, read `lazy.settings.json`, abort with *"Run `/lazy-wiki.install` first."* when the file is absent. When it has no `terms` key, abort: *"Run `/lazy-wiki.install` first — the `terms` section is missing."*

`AskUserQuestion`: *"Create a new terms scope, edit an existing one, or remove one?"* — offer `create` / `edit` / `remove`, listing the existing `terms.scopes` ids. With no scopes on record, `create` is the only option; do not offer the other two.

On `create`, collect the id: *"Scope id (lowercase slug)?"* — must match `^[a-z][a-z0-9_-]*$`, must not collide with an existing id; re-ask on either failure.

On `remove`, jump straight to the removal path in `Terms 5`; `Terms 2`–`Terms 4` are marked `skipped-per-user-choice`.

Outcome: `verified` + `mode-<create|edit|remove>`.

### Terms 2 — Collect paths globs

`AskUserQuestion`:
- New mode: *"Which documents does this dictionary serve — comma-separated globs (e.g. `specs/**/*.md`)? A document under them may consult the dictionary."*
- Edit mode: *"Served documents (current: `<current paths joined>`; comma-separated, Enter to keep):"*

Split on commas, trim, discard empties; at least one entry, re-ask if empty.

**Refuse an overlap.** Compare the collected globs against every other `terms.scopes` entry's `paths`. When a document could match two scopes, the dictionary that owns it is ambiguous — say which scope collides and on which glob, and re-ask. This is the wizard's rubber; the doctor's `config` finding is the second one, for settings written by hand.

Outcome: `collected`.

### Terms 3 — Collect dictionary file + create

`AskUserQuestion`:
- New mode: *"Path of the dictionary file for this scope (repo-relative, e.g. `specs/terms.md`)?"*
- Edit mode: *"Dictionary path (current: `<current file>`; Enter to keep):"*

Required, no default — re-ask until non-empty. Then `Bash(test -f <repo-root>/<file>)`; when absent, `Bash(mkdir -p <parent-dir>)` and `Write` an empty file. An existing file is never touched or truncated — a quiet recreation would destroy every term it holds.

Outcome: `collected` + `dictionary-<created|already-present>`.

### Terms 4 — Collect source_exclude

`source_exclude` names the documents the dictionary still **serves** but never **takes terms from**. It is deliberately not the wiki's `exclude_paths`: an excluded document may still consult the dictionary, which is what a test report writer needs.

Seed the array with the dictionary itself plus every tool-report glob, and show them as the default:

- the dictionary itself (`<file>`) — without it every term trivially "occurs in a document of the scope" and the dead-term check can never fire once;
- `**/code-report.md`, `**/data-report.md`, `**/docs-report.md`, `**/test-report.md` — the tool-type build journals, appended dozens of times per implementation, setting no terminology. An operator-declared tool type brings its own `report_doc`; when the repo declares one beyond the shipped four, offer its glob in the same seed.

Add `<upstream-mirror-glob>/**` to the seed when the repo carries an upstream mirror tree whose files fall under the collected `paths` — mirrored foreign markdown would otherwise fill the dictionary with another studio's vocabulary, and the doctor would then propose edits to mirrors that must not be edited.

`AskUserQuestion`: *"Are plan documents (`code-plan.md`, `test-plan.md`) sources of terminology for this dictionary?"* — options `yes, take terms from them` / `no, exclude them`. On `no`, add `**/code-plan.md` and `**/test-plan.md` to the array, plus the `plan_doc` glob of any operator-declared tool type that names one.

`AskUserQuestion`: *"Anything else to exclude as a term source — comma-separated globs, or blank for none:"* — append what comes back.

Outcome: `collected`.

### Terms 5 — Write back + exclude from wiki scopes

**Create / edit.** Set `lazy.settings.json[terms.scopes][<id>]` to:

```json
{
  "paths": ["<...>"],
  "source_exclude": ["<...>"],
  "file": "<path>"
}
```

Preserve every other key; write with `Write`.

Then **protect the dictionary from the wiki curator**: for every `wiki.scopes` entry whose `paths` globs cover `<file>`, append `<file>` to that scope's `exclude_paths` when it is not already there. The dictionary carries no frontmatter by design, so it has none of the `wiki_role` self-defence `topics.md` has; without this entry the wiki curator appends a `# See also` block to it within a scan tick and the file stops being its own truth.

**Remove.** Delete the `terms.scopes[<id>]` entry and drop from every `wiki.scopes` entry's `exclude_paths` the entries this wizard put there for that scope's dictionary. Then `AskUserQuestion`: *"Keep the dictionary file `<file>`, or delete it?"* — options `keep` / `delete`; on `delete`, `Bash(rm <repo-root>/<file>)`.

Outcome: `written` (or `removed`).

### Terms 6 — Register the scan routine

One routine per scope: `path_filter` is a single pathspec string and cannot span a scope's unrelated trees, so a shared scanner is impossible for arbitrary scopes.

Resolve the watched branch with `Bash(git rev-parse --abbrev-ref HEAD)`. Register through the registrar rather than hand-writing JSON — it validates the record's shape:

```
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.terms-scan-<id> type=git watch=changed_files branch=<branch> interval_sec=60 path_filter=<first paths glob> filter.frontmatter.review_active.not_in=[true] filter.folder_note=false expert=wiki.terms-curator protocols=lazycortex-wiki:lazy-wiki.terms-protocol request.kind=curate request.file={path} timeout_sec=900")
```

`protocols` is declared on the routine, not on the expert — that is the only channel by which the curator receives its own field contract in the job prompt. The `review_active` filter keeps documents under an open review out of the dictionary: a review can still rewrite or reject them, and a term lifted from a draft would surface as a divergence the moment the review closed.

**Edit mode rewrites rather than patches.** The registrar refuses to overwrite an existing record, so when `paths` changed, first `Skill(skill: "lazycortex-core:lazy-routine.unregister", args: "name=lazy-wiki.terms-scan-<id>")`, then register again with the new `path_filter`. **Remove mode** unregisters and stops.

When `daemon.enabled` is `false` in the tracked settings, skip the registration silently and state `skipped-daemon-disabled` — a routine that cannot fire is dead config, and the dictionary is still readable and still curatable by hand.

Outcome: `registered` / `re-registered` / `unregistered` / `skipped-daemon-disabled`.

### Terms 7 — Log + pointers

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "terms <mode> scope_id=<id>"`).

Print two pointers (no questions):
- *"A writing expert consults this dictionary through `/lazy-wiki.terms`; the curator fills it from finished documents on its own."*
- *"The corpus written before this scope existed was never seen by the routine — run the terms section of `/lazy-wiki.doctor` for a full pass over it."*

Outcome: `logged`.

## Structure branch — `/lazy-wiki.configure structure`

Configures `lazy.settings.json[structure]` — the section that drives the project-structure map `docs/structure.md`. The map's path is fixed by convention and is not asked. Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Structure 1 — Verify install + load section`
- `Structure 2 — Collect depth_profiles`
- `Structure 3 — Collect exclude`
- `Structure 4 — Write back`
- `Structure 5 — Register the scan routines`
- `Structure 6 — Log + pointers`
- `Report`

### Structure 1 — Verify install + load section

Resolve `<repo-root>`, read `lazy.settings.json`; abort with *"Run `/lazy-wiki.install` first."* when the file is absent, or with *"Run `/lazy-wiki.install` first — the `structure` section is missing."* when it has no `structure` key. A non-empty `depth_profiles` means edit mode: persisted values shown, Enter keeps them.

Outcome: `verified`.

### Structure 2 — Collect depth_profiles

Classes are collected one at a time; after each, ask whether to add another. Per class, two questions:

- *"Class name (a short label, e.g. `code`, `specs`, `tests`)?"* — must be unique within the section; re-ask on a duplicate.
- *"Glob(s) for this class, comma-separated (e.g. `src/**, cli/**`), and its depth — `file` (directory line + per-file lines for load-bearing files), `dir` (directory line only), or `brief` (half a line)?"* — at least one glob; depth must be one of the three.

**Warn on overlap** between two classes' globs — the first class by key order wins on a shared path, and that precedence should be chosen, not discovered. Warn only; overlap is legal.

Edit mode offers each existing class for keep / change / remove before offering to add new ones.

Outcome: `collected`.

### Structure 3 — Collect exclude

`AskUserQuestion`: *"Paths the map must not describe — comma-separated globs, or blank to keep just the default:"*. Always ensure `docs/structure.md` itself is in the array — the one mandatory entry (without it the map describes itself and the curator's own commit wakes the scan in a loop); append it silently when missing. Gitignored trees need no entry: the git watches never see them.

Outcome: `collected`.

### Structure 4 — Write back

Set `lazy.settings.json[structure]` to the collected `depth_profiles` and `exclude`, preserving `_version` and every other key; write with `Write`.

Outcome: `written`.

### Structure 5 — Register the scan routines

Three git routines, one per event class, because one `watch` covers one status set: `changed_files` passes only `A`/`M`, `deleted_files` only `D`, and a rename under git's default `diff.renames=true` arrives as `R`, which both of those drop — without the third routine a directory rename silently stales the map. (With `diff.renames=false` a rename decomposes into `D`+`A` and lands in the first two — the mechanism degrades to a correct result, not to a breakage.)

Resolve the watched branch with `Bash(git rev-parse --abbrev-ref HEAD)`. Register each through the registrar:

```
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan type=git watch=changed_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=curate request.path={path} request.status={status} timeout_sec=900")
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan-deletes type=git watch=deleted_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=curate request.path={path} request.status={status} timeout_sec=900")
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan-renames type=git watch=renamed_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=rename request.old_path={old_path} request.new_path={new_path} timeout_sec=900")
```

The rename routine carries a **different** `request` because `renamed_files` exposes different placeholders — `{old_path}` / `{new_path}`, not `{path}` / `{status}`; a shared template would `KeyError` on substitution and fail the tick on every rename. `path_filter` is omitted deliberately — the routines watch the whole tracked tree; the fine-grained cut is `exclude`, applied by the curator. The `review_active` filter keeps documents under an open review out of the map until the review closes and the file changes one last time; files without frontmatter pass it (`not_in [true]` holds for an absent key).

When `daemon.enabled` is `false` in the tracked settings, skip all three silently and state `skipped-daemon-disabled` — the map still works through `/lazy-wiki.structure rebuild`.

Edit mode: a routine already registered is left as is (`already-present`); when the section was reconfigured in a way the routines do not carry (they have no `path_filter`), nothing needs re-registering.

Outcome: `registered` / `already-present` / `skipped-daemon-disabled`.

### Structure 6 — Log + pointers

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "structure"`).

Print two pointers (no questions):
- *"Build the initial map with `/lazy-wiki.structure rebuild` — the routines only keep an existing map current, they never create it."*
- *"Re-run `/lazy-wiki.install` to register the `wiki.structure-curator` expert if it is not on record yet."*

Outcome: `logged`.

## Vault branch — `/lazy-wiki.configure vault`

Configures the two repository-wide keys of `lazy.settings.json[wiki]` — `tag_axes`, the closed axis vocabulary every scope narrows from, and `exclude`, the glob list unioned into every scope's `exclude_paths`. No other branch reaches them: the scope branch only narrows the vocabulary and only adds exclusions on top of this list. Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Vault 1 — Verify install + load section`
- `Vault 2 — Collect tag_axes`
- `Vault 3 — Collect exclude`
- `Vault 4 — Write back + log`
- `Report`

### Vault 1 — Verify install + load section

Same as Phase 1: resolve `<repo-root>`, read `lazy.settings.json`, abort with *"Run `/lazy-wiki.install` first."* when the file or its `wiki` key is missing. Both keys are seeded by the install, so a section carrying them is the normal case — show each persisted value and let Enter keep it.

Outcome: `verified`.

### Vault 2 — Collect tag_axes

`AskUserQuestion`: *"Tag axes — the closed vocabulary of classification dimensions for the whole vault (current: `<current tag_axes joined or "none">`; comma-separated, Enter to keep):"*

Split on commas, trim, discard empties, lowercase-normalise each slug. Keep `doc-kind`: it is the mandatory axis `/lazy-wiki.install` unions in, and dropping it here is undone by the next install run. Before writing a set that removes any other axis, name what it costs — every `wiki/<axis>/…` tag already carried by a node on that axis becomes unknown (the doctor's `unknown-axis` finding), and every scope narrowing to it silently loses it — then ask whether to proceed.

An axis added here becomes available to every scope at once; nothing else has to be edited for a scope to use it, since a scope that declares no narrowing speaks the full vocabulary.

Outcome: `collected`.

### Vault 3 — Collect exclude

`AskUserQuestion`: *"Exclude glob(s) no scope may opt out of (current: `<current exclude joined or "none">`; comma-separated, blank to clear, Enter to keep):"*

Split on commas, trim, discard empties. Keep `docs/structure.md` — the project-structure map is a generated document with no frontmatter to defend itself, and without the entry the curator appends a `# See also` block to it. Do not add the `wiki.domains.output` tree: it is excluded structurally from the setting itself, and an entry here would go stale the moment the output directory moves.

Outcome: `collected`.

### Vault 4 — Write back + log

Set `lazy.settings.json[wiki].tag_axes` and `lazy.settings.json[wiki].exclude` to the collected arrays, preserving `scopes`, `domains`, `_version`, and every other key; write with `Write`.

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "vault"`).

Outcome: `written` and `logged`.

## Report

One line per task in the canonical list of the branch that ran, with its outcome word. Scope-branch summary line: `scope <id> <created|updated>: paths=<count>, tag_axes=[<axes>], topics_index=<path>, review-skip=<on|off>, folder_note=<value held in the filter>`. Domains-branch summary line: `wiki.domains <created|updated>: code=<count>, dictionary=<path>, output=<path>, language=<language>`. Mirror-branch summary line: `scope <id> mirror <created|updated>: url=<url>, source_paths=<count>, exclude=<count>, mirror_path=<path>`. Terms-branch summary line: `terms scope <id> <created|updated|removed>: paths=<count>, file=<path>, source_exclude=<count>, routine=<registered|re-registered|unregistered|skipped-daemon-disabled>`. Structure-branch summary line: `structure <created|updated>: classes=<count>, exclude=<count>, routines=<registered|already-present|skipped-daemon-disabled>`. Vault-branch summary line: `wiki vault updated: tag_axes=[<axes>], exclude=<count>`.

## Failure modes

- **Phase 1 aborts: "run /lazy-wiki.install first"** — `lazy.settings.json` is absent or missing the `wiki` key → run `/lazy-wiki.install` then re-run this wizard.
- **Phase 2 re-asks on invalid id** — id doesn't match `^[a-z][a-z0-9_-]*$` → enter a valid slug (lowercase letters, digits, hyphens, underscores; must start with a letter).
- **Phase 3 re-asks on empty paths** — at least one path glob is required; blank input is not accepted.
- **Phase 5 offers no axes to pick from** — `wiki.tag_axes` is empty, so there is no vocabulary to narrow and the scope is written without one → run `/lazy-wiki.install` (it unions the mandatory `doc-kind` axis in) or `/lazy-wiki.configure vault` to declare the vocabulary, then re-run this wizard for the scope.
- **Phase 6 re-asks on blank topics_index** — a relative file path is required (the file need not exist yet).
- **Phase 9 reports `absent`** — no `lazy-wiki.navigation.md` in either rules directory, so sessions get no coverage trigger → run `/lazy-wiki.install`, then re-run this wizard to fill the section.
- **Mirror 1 aborts: "no scopes configured"** — the mirror block nests inside an existing scope → create the scope with `/lazy-wiki.configure` first, then re-run `/lazy-wiki.configure mirror`.
- **Terms 1 aborts: "the `terms` section is missing"** — `lazy.settings.json` predates the terms mechanism → run `/lazy-wiki.install`, then re-run `/lazy-wiki.configure terms`.
- **Terms 2 re-asks on an overlapping glob** — another terms scope already serves a document the new globs would match, and one document belongs to one dictionary → narrow the globs, or edit the colliding scope instead.
- **Terms 6 reports `skipped-daemon-disabled`** — the project does not run the background daemon, so nothing dispatches the curator → the dictionary still works for reading; run the terms section of `/lazy-wiki.doctor` to fill and check it by hand.
