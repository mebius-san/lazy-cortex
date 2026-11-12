---
name: lazy-wiki.relink
description: "Use when a wiki scope's nodes need classifying and See-also linking right now — this checkout runs no runtime daemon, or the operator wants to force a relink instead of waiting for the `lazy-wiki.scan` / `lazy-wiki.relink-weekly` routines."
allowed-tools: Read, Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(date -u *), Bash(git rev-parse *), Bash(mktemp), Bash(mktemp *), Bash(rm -f *), Bash(mkdir -p *), Bash(rm -rf *), Bash(test *), Bash(cp *), Write, Agent, AskUserQuestion
---
# lazy-wiki.relink

Relink one wiki scope without the runtime daemon — entirely in the current Claude Code session. The deterministic core (`relink-plan`, `apply-node`, `tag-apply`, `build-index`, `prune-node`, `relink-commit`) decides *what* to process and what the commit carries; this skill orchestrates by dispatching the `wiki.curator` agent — and, for the tag-canon step, the `wiki.tag-curator` agent — as synchronous subagents in **tail-off mode** (`tail: false`). There are **no job dirs** — the curator reads the real node (and the real `topics.md` for link) named in its dispatch prompt and **applies its own curation via `apply-node`** (C-hybrid, exactly as on the daemon — there is no collector); it just skips the *tail* (`build-index` / git-commit / `dispatch-link`), which this skill owns: the skill rebuilds the index once between phases and makes the single commit. Every writer of the run — each curator's `apply-node`, each tag curator's `tag-apply`, every `build-index` and `prune-node` — appends the paths it wrote to one touch ledger outside the repository, and that ledger, not the working tree's status, is what the commit carries. The daemon path (event-driven `lazy-wiki.scan` + weekly `lazy-wiki.relink-weekly`) is unaffected and runs in parallel as the autonomous alternative (it, not this skill, uses the runtime's job dirs, and there the curator runs its full tail with `tail: true`).

Invocation: `/lazy-wiki.relink [<scope-id>]`. When `<scope-id>` is omitted, ask the operator which configured scope to relink.

Prerequisites: `/lazy-wiki.install` has run, at least one scope is configured in `.claude/lazy.settings.json[wiki.scopes]`, and the `wiki.curator` and `wiki.tag-curator` experts are composed. The working tree should be clean for the touched paths — this skill writes and commits node files and `topics.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve scope + compute plan`
   - `Step 2 — Classify each node`
   - `Step 3 — Normalize tags + rebuild topics index`
   - `Step 4 — Link each node`
   - `Step 5 — Prune dropped nodes`
   - `Step 6 — Commit touched files + record anchor`
   - `Step 7 — Clean up scratch`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`empty-set`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug.

## Step 1 — Resolve scope + compute plan

If no `<scope-id>` was passed, list the configured scopes (`Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" resolve-scope . --repo <repo-root>)` is per-path, not a lister — instead read `.claude/lazy.settings.json[wiki.scopes]` keys) and ask the operator which to relink.

Context (print before asking):
- Where: /lazy-wiki.relink · Step 1 — Resolve scope + compute plan; target `.claude/lazy.settings.json[wiki.scopes]`
- Found: the invocation carried no scope id; configured scopes `<id: paths, …>`
- Why asking: which scope to relink is the operator's; each scope is its own plan and its own commit
- Answers: one option per scope id — that scope's plan is computed, its nodes classified, linked, and committed under the operator identity; not persisted, asked whenever the id is omitted
AskUserQuestion: header "Relink scope", question "Which configured wiki scope should be relinked now (`<ids>`)?", options one per scope id (description: its `paths`).

Compute `<repo-root>` via `Bash(git rev-parse --show-toplevel)`.

Resolve the language the dispatched curators write in, once, here: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" resolve-language --repo <repo-root>)`. Carry the returned code into every curator and tag-curator dispatch prompt below as `language=<code>` — a dispatched subagent cannot read the settings for itself.

