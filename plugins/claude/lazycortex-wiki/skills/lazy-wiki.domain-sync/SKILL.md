---
name: lazy-wiki.domain-sync
description: "Use when the domain-spec tree needs regenerating right now — this checkout runs no runtime daemon, domain markers or the dictionary just changed and the operator wants the docs current, or a `/lazy-python.knowledge-sweep` backfill has landed. Computes the domain plan, dispatches the domain-spec writer synchronously per changed group and lands every returned file — the group's folder note and the docs of its changed blocks — through `domain-land`, removes orphaned docs, repairs moved anchors and dead Related links, rebuilds `domains.md`, and makes one commit under the operator identity. An optional group key limits the run to that group."
allowed-tools: Read, Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(date -u *), Bash(git *), Bash(mkdir -p *), Bash(rm *), Write, Agent
---
# lazy-wiki.domain-sync

Regenerate the domain-spec tree without the runtime daemon — entirely in the current Claude Code session. The deterministic core (`domain-plan`, `domain-apply-index`) decides *what* changed; this skill orchestrates by dispatching the `lazy-wiki.domain-spec-writer` agent as a synchronous subagent in **tail-off mode** (`tail: false`) per changed group. There are **no job dirs** — each writer reads its group's payload from a file `domain-payload` writes, writes the group's folder note and the docs of its changed blocks into a scratch directory under `.runtime/`, and stops; this skill lands each returned file through `domain-land` (the same landing primitive the daemon's `domain-collect` uses) and owns orphan removal, the mechanical repairs, the single index rebuild, and the single commit. The tree holds one folder per dictionary group, opened by a folder note named like the folder, with one document per `Domain(…)` block inside. The daemon path (`lazy-wiki.domain-scan` git routine + `lazy-wiki.domain-full` weekly schedule dispatching jobs, `lazy-wiki.domain-collect` landing them) runs the same detect through `domain-tick`.

Invocation: `/lazy-wiki.domain-sync [<group-key>]` — with a group key, only that group's folder is written and cleaned; the index is still rebuilt from the whole tree.

Prerequisites: `/lazy-wiki.install` has run and `wiki.domains` is configured in `.claude/lazy.settings.json` (via `/lazy-wiki.configure domains`). The working tree should be clean for the output paths — this skill writes and commits doc files and `domains.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Compute the domain plan`
   - `Step 2 — Write each changed group`
   - `Step 3 — Remove orphaned docs`
   - `Step 4 — Repair anchors and links`
   - `Step 5 — Rebuild the index`
   - `Step 6 — Commit touched files`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`empty-set`, `unchanged`, …).
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug.

## Step 1 — Compute the domain plan

Compute `<repo-root>` via `Bash(git rev-parse --show-toplevel)`, then run — with `--group <group-key>` appended when the invocation named one:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" domain-plan --repo <repo-root>)
```

A non-zero exit means `wiki.domains` is not configured — surface the message, point at `/lazy-wiki.configure domains`, and stop.

Parse the JSON. The fields this skill acts on: `changed_groups` (each entry: `group`, `folder_note_path`, `docs` — every document of the group with its `slug` and `doc_path` — and `stale_docs`, the slugs whose document must be rewritten), `orphaned_docs` with `orphan_reasons`, `unlisted_docs`, `anchor_fixes`, `link_fixes`, `contract_drops`, `unknown_groups`, `untitled_blocks`, `index_needs_update`. Report any `unknown_groups` verbatim (groups used in code but absent from the dictionary — this run never generates them) and any `untitled_blocks` (blocks whose first body line is not a `# # <title>` line, so they have no document; name each by `path:line`).

`unlisted_docs` is the subset of `orphaned_docs` whose group the dictionary no longer lists. Carry it to the Report step and name every path there, so a deletion the operator did not intend is visible in the same run that made it. `orphan_reasons` gives each orphan's cause: `no-blocks`, `group-unlisted`, `block-gone` (its block was removed or retitled), `legacy-layout` (the one-document-per-group file the previous layout left beside the group folder).

If `changed_groups`, `orphaned_docs`, `anchor_fixes`, `link_fixes` and `contract_drops` are all empty and `index_needs_update` is false, the tree is in sync — report `empty-set`, mark Steps 2–6 `skipped` with outcome `empty-set`, and go to the Report step.

Outcome: `planned: changed=<n> orphaned=<m> unknown=<k> untitled=<u>`.

## Step 2 — Write each changed group

For each entry in `changed_groups`, write its payload to the gitignored runtime area:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" domain-payload --group <group> --out <repo-root>/.runtime/lazy-wiki.domain-sync/<group>/payload.json --repo <repo-root>)
```

It prints `{"payload": <path>, "files": [<names>]}` — `files` are the file names the writer must return: the folder note's first, then every stale doc's. Create the writer's output directory with `Bash(mkdir -p <repo-root>/.runtime/lazy-wiki.domain-sync/<group>/out)`, then dispatch the writer synchronously — **no job dir**:

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.domain-spec-writer",
      prompt: "kind=domain-spec, tail=false. repo_root=<repo-root>, payload_path=<the printed payload path>, output_dir=<repo-root>/.runtime/lazy-wiki.domain-sync/<group>/out. Write every file named here into output_dir: <the printed files>. Never write into the working tree and never run git. Report the files written and every discrepancy between the comments and the code.")
```

