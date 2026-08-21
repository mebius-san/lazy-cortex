---
name: lazy-wiki.structure
description: "Use when an agent doing research (an architect deciding where a new file belongs, any expert asking 'where does X live in this repo') needs the project's structure map, or when the operator asks to resync `docs/structure.md` with the tree after files moved. Two modes: `rebuild` walks the tracked tree and rewrites the map; `query [<path>]` returns just the slice under `<path>` — the whole file is never loaded into the caller's context."
research: true
allowed-tools: Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, Bash(git ls-files *), Bash(git add -N *), Bash(git commit *), Bash(git rev-parse *), Bash(test -f *), Bash(mkdir -p *), Bash(date -u *), TaskCreate, TaskUpdate, TaskList
---
# lazy-wiki.structure

One file per repository, `docs/structure.md` — a compact map of what lives where and where new work belongs, written for a model to read, not for a human to browse. Incremental upkeep belongs to the `lazy-wiki.structure-scan*` routines dispatching the `lazy-wiki.structure-curator` expert (wired by `/lazy-wiki.configure structure`); this skill's `rebuild` mode is the wholesale resync for the initial build, a map that drifted before the routines existed, or a hand edit that bypassed them. Query the map through this skill rather than reading the file directly — it can be large, and a caller only ever needs one slice of it.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Load structure config`
   - `Phase 2 — Resolve mode and target`
   - `Phase 3 — Rebuild the map`
   - `Phase 4 — Answer a query`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. The phase that does not match the resolved mode is marked `skipped` with outcome `skipped-per-mode` — not left `pending`.
3. **Do not reach the Log step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Load structure config

`Read` `.claude/lazy.settings.json` (and `.claude/lazy.settings.local.json` when present — scalars from local override tracked, arrays union). Extract the `structure` section: `depth_profiles` (map of class name → `{paths: [<glob>, ...], depth: "file"|"dir"|"brief"}`) and `exclude` (array of glob strings never described).

If the `structure` key is absent entirely, abort: *"No `structure` section — run `/lazy-wiki.install` first."* An absent or empty `depth_profiles` is valid, not an error: every tracked path defaults to `dir` depth (directory line only, no per-file entries) until `/lazy-wiki.configure structure` populates the classes.

Outcome: `loaded` or `no-section`.

## Phase 2 — Resolve mode and target

Parse the invocation: `/lazy-wiki.structure rebuild` or `/lazy-wiki.structure query [<path>]`. `<path>` is a repo-relative directory (or file) path; omitted means "top-level only" — the root-level bullets of the map, not the whole tree.

Neither keyword given → `AskUserQuestion`: *"Rebuild the structure map from the tree, or query a slice of it?"* with options `rebuild` / `query`; if `query`, follow up asking for the path (blank allowed).

Outcome: `resolved: <rebuild|query>`.

## Phase 3 — Rebuild the map

**mode=rebuild only.** If the resolved mode is `query`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Phase 4.

1. Enumerate the tracked tree: `Bash(git ls-files)`. Drop every path matching a glob in `exclude` (this always includes `docs/structure.md` itself — describing the map inside the map is meaningless).
2. Classify each remaining directory by the first `depth_profiles` entry (in key order) whose `paths` glob matches a file under it; a directory matching NONE of them is **unclassified** — a distinct third case, not the same as a directory explicitly classified into a `dir`-depth profile (step 3 below). A directory matching two classes takes the first by key order — a genuine overlap belongs in the operator's `depth_profiles`, not something this skill resolves.
3. Describe by depth:
   - **`file`** — one line for the directory (`- <path>/ — <one-line role>`) plus one nested line per **load-bearing** file underneath (entry point, registry, contract, a config whose semantics aren't obvious from its name) — judge "load-bearing" yourself, do not enumerate every file.
   - **`dir`** — one line for the directory, one to two sentences, no per-file lines.
   - **unclassified (no `depth_profiles` entry matched)** — the directory line itself renders exactly like `dir` (one line, one to two sentences), but individual FILES underneath still get a per-file line by the SAME load-bearing judgment `file` depth uses — an unclassified directory is not exempt from surfacing its own entry points and registries just because nobody assigned it a class.
   - **`brief`** — one line for the directory, half a sentence (e.g. `tests for `<module>``), nothing else.
   Source the description from what the content already says — a module docstring, a `description:` frontmatter key, a file header, a directory's own README — before writing anything from scratch.
4. **Fan-out on a large tree.** When more than roughly 12 top-level tracked directories exist, split them into batches of at most 4 and dispatch one `Agent(subagent_type: "Explore", mode: "dontAsk", ...)` per directory in a batch, in a single message per batch (never more than 4 concurrent dispatches — `lazy-core.skill-writing § 5`). Each agent reads only its assigned subtree and the relevant `depth_profiles` entry, and returns the markdown lines for it per step 3's shape — nothing else enters this session's context. Splice the returned blocks together, sorted by path. A small tree (≤ 12 top-level directories) is walked directly, no fan-out.
5. Assemble the lines into one nested markdown list — indentation mirrors directory nesting — and `Write` it to `docs/structure.md`. No frontmatter, no generated-index preamble: the file is markdown, self-explanatory, nothing else.
6. Commit: if `docs/structure.md` did not exist before this run, `Bash(git add -N docs/structure.md)` first (new-file registration, per `lazy-core.git` — never a plain `git add`); then `Bash(git commit -m "docs(structure): rebuild project structure map" -- docs/structure.md)`.

Outcome: `rebuilt: <directory-count> directories` or `skipped-per-mode`.

## Phase 4 — Answer a query

**mode=query only.** If the resolved mode is `rebuild`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Logging.

`Bash(test -f docs/structure.md)` — absent → answer *"No structure map yet — run `/lazy-wiki.structure rebuild` first."* and stop here (outcome `no-map`).

Empty `<path>` (top-level query) → `Read` only the first, unindented level of bullets — the directories directly under the repo root — and return that list. Never read the whole file.

Non-empty `<path>` → escape it for `Grep` (`[ ] ( ) { } * + ? | ^ $ \ .` each need a backslash before substitution — `Grep` has no fixed-string mode) and locate the bullet whose path matches. `Grep` for that line plus every following line indented deeper than it (`-A`, stop at the first line back at the same or shallower indentation — the block belongs to that directory and everything nested under it). No match → *"`<path>` is not in the map — it may be new, excluded, or the map is stale; run `/lazy-wiki.structure rebuild`."*, not an error.

Return only the matched slice to the caller. Never paste the full `docs/structure.md` into the response or into this session's context.

Outcome: `answered: <path-or-top-level>` or `no-match` or `no-map`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.structure/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.structure)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.structure/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<mode> <path-or-blank>"
---
# lazy-wiki.structure

## Actions
- <one line per Phase/step above with its outcome word>

## Result
<success/failure + one-sentence summary>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **Aborts: "No `structure` section"** — `lazy.settings.json` has no `structure` key → run `/lazy-wiki.install`, then re-run.
- **Query reports "No structure map yet"** — `docs/structure.md` was never built → run `/lazy-wiki.structure rebuild`.
- **Query reports "`<path>` is not in the map"** — the path is new, `exclude`d, or the map predates it → run `/lazy-wiki.structure rebuild` to resync, or check `exclude` in `lazy.settings.json[structure]`.
