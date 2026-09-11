---
name: lazy-wiki.configure
description: "Use when the user wants to add a wiki scope, change which paths the wiki covers, edit an existing scope's globs, axes, exclusions, or topics-index path — or set up domain-spec generation (`/lazy-wiki.configure domains`: code globs, dictionary, output tree, language) — or mirror a foreign repo's markdown into a scope (`/lazy-wiki.configure mirror`: source url/branch, source globs, excludes, mirror directory) — or set up a terms dictionary (`/lazy-wiki.configure terms`: which documents it serves, where the dictionary file lives, which documents are term sources) — or configure the project-structure map (`/lazy-wiki.configure structure`: depth profiles, exclusions, the three scan routines) — or edit the vault-wide wiki keys themselves (`/lazy-wiki.configure vault`: the `tag_axes` vocabulary every scope narrows from, the `exclude` globs every scope inherits). Wizard over .claude/lazy.settings.json[wiki.scopes] / [wiki.tag_axes] / [wiki.exclude] / [wiki.domains] / [terms.scopes] / [structure], one question per turn via AskUserQuestion; also refreshes the Coverage section of the installed navigation rule."
allowed-tools: Read, Edit, Write, AskUserQuestion, Skill, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(git ls-files *), Bash(git commit *), Bash(cp *), Bash(test *), Bash(rm *), Agent
---
# lazy-wiki.configure

Interactive wizard. Creates or edits a scope entry in `lazy.settings.json[wiki.scopes]` for the current repo — or, invoked as `/lazy-wiki.configure domains`, the `wiki.domains` section that drives domain-spec generation (see **Domains branch** below) — or, invoked as `/lazy-wiki.configure mirror`, an existing scope's nested `mirror` block that mirrors a foreign repo's markdown into the vault (see **Mirror branch** below) — or, invoked as `/lazy-wiki.configure terms`, a scope of the `terms` section that drives the terms dictionary (see **Terms branch** below) — or, invoked as `/lazy-wiki.configure structure`, the `structure` section that drives the project-structure map (see **Structure branch** below) — or, invoked as `/lazy-wiki.configure vault`, the repository-wide keys of the `wiki` section itself: the axis vocabulary `wiki.tag_axes` every scope narrows from, and the exclusion list `wiki.exclude` every scope inherits (see **Vault branch** below). Each field is collected one question at a time via `AskUserQuestion`. This wizard only collects **genuine project config that cannot be derived** — scope globs, exclude globs, and classification axes. Every path a file lands at is derived and merely announced: the topics index from the scope's own first glob, and the review-skip filter, terms dictionary, domain dictionary, and domain output directory from shipped defaults. Where a generated file sits is a preference an operator changes in edit mode on the day it matters, and asking it at setup, before there is anything in the tree to place it against, buys an answer nobody is equipped to give yet. There is no install-scope question (the wizard always edits the current repo's `lazy.settings.json`) and no environment probe.

**Read-first.** Re-running for an existing scope `id` (or for an existing `wiki.domains` section) enters edit mode: each persisted value is read from `lazy.settings.json` first and shown as the current value; pressing Enter keeps it untouched. A field is re-asked only to let the operator change it — never to re-collect a value already on record.

Prerequisite: `/lazy-wiki.install` has run (the `wiki` settings section exists).

## Execution discipline (MANDATORY — read before any action)

This skill has six mutually exclusive branches; exactly one runs per invocation. The **scope branch** (default) has 9 ordered steps plus Report; the **domains branch** (argument `domains`, or the operator asks to configure domain specs) has 5 ordered steps plus Report; the **mirror branch** (argument `mirror`, or the operator asks to mirror a foreign repo into the wiki) has 5 ordered steps plus Report; the **terms branch** (argument `terms`, or the operator asks to set up a terms dictionary) has 7 ordered steps plus Report; the **structure branch** (argument `structure`, or the operator asks to configure the structure map) has 6 ordered steps plus Report; the **vault branch** (argument `vault`, or the operator asks to edit the axis vocabulary or the repository-wide exclusions) has 4 ordered steps plus Report. The executing agent MUST NOT skip, merge, reorder, or silently omit any step of the chosen branch. To make dropped steps structurally impossible:

1. **Before calling any other tool**, decide the branch from the invocation, then write out the step ledger — one line per step of that branch, each marked `pending` — no merging, no abbreviation, no renaming, and no entries from another branch. The scope branch's canonical list (use these titles verbatim; each other branch's list is in its own section below):
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
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** Outcomes: `verified` / `collected` / `derived` / `skipped-per-user-choice` / `written` / `logged` / `refreshed` / `unchanged` / `absent` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.
5. **Orient before the branch's first `AskUserQuestion`.** Print two to four lines naming what the section governs, which artifact it produces and where that artifact lives, and what the values being collected mean — the vocabulary of the questions ahead (`depth_profiles` classes and their three depths, `source_exclude` versus `exclude_paths`, `tag_axes`, a `mirror` block). An operator who has not read this SKILL.md cannot answer a question phrased in its internal vocabulary, and a guessed answer is written to settings as a decision. Say it once per invocation, before the first question; do not repeat it per question.

## Phase 1 — Verify install + load settings

Run `Bash(git rev-parse --show-toplevel)` to get `<repo-root>`. `Read` `<repo-root>/.claude/lazy.settings.json`. If the file is absent, abort: *"Run `/lazy-wiki.install` first."* If the file exists but has no `wiki` key, abort: *"Run `/lazy-wiki.install` first — the `wiki` section is missing."* Hold the parsed object in memory.

Outcome: `verified`.

## Phase 2 — Collect scope id