Before landing anything, confirm that every name in `files` exists in the output directory and is not empty (`Bash(test -s <repo-root>/.runtime/lazy-wiki.domain-sync/<group>/out/<name>)` per name). When any is missing or empty, land none of the group's files: surface the reason, skip the group, and continue — a half-landed group would carry a folder note describing documents that were not rewritten. Then land every returned file. Each name in `files` lands at the path the plan gives it — the entry's `folder_note_path` for the first name, the matching `docs[].doc_path` for the rest:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" domain-land <path> --from <repo-root>/.runtime/lazy-wiki.domain-sync/<group>/out/<name> --payload <the printed payload path> --repo <repo-root>)
```

`domain-land` writes only a doc inside a group folder of the output tree, and stamps the doc's `domain_hash` from the payload and the explainer line under its H1; it refuses (exit 1, reason on stderr) an empty return, a return without a `domain_hash` frontmatter key or an H1, a path the payload names no digest for, or a path outside the tree, and writes nothing then. When the writer reports an error, surface it and skip the group. When a landing still refuses after the check above, surface the reason, restore every file of that group this step already landed with `Bash(git restore --worktree -- <path>)` (or `Bash(rm <path>)` for a path that did not exist before), and continue; the group is re-detected on the next run. Track every landed path for the Step 6 commit, and register each path that did not exist before with `Bash(git add -N <path>)` so the commit pathspec can see it. Carry the discrepancies each writer reported to the Report step.

Outcome: `written:<n groups>/<m files>` (or `empty-set`).

## Step 3 — Remove orphaned docs

For each path in `orphaned_docs`, the doc is deleted — the tree is a derivative of the code and the dictionary:

```
Bash(rm <repo-root>/<orphaned-doc-path>)
```

Plain `rm`, never `git rm` (auto-stages, violating the pathspec discipline). When a deletion leaves its group folder empty, remove the folder with `Bash(rm -d <repo-root>/<folder>)`. Track each removed path for the Step 6 commit.

Outcome: `dropped:<n>` (or `empty-set`); when `unlisted_docs` is non-empty, append `unlisted:<m>`.

## Step 4 — Repair anchors and links

After the landings and removals, repair what needs no writer: contract anchors whose file moved, `## Related` lines whose target no longer exists, and `## Contracts` bullets citing a guarantee no attributed contract accounts for:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" domain-repair --repo <repo-root>)
```

It prints `{"docs": [<paths>]}`; track each for the Step 6 commit.

Outcome: `repaired:<n>` (or `unchanged`).

## Step 5 — Rebuild the index

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" domain-apply-index --repo <repo-root>)
```

Parse `{index, updated, sections}`; track the index path for the commit when `updated` is true, and every path in `sections`. The index lists every group whose folder note exists and, under `## Discrepancies`, every doc a writer tagged `domains/discrepancy`. `sections` names the notes the engine wrote for folders above the groups that are not groups themselves (`pytool/pytool.md` above `pytool.code-discipline`), each listing the groups and sections directly inside it.

Outcome: `index-updated` or `index-unchanged`.

## Step 6 — Commit touched files

Commit everything in one atomic step under the operator identity (not a bot `git_author` — the skill owns this commit), naming every touched path in the pathspec:

```
Bash(git commit -m "wiki(domains): sync (write N / drop M)" -- <landed-1> … <orphan-1> … <repaired-1> … <index-path>)
```

No `git add` — the pathspec carries the worktree content straight into the commit, which is what `lazy-core.git`'s pathspec discipline requires and what leaves the operator's index alone (new files were registered with `git add -N` in Step 2). Do NOT invoke any project-level pre-commit pipeline — these are generated data files, not plugin source. If nothing changed (idempotent re-run produced no byte change), report `unchanged` and do not create an empty commit.

Outcome: `committed` / `unchanged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. Append the `unknown_groups` list and the `untitled_blocks` list (when non-empty) so the operator can fix the code or the dictionary, the `unlisted_docs` list (when non-empty) naming every doc deleted because its group left the dictionary, and every discrepancy the writers reported, each as comment claim, code behaviour, and anchor.

## Failure modes

- **`domain-plan` exits non-zero saying wiki.domains is not configured** — the `wiki.domains` section is missing from `lazy.settings.json` → run `/lazy-wiki.configure domains`, then re-run.
- **A writer subagent reports an error or returns too few files** — unreadable source file or malformed payload → the group is skipped this run and re-detected on the next; surface the message and continue.
- **`domain-land` refuses a returned file** — the writer left it empty or without a `domain_hash` frontmatter key or an H1, or the plan's path is not inside a group folder of the output tree → nothing is written for that file; surface the stderr reason, continue, and re-run to regenerate it.
- **Groups reported under `unknown_groups`** — code carries `Domain(<group>)` blocks whose group is not in the dictionary → add the group to the dictionary by hand and re-run, or run `/lazy-python.knowledge-sweep`, which grows the dictionary with the operator and refiles the blocks; `/lazy-wiki.audit` flags the same condition.
- **Blocks reported under `untitled_blocks`** — a `Domain(…)` block does not open with a `# # <title>` line, so it has no document → add the title line to the block in the code and re-run.
- **Docs deleted under `unlisted_docs`** — a group was renamed or removed in the dictionary → restore the group key and re-run to bring the docs back, or accept the removal and let `/lazy-python.knowledge-sweep` refile the code's blocks under the new name.
- **The commit at Step 6 stages nothing** — an idempotent re-run produced no byte change → reported as `unchanged`; no empty commit is created.
