---
name: lazy-wiki.audit
description: "Run when the operator asks to check the wiki's health, or when the wiki misbehaves — `/lazy-wiki.query` misses material it should cover or returns entries that no longer exist, See-also links point at moved or deleted nodes, the topic index disagrees with the files on disk, or documents and the terms dictionary have drifted onto different words for one concept. Read-only audit of one scope or all: it reports findings as `FAIL` / `WARN` / `INFO` with a repair route per finding and writes nothing itself, so the repairs are the operator's to run."
allowed-tools: Read, Write, Grep, Glob, Bash(lazycortex-wiki doctor *), Bash(date -u *), Bash(git rev-parse *), Bash(mkdir -p *), Agent
---
# lazy-wiki.audit

Run the integrity audit over one wiki scope (or every configured scope) and present the findings grouped by severity. **The audit never repairs anything.** Findings the `lazycortex-wiki doctor --apply` CLI can repair (rebuild the topic index — orphan-topic, index-desync; rewrite See-also targets written against a non-canonical path base — see-also-path-base; drop broken See-also lines — broken-see-also; refresh stale glosses — stale-gloss) are labelled `(fixable)` and the report names that command as their route; the scheduled `lazy-wiki.doctor-apply` routine runs the same command with `--commit`. All other findings carry a per-finding repair route naming the skill or command that owns it — including the mirror checks (a scope's `mirror` block vs the mirror directory, `paths` coverage of `mirror_path`, a stale source clone, local edits a sync would erase) and the dangling-`@`-prefix check that catches leftover pre-mirror cross-repo links. When `wiki.domains` is configured (or a domain routine is registered without it), the audit also prints a repo-level `domains` section. When `terms.scopes` carries any scope, the run adds a `terms` section per scope: format and configuration judged here by reading, meaning findings dispatched to the terms curator in `report` mode.

Invocation: `/lazy-wiki.audit [<scope-id>]`

Prerequisites: `/lazy-wiki.install` has run and at least one scope is configured in `.claude/lazy.settings.json[wiki.scopes]`.

Fix/waive orchestration over these findings belongs to `/lazy-core.doctor`, which delegates to this audit and drives whatever loop the operator wants; this skill only measures.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Run the audit`
   - `Phase 2 — Audit the terms scopes + the structure map`
   - `Phase 3 — Present findings`
   - `Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`asserted`, `unchanged`, `clean`, …).
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Run the audit

Run the read-only audit — never pass `--apply`, in this phase or any other. The CLI's repair mode is the operator's to run, not this skill's.

`Bash(lazycortex-wiki doctor <scope-id>)` when the operator named a scope, or `Bash(lazycortex-wiki doctor)` to audit every configured scope.

The command prints findings grouped per scope and severity (`FAIL` / `WARN` / `INFO`), tags each fixable finding `(fixable)`, and ends with a grand-total count. It exits 0 when the audit ran; a non-zero exit means the named scope id is unknown or no scopes are configured — surface that message to the operator and stop (do not proceed to later phases).

Outcome: `audited`.

## Phase 2 — Audit the terms scopes + the structure map