Context (print before asking):
- Where: /lazy-wiki.configure · Phase 2 — Collect scope id; target `lazy.settings.json[wiki.scopes]`
- Found: scope ids on record `<ids joined, or none>`
- Why asking: the id names a new scope or picks an existing one to edit — nothing on record derives into a name
- Answers: an existing id — edit mode, persisted values shown, Enter keeps each; a new id — the scope is created in Phase 8 under `wiki.scopes[<id>]`; the id is the key and is never re-asked
AskUserQuestion: header "Scope id", question "Id of the wiki scope to create or edit in `lazy.settings.json[wiki.scopes]` — lowercase letters, digits, hyphens, underscores, e.g. `docs` or `codebase` (existing: `<ids>`)?", options one per existing id (description: its `paths`) plus free text for a new one.

Validate: must match `^[a-z][a-z0-9_-]*$`. Re-ask until valid.

If an entry already exists at `wiki.scopes[<id>]`, inform the user: *"Scope `<id>` already exists — entering edit mode. Existing values will be shown; press Enter to keep them."* Hold edit-mode flag.

Outcome: `collected`.

## Phase 3 — Collect paths globs

Context (print before asking):
- Where: Phase 3 — Collect paths globs; target scope `<id>`
- Found: new mode — no `paths` on record; edit mode — current `paths`: `<current paths joined>`
- Why asking: which files the wiki covers is project config nothing can derive
- Answers: comma-separated globs — written to `wiki.scopes[<id>].paths` in Phase 8 and rendered into the navigation rule's Coverage in Phase 9; Enter (edit mode) — current list kept; re-asked only on the next edit run
AskUserQuestion: header "Scope paths", question — new mode: "Path glob(s) that define wiki scope `<id>` — comma-separated (e.g. `docs/**/*.md, src/**/*.py`)?"; edit mode: "Path glob(s) for scope `<id>` (current: `<current paths joined>`; comma-separated, Enter to keep)?"; free text.

Split on commas, trim whitespace, discard empty entries. Must have at least one entry; re-ask if empty. Hold as an array.

Outcome: `collected`.

## Phase 4 — Collect exclude_paths

**A spec catalog's excludes are not asked.** When the settings loaded in Phase 1 carry a `spec` section and one of this scope's `paths` globs starts with `<spec.vault_root>/` (default `specs`), skip the question: print one line — *"scope `<id>` covers the spec catalog; its excludes (request inbox, plan and report working papers) are seeded by `/lazy-spec.install`, nothing to collect here"* — hold the current `exclude_paths` unchanged (new mode: no key) and state outcome `derived`.

Otherwise ask. The `Found` line lists only what is on record; never propose candidate globs derived from reading the tree — an operator who accepts an invented exclusion silently drops nodes from the wiki.

Context (print before asking):
- Where: Phase 4 — Collect exclude_paths; target scope `<id>`
- Found: new mode — no `exclude_paths` on record; edit mode — current: `<current exclude_paths joined or "none">`; repository-wide `wiki.exclude` already carries `<wiki.exclude joined>`
- Why asking: what this scope omits beyond the vault-wide list is project config
- Answers: comma-separated globs — written as `wiki.scopes[<id>].exclude_paths` in Phase 8, rendered into Coverage in Phase 9; blank — no key (new mode) or the key cleared (edit mode); Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion: header "Scope excludes", question — new mode: "Exclude glob(s) to omit from wiki scope `<id>` beyond `wiki.exclude` — comma-separated, or blank for none (e.g. `**/.obsidian/**, **/node_modules/**`)?"; edit mode: "Exclude glob(s) for scope `<id>` (current: `<current exclude_paths joined or "none">`; comma-separated, blank to clear, Enter to keep)?"; free text.

Split on commas, trim, discard empty entries. Empty input means no `exclude_paths` key (or clear existing). Hold as an array (may be empty).

**The scope list is additive on top of `wiki.exclude`.** The section-level `wiki.exclude` list is unioned into every scope's exclusions, so what is collected here is only what this scope excludes *beyond* the repository-wide set — never a repetition of it. Two entries in particular are already covered and must not be re-collected here: `docs/structure.md` (the fixed-path project-structure map, seeded into `wiki.exclude` by `/lazy-wiki.install`), and the generated domain-spec tree, which is derived from `wiki.domains.output` and excluded structurally without being declared anywhere. Edit the repository-wide list itself with `/lazy-wiki.configure vault`.

Outcome: `collected` / `derived`.

## Phase 5 — Collect tag_axes

The axis vocabulary belongs to the repository, not to the scope: `wiki.tag_axes` declares the closed set for the whole vault, and a scope's own `tag_axes` list only **narrows** it to the axes this scope actually uses. A scope can never widen the vocabulary — an axis the repository does not declare is not offered here and cannot be added here.

Read `wiki.tag_axes` from the settings loaded in Phase 1 and offer exactly those axes. An empty vocabulary means there is nothing to narrow — say so, skip the question, hold an empty array, and point at `/lazy-wiki.configure vault`, which is where the vocabulary is authored.

Context (print before asking):
- Where: Phase 5 — Collect tag_axes; target scope `<id>`
- Found: vault vocabulary `wiki.tag_axes`: `<repository tag_axes joined>`; edit mode — current narrowing: `<current tag_axes joined or "all">`
- Why asking: which axes this scope classifies on is the operator's; a scope can only narrow the vault's set
- Answers: a subset — written to `wiki.scopes[<id>].tag_axes`, the curator receives only those; blank — empty array, the scope uses every vault axis; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion: header "Scope tag axes", question — new mode: "Which of the vault's tag axes does wiki scope `<id>` use — `<repository tag_axes joined>` — comma-separated, or blank for all of them?"; edit mode: "Tag axes for scope `<id>` (vault vocabulary: `<repository tag_axes joined>`; current narrowing: `<current tag_axes joined or "all">`; comma-separated, blank for all, Enter to keep)?"; options one per vault axis (multi-select; description: the `wiki/<axis>/…` tags it governs).