Run the plan:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" relink-plan <scope-id> --repo <repo-root>)
```

Parse the JSON `{mode, synced_sha, classify[], link[], drop[]}`. The three modes — `initial` (no anchor → all nodes), `incremental` (delta from `wiki_synced_sha`..HEAD), `anchor-lost` (content-hash backstop) — are all returned uniformly: process the path sets as given. Note the mode for the report.

Create the touch ledger — the run's one scratch file, outside the repository: `Bash(mktemp)`, and hold the printed path as `<ledger>`. Carry it into every curator and tag-curator dispatch prompt below as `ledger=<ledger>`, and pass `--ledger <ledger>` to every `build-index` and `prune-node` call. No job dirs are created; each dispatched curator manages (and removes) its own `mktemp` curation file inside its run, and nothing relink-related is ever written inside the repo.

If `classify`, `link`, and `drop` are all empty, the scope is already in sync — report `empty-set` and skip Steps 2–5 (still run Step 6 to refresh the anchor and Step 7/Log).

Outcome: `planned:<mode>`.

## Step 2 — Classify each node

Resolve the scope's **effective** axis list once from `.claude/lazy.settings.json`: the repository vocabulary `wiki.tag_axes`, narrowed to the entries the scope's own `wiki.scopes[<scope-id>].tag_axes` names. That key is a narrowing, not a vocabulary — absent or empty means the scope uses the full `wiki.tag_axes`, and an entry outside it is not an axis and is dropped. Pass the resolved list inline; the curator receives a closed set either way. Then capture the existing tag values as the classify **anchor**: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" collect-tags <scope-id> --repo <repo-root>)` — capture its JSON (empty `axes` on cold-start, when nothing is classified yet).

For each absolute node path in `classify[]`, dispatch the curator synchronously — **no job dir**; it reads the real node in place AND applies its own curation via `apply-node` (the skill does NOT apply — the curator owns its write, C-hybrid):

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.curator",
      prompt: "kind=classify, tail=false. node_path=<abs-node-path>, scope_id=<scope-id>, repo_root=<repo-root>, language=<code>, ledger=<ledger>, tag_axes=<comma-separated effective axes>, existing_tags=<the collect-tags JSON from above>. Read the real node at node_path (and its own pin fields); choose wiki_summary, topics, connectors — anchor topic values to existing_tags (reuse a fitting existing value instead of coining a synonym); apply them to the node yourself via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" apply-node <node_path> --from <a mktemp curation file you create> --ledger <ledger>` (this writes wiki_summary, the wiki/* tags, wiki_connectors, and the wiki_src_hash backstop, and records the node in the ledger), then rm the temp; STOP — do NOT build-index, git, or dispatch-link. Report the outcome.")
```

The curator writes the node via `apply-node`; the skill runs no `apply-node`. If a curator reports an error, skip that node and continue; the ledger already holds every node that was written. Outcome: `classified:<n>` (or `empty-set` when `classify[]` was empty).

## Step 3 — Normalize tags + rebuild topics index