The terms dictionary has no CLI of its own — this phase is the whole check. `Read` `.claude/lazy.settings.json` (and `.claude/lazy.settings.local.json` when present, merged the runtime's way: local scalars replace tracked, arrays union). No `terms` section or an empty `scopes` map → state `no-terms-scopes` and move on; that is not a finding.

For each terms scope, run both halves. Nothing here writes.

**Format and configuration — judged here, by reading.** They are simple, but no program computes them:

- `config` — the scope's `file` names a document that does not exist; two terms scopes' `paths` globs overlap (one document must belong to one dictionary); the dictionary is missing from `exclude_paths` of a `wiki.scopes` entry whose globs cover it (the wiki curator will otherwise append a `# See also` block to a file that carries no frontmatter to defend itself); the dictionary is missing from the scope's own `source_exclude` (every term would then trivially occur in a document of the scope and the dead-term check could never fire); the scope's `lazy-wiki.terms-scan-<id>` routine is absent, or its `path_filter` no longer matches the scope's `paths`.
- `format` — a definition longer than three physical lines; sections out of sort order (heading lowercased, then code points — latin before cyrillic); a duplicated heading, counting two headings that differ only in case as the same term. Read the dictionary itself for these. Sort order over mixed alphabets is the one check here that a human eye and a model both get wrong at a glance — walk the headings in file order and compare each against its predecessor rather than judging the list as a whole.

**Meaning — dispatched, one per scope.** Send `lazy-wiki.terms-curator` in `report` mode with the `Agent` tool, naming the scope id, the dictionary path, the scope's `paths`, and its `source_exclude` in the prompt. There is no job dir on this path. It returns `divergence`, `missing`, `duplicate`, and `dead` findings and writes nothing.

**Then the structure map, same pattern.** No CLI here either. From the merged settings take the `structure` section; `depth_profiles` empty AND `docs/structure.md` absent → state `no-structure` and move on. Otherwise, two halves, nothing written:

- **Configuration — judged here.** `docs/structure.md` missing from the section's own `exclude` (the curator's commit would wake the scan in a loop); two `depth_profiles` classes' globs overlapping (first-by-key-order wins on a shared path — the precedence should be chosen, not discovered); any of the three routines `lazy-wiki.structure-scan` / `lazy-wiki.structure-scan-deletes` / `lazy-wiki.structure-scan-renames` absent, or carrying the wrong `watch` (`new_files` / `deleted_files` / `renamed_files` respectively — `changed_files` on the scan routine is the retired pre-v7 shape that queued one expert job per content edit); any of the three routines registered while `docs/structure.md` does not exist (every incremental dispatch fails `logical` until `/lazy-wiki.structure rebuild` creates the map); `docs/structure.md` missing from the repository-wide `wiki.exclude` while some wiki scope's `paths` cover it (the map has no frontmatter to defend itself, and the exclusion is the vault's, not any one scope's).
- **Map vs tree — dispatched.** Send `lazy-wiki.structure-curator` in `report` mode with the `Agent` tool, naming the map path, the `depth_profiles`, and the `exclude` in the prompt. No job dir on this path. It returns `missing-dir`, `missing-file`, `dead-entry`, `divergence`, and `depth` findings and writes nothing. Skip the dispatch when `docs/structure.md` does not exist — report that single fact instead (the fix is `/lazy-wiki.structure rebuild`).

Outcome: `terms-audited` / `no-terms-scopes` plus `structure-audited` / `no-structure`.

## Phase 3 — Present findings

Summarise the captured output for the operator: the per-scope counts by severity, and a short list of the concrete findings (check name, node path, message). Every finding carries a repair route the operator runs; this skill runs none of them.