Split on commas, trim, discard empty entries. Lowercase-normalise each axis slug. Drop — and name — any entry outside the vault vocabulary rather than writing it: it would be silently ignored on every dispatch. Blank input means the scope uses the full vocabulary; hold it as an empty array.

Outcome: `collected`.

## Phase 6 — Collect topics_index

**New mode does not ask**: derive the path from the scope's own first `paths` glob — its leading literal directory segments, plus `topics.md`. A scope covering `specs/**/*.md` derives `specs/topics.md`; one covering `docs/**/*.md` derives `docs/topics.md`; a glob with no literal directory prefix at all (`**/*.md`) derives `topics.md` at the repo root. The index belongs beside the material it indexes, which is the only place derivable without an answer. Print one line naming the derived path, outcome `derived`. Moving it is an edit-mode change or a hand edit of `lazy.settings.json`; the file is created on the first full scan either way, so nothing is written now.

Edit mode asks:

Context (print before asking):
- Where: Phase 6 — Collect topics_index; target scope `<id>`
- Found: current: `<current topics_index>` (file `<present|absent>`)
- Why asking: the path is on record and only the operator can decide to move the index
- Answers: a repo-relative path — written to `wiki.scopes[<id>].topics_index`, the index rebuilt there by the next full scan; Enter — the current value kept; re-asked only on the next edit run
AskUserQuestion (edit mode only): header "Topics index path", question "Topics index path for scope `<id>` (current: `<current topics_index>`; Enter to keep)?"; free text.

Trim whitespace. Must be non-empty; re-ask if blank. The file need not exist yet — it is created on first full scan.

Outcome: `derived` (new mode) / `collected` (edit mode).

## Phase 7 — Collect filter

The per-scope `filter` excludes a node from the wiki on the fly (the node is not curated, not indexed, not linked while it matches). Two sub-filters: `frontmatter` — the common case is standing down on documents currently under review; `folder_note` — a note named after its own folder (`sync/sync.md`) renders as the folder itself under the folder-notes convention, so it is a structural navigation node, not a document to curate.

`folder_note: false` is not asked — it is the structural default for every scope. Seed it whenever the key is absent (new scope, or an edit-mode scope whose filter predates it); never overwrite an operator's explicit `true`, which selects folder notes exclusively.

The review-skip half is not asked either. Seed `frontmatter.review_active.not_in = [true]` whenever the sub-filter lacks that key: harmless in a repo without lazycortex-review (no document ever carries the flag) and required in one that runs it (a document under an open review must stay out of the wiki until review closes). Never overwrite an operator's own predicate on that key. Hold the merged filter `{ "frontmatter": { "review_active": { "not_in": [true] } }, "folder_note": false }` over whatever is on record.

Richer predicates (other frontmatter keys, `in` allow-lists) follow the same schema as a routine's `filter` block and are hand-editable in `lazy.settings.json` — this wizard seeds the two structural defaults and collects nothing.

Outcome: `derived`.

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

Context (print before asking):
- Where: Domains 2 — Collect code globs; target `lazy.settings.json[wiki.domains].code`
- Found: new mode — no `wiki.domains` on record; edit mode — current `code`: `<current code joined>`
- Why asking: which source files carry `Domain(…)` blocks is project layout
- Answers: comma-separated globs — written to `wiki.domains.code` in Domains 5, scanned by every domain tick; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion: header "Domain code globs", question — new mode: "Code glob(s) to scan for `Domain(…)` blocks in this repo — comma-separated (e.g. `src/**/*.py`)?"; edit mode: "Code glob(s) for `wiki.domains` (current: `<current code joined>`; comma-separated, Enter to keep)?"; free text.

Split on commas, trim, discard empty entries. Must have at least one entry; re-ask if empty. Hold as an array.

Outcome: `collected`.

### Domains 3 — Collect dictionary path + seed

**New mode does not ask**: take the shipped default `docs/guidelines/domain-groups.md`, print one line naming it, outcome `derived`. A different path is an edit-mode change or a hand edit of `lazy.settings.json`. Edit mode asks:

Context (print before asking):
- Where: Domains 3 — Collect dictionary path + seed; target `wiki.domains.dictionary`
- Found: current: `<current dictionary>` (file `<present|absent>`)
- Why asking: the path is on record and only the operator can decide to move it
- Answers: a repo-relative path — written to `wiki.domains.dictionary`; when the file is absent the skeleton template is copied there now, an existing file is never touched; Enter — the current value kept; re-asked only on the next edit run
AskUserQuestion (edit mode only): header "Domain dictionary", question "Dictionary path for `wiki.domains` (current: `<current dictionary>`; Enter to keep)?"; free text.

Then **ensure the dictionary exists** — the configurator owns this guarantee: `Bash(test -f <repo-root>/<dictionary>)`; when absent, seed it from the skeleton template shipped by this plugin — `Bash(mkdir -p <dictionary-parent-dir>)` then `Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/domain-groups.md <repo-root>/<dictionary>)` — and tell the operator it holds a sample group to replace. An existing file is never touched (idempotent; `/lazy-python.knowledge-sweep` is the other creator and builds a populated one).

Outcome: `derived` (new mode) / `collected` (edit mode) + `dictionary-<seeded|already-present>`.

### Domains 4 — Collect output + language

**New mode does not ask** for the output directory: take the shipped default `docs/domains`, print one line naming it, outcome `derived` for this half. Edit mode asks:

Context (print before asking):
- Where: Domains 4 — Collect output + language; target `wiki.domains.output`
- Found: current: `<current output>`; wiki scopes whose globs reach it: `<id: glob, … or none>`
- Why asking: the directory is on record and only the operator can decide to move the generated tree
- Answers: a repo-relative directory — written to `wiki.domains.output`, the tree materialised there by `/lazy-wiki.domain-sync` and the domain routines, excluded from every wiki scope structurally; Enter — the current value kept; re-asked only on the next edit run
AskUserQuestion (output, edit mode only): header "Domain output dir", question "Output directory for `wiki.domains` (current: `<current output>`; Enter to keep)?"; free text.

**Overlap warning:** check every `wiki.scopes` entry's `paths` globs against the chosen output directory; when a glob covers files under it, warn — *"Scope `<id>` glob `<glob>` reaches `<output>`, which is excluded from every scope regardless — the glob claims nothing there. Narrow it so the scope says what it actually covers."* Warn only. The generated tree is derived from this very setting and excluded structurally, so the warning is about a misleading glob, never about a contested file: handing the tree to the wiki is not something a scope can do.

Then the language: sample a few of the vault's authored spec/doc files to judge the language they are written in, and propose it as the default.

Context (print before asking):
- Where: Domains 4 — Collect output + language; target `wiki.domains.language`
- Found: `<n>` authored docs sampled, written in `<detected>`; edit mode — current: `<current language>`
- Why asking: the language the generated docs are written in is an editorial choice the sample only suggests
- Answers: a language — written to `wiki.domains.language`, every generated group doc is written in it; Enter — `<detected>` (new mode) or the current value (edit mode); re-asked only on the next edit run
AskUserQuestion (language): header "Domain docs language", question — new mode: "Language for the generated domain docs under `<output>` (Enter for `<detected>`, the language this vault's specs are written in)?"; edit mode: "Language for the generated domain docs (current: `<current language>`; Enter to keep)?"; free text.

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

Same as Phase 1: resolve `<repo-root>`, read `lazy.settings.json`, abort with *"Run `/lazy-wiki.install` first."* when the file or its `wiki` key is missing. The scope MUST already exist; when `wiki.scopes` is empty, abort: *"No scopes configured — create one with `/lazy-wiki.configure` first."* Otherwise pick it.

Context (print before asking):
- Where: /lazy-wiki.configure mirror · Mirror 1 — Verify install + pick scope; target `lazy.settings.json[wiki.scopes]`
- Found: configured scopes `<id: paths, …>`; scopes already carrying a `mirror` block: `<ids or none>`
- Why asking: a mirror nests inside exactly one scope, and which one is the operator's choice
- Answers: one option per scope id — its `mirror` block is created in Mirror 5 (edit mode when it already has one: persisted values shown, Enter keeps them); persisted under `wiki.scopes[<id>].mirror`; never re-asked for that block
AskUserQuestion: header "Mirror scope", question "Which configured wiki scope gets the mirror block (`<ids>`)?", options one per scope id (description: its `paths`, and `has mirror` when one is on record).

If the chosen scope already carries a `mirror` block, announce edit mode (persisted values shown, Enter keeps them).

Outcome: `verified`.

### Mirror 2 — Collect url + branch

Context (print before asking):
- Where: Mirror 2 — Collect url + branch; target `wiki.scopes[<id>].mirror.url`
- Found: new mode — none on record; edit mode — current `url`: `<current url>`
- Why asking: the source repository is external config nothing local can derive
- Answers: a git URL — written to `mirror.url`, cloned into the gitignored runtime dir on every sync; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion (url): header "Mirror source URL", question "Git URL of the repository to mirror into wiki scope `<id>`?" (edit mode: "… (current: `<current url>`; Enter to keep)?"); free text — must be non-empty; re-ask if blank.

Context (print before asking):
- Where: Mirror 2 — Collect url + branch; target `wiki.scopes[<id>].mirror.branch`
- Found: new mode — none on record; edit mode — current `branch`: `<current branch or "source default">`
- Why asking: which branch of `<url>` is the wanted one is the operator's
- Answers: a branch name — written to `mirror.branch`, the clone checks it out; blank — no `branch` key, the clone follows the source's default; Enter (edit mode) — kept
AskUserQuestion (branch): header "Mirror branch", question "Branch of `<url>` to mirror (Enter for the source's default branch)?"; free text.

Outcome: `collected`.

### Mirror 3 — Collect source_paths + exclude

Context (print before asking):
- Where: Mirror 3 — Collect source_paths + exclude; target `wiki.scopes[<id>].mirror.source_paths`
- Found: new mode — none on record; edit mode — current `source_paths`: `<current source_paths joined>`
- Why asking: which markdown of `<url>` is wanted in this vault is per-mirror config
- Answers: comma-separated globs — written to `mirror.source_paths`, only `.md` files under them are mirrored on every sync; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion (source_paths): header "Mirror source globs", question "Glob(s) of markdown to mirror from `<url>`, relative to the source repo root — comma-separated (e.g. `docs/domains/**`); only `.md` files under them are mirrored?"; free text — must have at least one entry; re-ask if empty.

Context (print before asking):
- Where: Mirror 3 — Collect source_paths + exclude; target `wiki.scopes[<id>].mirror.exclude`
- Found: new mode — none on record; edit mode — current `exclude`: `<current exclude joined or "none">`
- Why asking: which of the source's service files must not become nodes is per-mirror config
- Answers: comma-separated globs — written to `mirror.exclude`, matching files are never mirrored; blank — no `exclude` key; Enter (edit mode) — kept
AskUserQuestion (exclude): header "Mirror excludes", question "Exclude glob(s) under `<source_paths>` of `<url>`, comma-separated, or blank for none — put the source's service files here, e.g. a generated index like `docs/domains/domains.md` that would otherwise become a node and go to pointless curation?"; free text.

Outcome: `collected`.

### Mirror 4 — Collect mirror_path