After all classify-applies, first **consolidate the tag vocabulary** (so a cold-start run's free-form values collapse to a canon), then rebuild `topics.md` once before any link.

The canon is judged per **tag surface**: every configured `wiki.scopes` entry (read the keys from `.claude/lazy.settings.json`), plus the reserved `domains` surface — the generated domain-doc tree — when `wiki.domains` is configured, for `len(scopes)+1` surfaces in that case. A relink is the run that settles the vault's vocabulary, so every surface is passed over, not only the scope being relinked; each surface is judged on its own, because two surfaces may legitimately spell the same idea differently.

1. **Collect + normalize, one surface at a time.** For each surface id:

   a. Capture that surface's value census: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" collect-tags <surface> --repo <repo-root>)`. An empty `axes` object means nothing is tagged there — skip the surface, dispatch nothing.

   b. Dispatch the tag curator to judge a canonical set — **no job dir**; it self-applies via `tag-apply`, which retags the surface and rewrites the advisory dictionary (the skill does neither):

   ```
   Agent(subagent_type: "lazycortex-wiki:lazy-wiki.tag-curator",
         prompt: "kind=normalize-tags, tail=false. surface=<surface>, repo_root=<repo-root>, language=<code>, ledger=<ledger>, collected_tags=<the collect-tags JSON from step a>, tag_dictionary=<the `wiki.tags.dictionary` path from .claude/lazy.settings.json, or docs/tags.md when unset>. Judge a canonical axis-value set; build the alias map ({axis:{old-value:new-value}} — merge a synonym, nest a subtype, or keep) and gloss every value the dictionary does not yet record; write both to mktemp files you create and apply them via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" tag-apply <surface> --from <alias-map file> --glosses <glosses file> --ledger <ledger> --repo <repo-root>`, then rm both temps; STOP — do NOT build-index or git. Report the alias map and outcome.")
   ```

   The tag curator runs `tag-apply`; the skill does not. The verb records every node it retagged and the dictionary it wrote in the ledger, so the Step 6 commit carries them without the skill collecting anything.

2. **Rebuild the indexes.** `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" build-index <scope-id> --repo <repo-root> --ledger <ledger>)` for the relinked scope — once, after normalize, before Step 4. The link phase reads this freshly-populated, canonicalised catalog. Run it again for every **other** scope surface whose canon pass reported a non-empty alias map, so a scope this run retagged is not left with a stale catalog. The `domains` surface has no topics index — never call `build-index` for it. Every `build-index` call carries `--ledger <ledger>`, so each rebuilt `topics.md` reaches the Step 6 commit.

Outcome: `normalized:<n> index-rebuilt` (or `skipped-per-user-choice` only when the plan was `empty-set`).

## Step 4 — Link each node

For each absolute node path in `link[]`:

1. Compute the recall shortlist: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" find-candidates <abs-node-path> --scope <scope-id> --repo <repo-root>)` — capture its JSON-array stdout (a ranked top-N of repo-relative candidate paths; deterministic content overlap, pins honored; `[]` when nothing overlaps → the curator falls back to `topics.md` judgment).
2. Dispatch the curator synchronously — **no job dir**; it reads the real node + the real `topics.md` AND applies its own curation via `apply-node` (the skill does NOT apply):

   ```
   Agent(subagent_type: "lazycortex-wiki:lazy-wiki.curator",
         prompt: "kind=link, tail=false. node_path=<abs-node-path>, scope_id=<scope-id>, repo_root=<repo-root>, language=<code>, ledger=<ledger>, topics_path=<repo-root>/<topics_index>, candidates=<the JSON array from step 1>. Read the real node (it now carries the classify writes) and the real topics.md (and the node's own pin fields); verify the candidates first (empty → judge from topics.md); build see_also; apply it to the node yourself via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" apply-node <node_path> --from <a mktemp curation file you create> --ledger <ledger>` (this grafts only the # See also section), then rm the temp; STOP — do NOT git. Report the outcome.")
   ```

The curator writes the node via `apply-node`; the skill runs no `apply-node`. If a curator reports an error, skip that node and continue; the ledger already holds every node that was written. Outcome: `linked:<n>` (or `empty-set` when `link[]` was empty).

## Step 5 — Prune dropped nodes

For each path in `drop[]`: the node was deleted since the anchor. The Step 3 index rebuild already excludes it from `topics.md` (it no longer exists on disk, so `find_all_nodes` skips it), but other nodes may still carry See-also links pointing at it. Drop those dangling lines deterministically:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" prune-node <dropped-path> --repo <repo-root> --no-commit --ledger <ledger>)
```

Run once per dropped path. `--no-commit` is mandatory here — the Step 6 commit owns all writes; `--ledger` records the pruned nodes and the rebuilt index for it. A `skip (no scope)` note is fine — the node resolved to no scope and nothing was touched.

Outcome: `dropped:<n> pruned:<m>` (or `empty-set` when `drop[]` was empty).

## Step 6 — Commit touched files + record anchor

Record the new anchor and commit the ledger in one call, under the operator identity (not the curator's `git_author` — the skill owns this commit):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" relink-commit <scope-id> --ledger <ledger> --mode <mode> --classify <N> --link <M> --drop <K> --repo <repo-root>)
```

The verb anchors `wiki_synced_sha` at the `HEAD` the pass ran against and commits exactly the ledger plus the scope's index — never a path someone else left in the working tree or the index. Parse its one-line JSON `{status, anchor, paths, unledgered}`. A non-empty `unledgered` names wiki files changed outside this run; list them in the report — they are not this run's to commit. Do NOT invoke any project-level pre-commit pipeline — these are scope/data files, not plugin source.

Outcome: `committed` / `unchanged` — the verb's `status`.

## Step 7 — Clean up scratch

Delete the touch ledger: `Bash(rm -f <ledger>)`. It lives outside the repository, so nothing inside the worktree is touched. Each curator has already removed its own `mktemp` curation file. Outcome: `cleaned`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/lazy-wiki.relink` reports "unknown scope '<id>'"** — the scope id is not in `lazy.settings.json[wiki.scopes]` → run `/lazy-wiki.configure` to create it, or re-invoke with a known id.
- **`relink-plan` returns `anchor-lost` unexpectedly** — the `wiki_synced_sha` commit became unreachable (rebase, `reset --hard`, squash, gc, shallow clone) → the plan falls back to a content-hash backstop over `wiki_src_hash`; this is expected recovery, not an error. `relink-commit` anchors the new pass at Step 6 like any other.
- **A curator subagent reports an error** — malformed input, a refused `apply-node` / `tag-apply`, or a curator-side schema violation → in tail:false the curator reports it in its reply (there is no job dir and no `response.json`); surface the message, skip that node, and continue with the rest; the node is picked up on the next relink.
- **Step 6 reports `unchanged`** — `relink-commit` found nothing to commit → no empty commit is created.
- **The report lists `unledgered` paths** — wiki files changed in the working tree that no writer of this run recorded (an operator edit, another session) → they are left out of the commit on purpose; commit or discard them yourself.