Call out which findings the CLI repairs for you (`orphan-topic`, `index-desync`, `see-also-path-base`, `broken-see-also`, `stale-gloss` — route: `Bash(lazycortex-wiki doctor <scope-id> --apply)`, which rebuilds the index, rewrites the path-base See-also targets, drops the broken lines and refreshes the glosses, leaving the rewritten files uncommitted in the worktree; the scheduled `lazy-wiki.doctor-apply` routine runs the same command with `--commit`) versus which need a hand repair (`dangling-at-prefix`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`, the mirror checks `mirror-clone-orphaned`, `mirror-dir-missing`, `mirror-paths-uncovered`, `mirror-stale-fetch`, `mirror-local-edit`, and every check in the `domains` section: `domain-dictionary-missing`, `domain-doc-unknown`, `domain-gloss-missing`, `domain-group-unknown`, `domain-hash-stale`, `domain-output-in-scope`, `domain-routine-mismatch`, `domain-tag-axis-unknown`). For a `dangling-at-prefix` finding, name the repair route: rewrite the link to the mirrored node's local path (when a mirror scope covers the target) or drop the line. For the mirror findings: register or remove the scope's `mirror` block via `/lazy-wiki.configure mirror` (`mirror-clone-orphaned`), run `Bash(lazycortex-wiki mirror-sync <scope-id>)` by hand or wait for the `lazy-wiki.mirror-sync` routine (`mirror-dir-missing`, `mirror-stale-fetch`, `mirror-local-edit` — local edits are overwritten by that sync, so salvage them first), add `<mirror_path>/**` to the scope's `paths` (`mirror-paths-uncovered`). For the domain findings, name the repair route — two of them carry a second route the operator is more likely to want:

- `domain-group-unknown` — edit the dictionary by hand to add the group, **or** run `/lazy-python.knowledge-sweep`, which grows the dictionary with the operator and refiles the blocks under the groups it accepts. The sweep is the route whenever several groups are reported at once or the blocks are parked under `Domain(unfiled):`.
- `domain-dictionary-missing` — seed an empty skeleton via `/lazy-wiki.configure domains`, **or** run `/lazy-python.knowledge-sweep`, which builds a populated dictionary from the code's own domain vocabulary. The sweep is the route for a repo whose code already carries domain knowledge; the skeleton is for a repo starting from nothing.
- `domain-doc-unknown` — edit the dictionary (a group renamed there strands its old doc). A markdown doc under the output tree whose group the dictionary no longer lists is dropped by the next `/lazy-wiki.domain-sync` or domain routine and reported there as an unlisted removal; anything else under the tree (a non-markdown file, a hand-added directory) stays until the operator removes it.
- `domain-gloss-missing` — add the group's one-line gloss under its `## <group>` heading in the dictionary; without it the index line stays bare and the writer has only the blocks to synthesise the overview from.
- `domain-hash-stale` — run `/lazy-wiki.domain-sync` or wait for the routine.
- `domain-output-in-scope` — a wiki scope's globs reach the domain output tree, which is excluded from every scope structurally (the exclusion is derived from `wiki.domains.output`, not declared anywhere). No file is contested and no curator ever touches the tree; what the finding reports is a glob that claims more than the scope covers. Narrow the scope's `paths` via `/lazy-wiki.configure` so the coverage says what it actually is — there is nothing to exclude, and handing the tree to the wiki is not an option the settings offer.
- `domain-routine-mismatch` — re-run `/lazy-wiki.install`.
- `domain-tag-axis-unknown` — a generated domain doc carries a `wiki/<axis>/...` tag whose axis is not in `wiki.tag_axes`; the finding names the axis and the carrying doc. Either register the axis via `/lazy-wiki.configure` when the vault means to use it, or fix the writer's tagging so it stops minting one — the doc itself is regenerated, so hand-editing its tags is never the repair.

Then the terms findings from Phase 2. Which side of a finding is right is always the operator's decision, and this audit writes neither the dictionary nor the document; once they have decided a `divergence` in the dictionary's favour, one CLI verb performs that half mechanically (below), and every other repair is a hand edit. Two things are never edited whichever repair the operator picks, so say so with the finding: a document whose frontmatter has `review_active: true` (an edit from outside the job counts against the open review round) and anything under an upstream mirror tree (editing a mirror breaks the drift detection it exists for).

- `divergence` — the document and the dictionary name one concept with different words → rename in the document, or widen/rename the term; report both sides (the word the document uses, the term the dictionary carries) so the operator can pick, and never pick for them. Once they have picked the dictionary's side, `Bash(lazycortex-wiki terms-apply <document> --from "<the document's word>" --to "<the dictionary's term>")` performs that substitution — whole-word, in prose only, leaving frontmatter, code fences, inline code, link targets and the `# See also` block alone, and refusing outright on a document under an open review round or inside a mirror tree. Name the command with the finding; never run it — the direction is the operator's to give, and this audit writes nothing. The other side of the decision (rename or widen the term) stays a hand edit in the dictionary.
- `missing` — the document introduces a project entity the dictionary does not carry → add the term.
- `duplicate` — two terms describe one concept → merge them, keeping the name the corpus actually uses.
- `dead` — a term no document uses → drop it, or leave it when the concept is real and simply unwritten yet.
- `format` / `config` — repair the dictionary in place, or fix the scope through `/lazy-wiki.configure terms`; a missing or diverged routine is that wizard's job too.

And the structure findings, with per-finding routes:

- `missing-dir` / `missing-file` / `dead-entry` / `divergence` / `depth` — run `/lazy-wiki.structure rebuild` for a wholesale resync, or fix the single entry by hand in `docs/structure.md`; a lone finding rarely earns a full rebuild.
- structure `config` — fix through `/lazy-wiki.configure structure` (profiles, exclude, routines); a map left reachable by the wiki is fixed once for the whole vault by putting `docs/structure.md` back into `wiki.exclude` via `/lazy-wiki.configure vault`, not scope by scope.

If neither phase found anything, report "scope clean".

Outcome: `presented` or `clean`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.audit/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.audit)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.audit/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<scope-id or 'all scopes'>"
---
# lazy-wiki.audit

## Actions
- <bullet per step with outcome>

## Result
<success/failure + one-sentence summary of finding counts by severity>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/lazy-wiki.audit` reports "unknown scope '<id>'"** — the scope id is not in `lazy.settings.json[wiki.scopes]` → run `/lazy-wiki.configure` to create it, or re-invoke with a known id.
- **`/lazy-wiki.audit` reports "no wiki scopes configured"** — no scopes exist yet → run `/lazy-wiki.install` then `/lazy-wiki.configure` first.
- **`/lazy-wiki.audit` reports `domain-output-in-scope`** — a scope's `paths` glob reaches the generated domain-spec tree; the tree is excluded from every scope structurally, so the glob claims nothing there and no file has two writers → narrow the glob via `/lazy-wiki.configure` so the scope's coverage matches what it curates.