Context (print before asking):
- Where: Mirror 4 — Collect mirror_path; target `wiki.scopes[<id>].mirror.mirror_path`
- Found: new mode — none on record; edit mode — current `mirror_path`: `<current mirror_path>`; scope `paths` today: `<paths joined>`
- Why asking: where foreign markdown lands in this vault is a layout choice with no default
- Answers: a repo-relative directory — written to `mirror.mirror_path`, files land at `<mirror_path>/<source-relative-path>`, and `<mirror_path>/**` joins the scope's `paths` in Mirror 5; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion: header "Mirror directory", question "Directory in this vault where the mirror of `<url>` lands for scope `<id>` (repo-relative)?"; free text — **required, no default**; re-ask until non-empty. Files land at `<mirror_path>/<source-relative-path>`.

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

Then add the glob `<mirror_path>/**` to the same scope's `paths` array when it is not already there — the mirror files become nodes only through `paths`, and this wizard owns that wiring (`/lazy-wiki.audit` flags the desync as `mirror-paths-uncovered`). Preserve all other keys; write with `Write`. Because `paths` changed, refresh the navigation rule's `## Coverage` per the Phase 9 recipe (same locate/replace/commit rules).

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

Context (print before asking):
- Where: /lazy-wiki.configure terms · Terms 1 — Verify install + pick scope + mode; target `lazy.settings.json[terms.scopes]`
- Found: terms scopes on record `<id: file, … or none>`
- Why asking: create, edit, or remove is the operator's intent
- Answers: `create` — a new id is collected next, the scope written in Terms 5, its scan routine registered in Terms 6; `edit` — persisted values shown per field, Enter keeps each, the routine re-registered when `paths` change; `remove` — the entry deleted, its routine unregistered, the dictionary file's fate asked in Terms 5; not persisted, asked on every run
AskUserQuestion: header "Terms scope mode", question "Create a new terms scope, edit an existing one, or remove one (existing: `<ids>`)?", options `create` / `edit` / `remove` with the descriptions above. With no scopes on record, `create` is the only option; do not offer the other two.

On `create`, collect the id.

Context (print before asking):
- Where: Terms 1; target `terms.scopes[<id>]`
- Found: ids already taken `<ids or none>`
- Why asking: the id is the scope's settings key and its routine's name suffix; nothing derives it
- Answers: free text — becomes the key `terms.scopes[<id>]` and the routine `lazy-wiki.terms-scan-<id>`; never re-asked
AskUserQuestion: header "Terms scope id", question "Id for the new terms scope (lowercase slug; taken: `<ids>`)?"; free text — must match `^[a-z][a-z0-9_-]*$`, must not collide with an existing id; re-ask on either failure.

On `remove`, jump straight to the removal path in `Terms 5`; `Terms 2`–`Terms 4` are marked `skipped-per-user-choice`.

Outcome: `verified` + `mode-<create|edit|remove>`.

### Terms 2 — Collect paths globs

Context (print before asking):
- Where: Terms 2 — Collect paths globs; target `terms.scopes[<id>].paths`
- Found: new mode — none on record; edit mode — current `paths`: `<current paths joined>`; other terms scopes' `paths`: `<id: globs, … or none>`
- Why asking: which documents consult this dictionary is per-repo, and one document belongs to one dictionary
- Answers: comma-separated globs — written to `terms.scopes[<id>].paths` in Terms 5, the first glob becomes the scan routine's `path_filter` in Terms 6; a glob overlapping another scope re-asks; Enter (edit mode) — kept; re-asked only on the next edit run
AskUserQuestion: header "Served documents", question — new mode: "Which documents does terms dictionary `<id>` serve — comma-separated globs (e.g. `specs/**/*.md`)? A document under them may consult the dictionary."; edit mode: "Served documents of terms scope `<id>` (current: `<current paths joined>`; comma-separated, Enter to keep)?"; free text.

Split on commas, trim, discard empties; at least one entry, re-ask if empty.

**Refuse an overlap.** Compare the collected globs against every other `terms.scopes` entry's `paths`. When a document could match two scopes, the dictionary that owns it is ambiguous — say which scope collides and on which glob, and re-ask. This is the wizard's rubber; the audit's `config` finding is the second one, for settings written by hand.

Outcome: `collected`.

### Terms 3 — Collect dictionary file + create

**New mode does not ask**: take the shipped default `docs/terms.md` — the project's own documentation tree, never the tree the dictionary serves. A dictionary written inside a served scope is material that scope then scans, which is why the wizard has to fence it out of every covering scope's `exclude_paths` below; `docs/` needs no fence. Print one line naming it, outcome `derived`. Moving it is an edit-mode change or a hand edit of `lazy.settings.json`.

Edit mode asks:

Context (print before asking):
- Where: Terms 3 — Collect dictionary file + create; target `terms.scopes[<id>].file`
- Found: current `file`: `<current file>` (file `<present|absent>`)
- Why asking: the path is on record and only the operator can decide to move the dictionary
- Answers: a repo-relative path — written to `terms.scopes[<id>].file`; an absent file is created empty now, a present one is never touched or truncated; Enter — the current value kept; re-asked only on the next edit run
AskUserQuestion (edit mode only): header "Dictionary file", question "Dictionary path for terms scope `<id>` (current: `<current file>`; Enter to keep)?"; free text.

Trim whitespace; re-ask if blank. Then `Bash(test -f <repo-root>/<file>)`; when absent, `Bash(mkdir -p <parent-dir>)` and `Write` an empty file. An existing file is never touched or truncated — a quiet recreation would destroy every term it holds.

Outcome: `derived` (new mode) / `collected` (edit mode) + `dictionary-<created|already-present>`.

### Terms 4 — Collect source_exclude

`source_exclude` names the documents the dictionary still **serves** but never **takes terms from**. It is deliberately not the wiki's `exclude_paths`: an excluded document may still consult the dictionary, which is what a test report writer needs.

Seed the array with the dictionary itself plus every tool-report glob, and show them as the default:

- the dictionary itself (`<file>`) — without it every term trivially "occurs in a document of the scope" and the dead-term check can never fire once;
- `**/code-report.md`, `**/data-report.md`, `**/docs-report.md`, `**/test-report.md` — the tool-type build journals, appended dozens of times per implementation, setting no terminology. An operator-declared tool type brings its own `report_doc`; when the repo declares one beyond the shipped journals, offer its glob in the same seed only if that report type is declared `append_only: true` — a stage-bearing report such as the `research` tool's `research-report` is content and is never offered for exclusion.

Add `<upstream-mirror-glob>/**` to the seed when the repo carries an upstream mirror tree whose files fall under the collected `paths` — mirrored foreign markdown would otherwise fill the dictionary with another studio's vocabulary, and the audit would then report term repairs against mirrors that must not be edited.

Context (print before asking):
- Where: Terms 4 — Collect source_exclude; target `terms.scopes[<id>].source_exclude`
- Found: seed so far `<file>`, `<report globs>`, `<upstream mirror glob when present>`; edit mode — current `source_exclude`: `<current source_exclude joined>`; plan docs under `paths`: `<count>`
- Why asking: whether plan documents set terminology is an editorial choice
- Answers: `yes, take terms from them` — plan docs stay term sources, the seed is written as is; `no, exclude them` — `**/code-plan.md`, `**/test-plan.md`, and every declared `plan_doc` glob are appended before the write in Terms 5; re-asked only on the next edit run
AskUserQuestion: header "Plan docs as sources", question "Are plan documents (`code-plan.md`, `test-plan.md`) sources of terminology for dictionary `<file>` of terms scope `<id>`?", options `yes, take terms from them` / `no, exclude them` with the descriptions above. On `no`, add `**/code-plan.md` and `**/test-plan.md` to the array, plus the `plan_doc` glob of any operator-declared tool type that names one.

Context (print before asking):
- Where: Terms 4 — Collect source_exclude; target `terms.scopes[<id>].source_exclude`
- Found: array so far `<source_exclude joined>`
- Why asking: further documents that consult the dictionary but must not feed it are per-repo
- Answers: comma-separated globs — appended to `source_exclude` before the write in Terms 5; blank — nothing added; re-asked only on the next edit run
AskUserQuestion: header "More source excludes", question "Anything else under `<paths>` to exclude as a term source for scope `<id>` — comma-separated globs, or blank for none?"; free text — append what comes back.

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

**Any scope whose `exclude_paths` this step touched needs its rendered Coverage back in step.** The navigation rule's `## Coverage` is derived from `paths` / `exclude_paths`, so an entry added or dropped here leaves it stating an exclusion the settings no longer carry — and every session reads that rule, not the settings. When this step changed any scope's `exclude_paths`, refresh the section per the Phase 9 recipe (same locate / replace / commit rules), naming the terms scope in the commit subject instead of a wiki scope. Unchanged `exclude_paths` — nothing to refresh.

**Remove.** Delete the `terms.scopes[<id>]` entry and drop from every `wiki.scopes` entry's `exclude_paths` the entries this wizard put there for that scope's dictionary. Then ask about the file.

Context (print before asking):
- Where: Terms 5 — remove path; target `<repo-root>/<file>`
- Found: `terms.scopes[<id>]` removed from settings; the dictionary at `<file>` `<is absent | holds <n> terms>`
- Why asking: deleting the file is destructive and nothing in settings can restore its terms
- Answers: `keep` — the file stays in the worktree, no longer served or scanned; `delete` — `rm <repo-root>/<file>` now, the terms are gone; not persisted
AskUserQuestion: header "Dictionary file", question "Keep the dictionary file `<file>` of removed terms scope `<id>`, or delete it?", options `keep` / `delete` with the descriptions above; on `delete`, `Bash(rm <repo-root>/<file>)`.

Outcome: `written` (or `removed`).

### Terms 6 — Register the scan routine

One routine per scope: `path_filter` is a single pathspec string and cannot span a scope's unrelated trees, so a shared scanner is impossible for arbitrary scopes.

Resolve the watched branch with `Bash(git rev-parse --abbrev-ref HEAD)`. Register through the registrar rather than hand-writing JSON — it validates the record's shape:

```
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.terms-scan-<id> type=git watch=changed_files branch=<branch> interval_sec=60 path_filter=<first paths glob> filter.frontmatter.review_active.not_in=[true] filter.folder_note=false expert=wiki.terms-curator protocols=lazycortex-wiki:lazy-wiki.terms-protocol request.kind=curate request.file={path} timeout_sec=900")
```

`protocols` is declared on the routine, not on the expert — that is the only channel by which the curator receives its own field contract in the job prompt. The `review_active` filter keeps documents under an open review out of the dictionary: a review can still rewrite or reject them, and a term lifted from a draft would surface as a divergence the moment the review closed.

**Edit mode rewrites rather than patches.** The registrar refuses to overwrite an existing record, so when `paths` changed, first `Skill(skill: "lazycortex-core:lazy-routine.unregister", args: "name=lazy-wiki.terms-scan-<id>")`, then register again with the new `path_filter`. **Remove mode** unregisters and stops.

Outcome: `registered` / `re-registered` / `unregistered`.

### Terms 7 — Log + pointers

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "terms <mode> scope_id=<id>"`).

Print two pointers (no questions):
- *"A writing expert consults this dictionary through `/lazy-wiki.terms`; the curator fills it from finished documents on its own."*
- *"The corpus written before this scope existed was never seen by the routine — run the terms section of `/lazy-wiki.audit` for a full pass over it."*

Outcome: `logged`.

## Structure branch — `/lazy-wiki.configure structure`

Configures `lazy.settings.json[structure]` — the section that drives the project-structure map `docs/structure.md`. The map's path is fixed by convention and is not asked. Canonical task list for this branch (create these instead of the scope phases, titles verbatim):

- `Structure 1 — Verify install + load section`
- `Structure 2 — Collect depth_profiles`
- `Structure 3 — Collect exclude`
- `Structure 4 — Write back`
- `Structure 5 — Register the scan routines`
- `Structure 6 — Initial map + log`
- `Report`

### Structure 1 — Verify install + load section

Resolve `<repo-root>`, read `lazy.settings.json`; abort with *"Run `/lazy-wiki.install` first."* when the file is absent, or with *"Run `/lazy-wiki.install` first — the `structure` section is missing."* when it has no `structure` key. A non-empty `depth_profiles` means edit mode: persisted values shown, Enter keeps them.

Outcome: `verified`.

### Structure 2 — Collect depth_profiles

Classes are collected one at a time; after each, ask whether to add another. One context block covers the loop — print it before each iteration's first question, with Found filled from the classes collected so far:

Context (print before asking):
- Where: /lazy-wiki.configure structure · Structure 2 — Collect depth_profiles; target `lazy.settings.json[structure].depth_profiles`
- Found: classes so far `<name: globs → depth, … or none>` (edit mode: the persisted classes); overlapping globs `<pair, … or none>`
- Why asking: which trees the map describes at which depth is per-repo; nothing derives it
- Answers: class name — the key of a new `depth_profiles` entry; globs + depth — that class's `paths` and `depth`, `file` = directory line + per-file lines for load-bearing files, `dir` = directory line only, `brief` = half a line, first class by key order wins on a shared path; `keep` / `change` / `remove` (edit mode) — leave the class, re-collect it, or drop it; `yes` / `no` — collect another class or continue. Written in Structure 4; re-asked only on the next edit run.

Per class, two questions:

- AskUserQuestion: header "Class name", question "Name of the next depth-profile class for the structure map (a short label, e.g. `code`, `specs`, `tests`; taken: `<names>`)?"; free text — must be unique within the section; re-ask on a duplicate.
- AskUserQuestion: header "Class globs + depth", question "Glob(s) for class `<name>`, comma-separated (e.g. `src/**, cli/**`), and its depth — `file` (directory line + per-file lines for load-bearing files), `dir` (directory line only), or `brief` (half a line)?", options `file` / `dir` / `brief` with those descriptions, globs as free text — at least one glob; depth must be one of the three.

Then AskUserQuestion: header "Another class", question "Add another depth-profile class to `structure.depth_profiles` (so far: `<names>`)?", options `yes` / `no`.

**Warn on overlap** between two classes' globs — the first class by key order wins on a shared path, and that precedence should be chosen, not discovered. Warn only; overlap is legal.

Edit mode offers each existing class before offering to add new ones — AskUserQuestion: header "Class `<name>`", question "Keep, change, or remove structure class `<name>` (`<globs>` → `<depth>`)?", options `keep` / `change` / `remove`.

Outcome: `collected`.

### Structure 3 — Collect exclude

Context (print before asking):
- Where: Structure 3 — Collect exclude; target `lazy.settings.json[structure].exclude`
- Found: current `exclude`: `<current exclude joined>` (`docs/structure.md` seeded by install)
- Why asking: which trees the map must not describe is per-repo
- Answers: comma-separated globs — written as `structure.exclude` in Structure 4, `docs/structure.md` kept in it whatever is typed; blank — the default entry alone; re-asked only on the next edit run
AskUserQuestion: header "Map excludes", question "Paths the structure map `docs/structure.md` must not describe — comma-separated globs, or blank to keep just the default (current: `<current exclude joined>`)?"; free text. Always ensure `docs/structure.md` itself is in the array — the one mandatory entry (without it the map describes itself and the curator's own commit wakes the scan in a loop); append it silently when missing. Gitignored trees need no entry: the git watches never see them.

Outcome: `collected`.

### Structure 4 — Write back

Set `lazy.settings.json[structure]` to the collected `depth_profiles` and `exclude`, preserving `_version` and every other key; write with `Write`.

Outcome: `written`.

### Structure 5 — Register the scan routines

Three git routines, one per event class, because one `watch` covers one status set: `new_files` passes only `A`, `deleted_files` only `D`, and a rename under git's default `diff.renames=true` arrives as `R`, which both of those drop — without the third routine a directory rename silently stales the map. (With `diff.renames=false` a rename decomposes into `D`+`A` and lands in the first two — the mechanism degrades to a correct result, not to a breakage.)

The scan routine deliberately does NOT watch modifications (`changed_files` = `A`+`M`): the map describes the tree's shape — what exists where — and a content edit never changes that, so every `M` dispatch cost one expert job with nothing to apply, and a busy commit wave queued them by the dozen. The price is that a per-file description at `file` depth goes stale when its file is rewritten in place; that drift is `report`'s to find (`/lazy-wiki.audit`, the `divergence` finding) and `/lazy-wiki.structure rebuild`'s to repair.

Resolve the watched branch with `Bash(git rev-parse --abbrev-ref HEAD)`. Register each through the registrar:

```
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan type=git watch=new_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=curate request.path={path} request.status={status} timeout_sec=900")
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan-deletes type=git watch=deleted_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=curate request.path={path} request.status={status} timeout_sec=900")
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=lazy-wiki.structure-scan-renames type=git watch=renamed_files branch=<branch> interval_sec=60 filter.frontmatter.review_active.not_in=[true] expert=wiki.structure-curator protocols=lazycortex-wiki:lazy-wiki.structure-protocol request.kind=rename request.old_path={old_path} request.new_path={new_path} timeout_sec=900")
```

The rename routine carries a **different** `request` because `renamed_files` exposes different placeholders — `{old_path}` / `{new_path}`, not `{path}` / `{status}`; a shared template would `KeyError` on substitution and fail the tick on every rename. `path_filter` is omitted deliberately — the routines watch the whole tracked tree; the fine-grained cut is `exclude`, applied by the curator. The `review_active` filter keeps documents under an open review out of the map until the review closes and the file changes one last time; files without frontmatter pass it (`not_in [true]` holds for an absent key).

Edit mode: a routine already registered is left as is (`already-present`); when the section was reconfigured in a way the routines do not carry (they have no `path_filter`), nothing needs re-registering.

Outcome: `registered` / `already-present`.

### Structure 6 — Initial map + log

**Build the initial map when it is missing.** The routines registered in Structure 5 only keep an existing map current — the curator refuses to create one, so a repo that leaves this section without `docs/structure.md` has every incremental dispatch fail with a `logical` error until someone remembers the rebuild. `Bash(test -f docs/structure.md && echo present || echo absent)`; on `absent`, invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.structure", args: "rebuild")` now — never defer it to a printed pointer. Outcome: `map-present` / `map-built`.

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "structure"`).

Print one pointer (no questions):
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

Context (print before asking):
- Where: /lazy-wiki.configure vault · Vault 2 — Collect tag_axes; target `lazy.settings.json[wiki].tag_axes`
- Found: current `tag_axes`: `<current tag_axes joined or "none">`; scopes narrowing to each: `<axis: ids, … or none>`
- Why asking: the closed classification vocabulary is the vault's editorial choice
- Answers: comma-separated slugs — replaces `wiki.tag_axes` in Vault 4 (`doc-kind` kept whatever is typed), every scope without a narrowing speaks the new set at once; Enter — kept; removing an axis triggers the confirmation below; re-asked on every vault run
AskUserQuestion: header "Vault tag axes", question "Tag axes — the closed vocabulary of classification dimensions for the whole vault (current: `<current tag_axes joined or "none">`; comma-separated, Enter to keep)?"; free text.

Split on commas, trim, discard empties, lowercase-normalise each slug. Keep `doc-kind`: it is the mandatory axis `/lazy-wiki.install` unions in, and dropping it here is undone by the next install run. Before writing a set that removes any other axis, name what it costs — every `wiki/<axis>/…` tag already carried by a node on that axis becomes unknown (the audit's `unknown-axis` finding), and every scope narrowing to it silently loses it — then ask whether to proceed.

Context (print before asking):
- Where: Vault 2 — Collect tag_axes; target `wiki.tag_axes`
- Found: axes to be removed `<axes>`; nodes carrying tags on them `<n>`; scopes narrowing to them `<ids or none>`
- Why asking: the write orphans existing classification — destructive, not derivable
- Answers: `proceed` — the reduced list is written in Vault 4, those tags surface as `unknown-axis` findings and the narrowing scopes lose the axis; `cancel` — the current list stays, nothing written; not persisted
AskUserQuestion: header "Remove axes", question "Write `wiki.tag_axes` without `<axes>`, orphaning `<n>` tagged nodes and the narrowing of scopes `<ids>`?", options `proceed` / `cancel` with the descriptions above.

An axis added here becomes available to every scope at once; nothing else has to be edited for a scope to use it, since a scope that declares no narrowing speaks the full vocabulary.

Outcome: `collected`.

### Vault 3 — Collect exclude

Context (print before asking):
- Where: Vault 3 — Collect exclude; target `lazy.settings.json[wiki].exclude`
- Found: current `exclude`: `<current exclude joined or "none">`
- Why asking: which files every scope must leave alone is project config
- Answers: comma-separated globs — replaces `wiki.exclude` in Vault 4 and is unioned into every scope's exclusions (`docs/structure.md` kept whatever is typed); blank — cleared down to that mandatory entry; Enter — kept; re-asked on every vault run
AskUserQuestion: header "Vault excludes", question "Exclude glob(s) no wiki scope may opt out of (current: `<current exclude joined or "none">`; comma-separated, blank to clear, Enter to keep)?"; free text.

Split on commas, trim, discard empties. Keep `docs/structure.md` — the project-structure map is a generated document with no frontmatter to defend itself, and without the entry the curator appends a `# See also` block to it. Do not add the `wiki.domains.output` tree: it is excluded structurally from the setting itself, and an entry here would go stale the moment the output directory moves.

Outcome: `collected`.

### Vault 4 — Write back + log

Set `lazy.settings.json[wiki].tag_axes` and `lazy.settings.json[wiki].exclude` to the collected arrays, preserving `scopes`, `domains`, `_version`, and every other key; write with `Write`.

Log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` per the Phase 8 recipe (`input: "vault"`).

Outcome: `written` and `logged`.

## Report

One line per task in the canonical list of the branch that ran, with its outcome word. Scope-branch summary line: `scope <id> <created|updated>: paths=<count>, tag_axes=[<axes>], topics_index=<path>, review-skip=<on|off>, folder_note=<value held in the filter>`. Domains-branch summary line: `wiki.domains <created|updated>: code=<count>, dictionary=<path>, output=<path>, language=<language>`. Mirror-branch summary line: `scope <id> mirror <created|updated>: url=<url>, source_paths=<count>, exclude=<count>, mirror_path=<path>`. Terms-branch summary line: `terms scope <id> <created|updated|removed>: paths=<count>, file=<path>, source_exclude=<count>, routine=<registered|re-registered|unregistered>`. Structure-branch summary line: `structure <created|updated>: classes=<count>, exclude=<count>, routines=<registered|already-present>`. Vault-branch summary line: `wiki vault updated: tag_axes=[<axes>], exclude=<count>`.

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
