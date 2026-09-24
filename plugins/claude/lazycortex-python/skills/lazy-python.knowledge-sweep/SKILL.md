---
name: lazy-python.knowledge-sweep
description: "Run when the operator asks to update or grow the domain-groups dictionary — 'add these groups', 'the dictionary is missing half our domains', 'file the unfiled blocks' — or when parked `Domain(unfiled):` findings have piled up in the checker output and nobody can clear them by hand. Also the backfill route for a repo that just adopted domain markers: clusters the parked knowledge into candidate groups, writes the ones the operator accepts into the dictionary, then sweeps the sources so every block lands under a real group."
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
user-invocable: true
---
# Python knowledge sweep — backfill domain and contract markers

Sweeps the repo's Python sources with the `lazy-python.domain-writer` and `lazy-python.contract-writer` agents so existing code catches up with the canon's knowledge-marker discipline: domain mechanics get `Domain(<group>):` blocks, caller-visible guarantees get `Contract:` blocks with synced docstring `Guarantees` sections. Builds the domain-groups dictionary first when the repo has none. The canon requires markers at writing time; this sweep pays down the debt of code written before the discipline (or before the current dictionary).

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve dictionary`
   - `Step 2 — Grow the dictionary from parked knowledge`
   - `Step 3 — Enumerate files`
   - `Step 4 — Dispatch writers`
   - `Step 5 — Consolidate the dictionary`
   - `Step 6 — Consolidate the contracts`
   - `Step 7 — Verify`
   - `Step 8 — Commit`
   - `Step 9 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND emitted a one-word outcome. A step the run skips must be marked explicitly with the outcome that justified the skip (`no-files`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly skipped with an outcome.** A still-`pending` task is a bug — execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above.

## Step 1 — Resolve dictionary

Resolve the dictionary path: `.claude/lazy.settings.json[wiki.domains.dictionary]` when set, else the conventional `docs/guidelines/domain-groups.md`.

Read it when it exists; note its absence when it does not. Either way Step 2 is what fills it — starting from the existing groups, or from nothing.

Outcome: `dictionary-read` or `dictionary-absent`.

## Step 2 — Grow the dictionary from parked knowledge

Always runs. Parked knowledge is the whole reason a sweep is invoked: `Domain(unfiled):` blocks accumulate because no listed group fit, and they keep burning as checker findings until the dictionary grows to hold them. Walking straight to the writers with an unchanged dictionary would re-park every one of them.

1. **Collect.** "The sources" everywhere in this step means the scope Step 3 resolves — resolve it here rather than grepping the whole tree, so the candidate groups describe the code the sweep will actually mark. Grep them for `Domain(unfiled):` blocks and read each block's body. Also read the sources' subject-area vocabulary the way Step 1 of a from-scratch build would — module and package names, recurring domain nouns in docstrings — so a repo with no markers yet still yields candidates.
2. **Cluster.** Group the parked blocks by the subject area they describe, not by file or module. Each cluster is one candidate group: a dot-hierarchy name, a one-line gloss, and the parked blocks it would absorb.
3. **Settle the cut.** Do not ask. Take the finest cut the clusters justify: one group per subject a reader would open separately, and no group merged with another merely to keep the count down. Blocks that share a subject share a group even when they sit in different packages; blocks that do not, do not — a subject worth its own document gets one. Report the cut you settled on, with the blocks under each group, so the operator can overrule a name or a boundary afterwards. A cluster too thin or too ambiguous to name honestly stays parked, and the report says which and why.
4. **Write.** Append every accepted group to the dictionary as a `## <group>` heading plus its gloss line, preserving the existing entries byte-for-byte. Create the file when Step 1 reported `dictionary-absent`. `unfiled` is never listed — it is reserved, not a domain.
5. **Reconcile unknown groups.** Parked blocks are not the only broken filing: a block can carry a group that is simply not in the dictionary — a typo, or a name invented at the keyboard — and nothing in the pipeline repairs those. Grep the sources for every `Domain(<group>):` whose group is neither `unfiled` nor listed in the dictionary as it now stands, then settle each one yourself: add it to the dictionary when the name is sound under the naming law, or rename it into the listed group it duplicates — carried into Step 4 as a `rename=<old>-><new>` instruction, since only the writer agent edits code. Report every add and every rename so the operator can overrule it.

The dictionary is the operator's registry, so every name this step writes is reported back in full and stays theirs to overrule. When nothing is parked and no candidate survives, the dictionary is left untouched.

Outcome: `<N>-groups-added`, `<K>-groups-renamed`, `dictionary-unchanged`, or `nothing-parked`.

## Step 3 — Enumerate files

List the sweep scope in this precedence, first hit wins:

1. Explicit paths the operator passed to the skill.
2. The globs in `.claude/lazy.settings.json[wiki.domains.code]` when the section is configured — `git ls-files -- <glob> …`, one pathspec per glob. That key already declares which code the domain tooling reads; sweeping wider marks files the generator will never look at, and on a repo whose tests outnumber its sources it multiplies the dispatch count for nothing.
3. `git ls-files -- '*.py'` when neither is available.

In every case, subtract the paths the project's settings exclude from checking (same exclusions `chk-py` honors, if any are configured).

Report which of the three the scope came from — the operator has to know whether a file missing from the sweep was excluded or simply outside the configured globs.

Empty scope → outcome `no-files`; mark Steps 4 through 8 skipped with that same outcome and go to Step 9.

Outcome: `<N>-files-enumerated-<explicit|domains-globs|all-python>`.

## Step 4 — Dispatch writers

For each file, dispatch the two writer agents from this plugin — `lazy-python.domain-writer` (domain mechanics, validates groups against the dictionary, parks unmatched knowledge under `Domain(unfiled):`; refiles existing `unfiled` blocks when the dictionary now has a fitting group) and `lazy-python.contract-writer` (caller-visible guarantees plus the docstring `Guarantees` sync). Batch dispatches — up to 4 parallel agents, domain-writer and contract-writer for the same file never concurrently (both edit it).

Both agents read the canon and the dictionary themselves on every dispatch, so the prompt carries only what they cannot resolve alone:

- **Every dispatch** — the file path and `dictionary=<the path Step 1 resolved>`; the resolved path wins over the agent's conventional fallback.
- **Every `lazy-python.domain-writer` dispatch** — `refile=true`, which is what licenses the agent to re-pick a group for the file's already-parked blocks against the grown dictionary and rewrite their header lines. Without the token it only ever writes new blocks and Step 2's growth reaches nothing that is already parked.
- **Renames accepted in Step 2** — one `rename=<old>-><new>` token per group the operator chose to rename, on the domain-writer dispatch for each file that uses it.

A file where an agent finds nothing to mark is a legitimate no-op.

Outcome: `<N>-files-swept`.

## Step 5 — Consolidate the dictionary

Always runs when Step 4 wrote anything. Each writer saw one file or one package and proposed a group from it; nobody saw the corpus. Divergence that no single dispatch could notice lives only at this scale, and it is the operator's dictionary that inherits it.

Collect every block the sweep wrote — file, symbol, block title, the group or candidate it carries — plus every group already listed. Do not re-read the code: this step judges the set of groups, never the knowledge inside a block.

Then put the corpus through five checks, in order:

1. **Synonyms** — two candidates naming one subject (`geo.grid` against `geo.grids`, `movement` against `mechanics.movement`) collapse into one name.
2. **Overloaded groups** — a group whose blocks split into two unrelated subjects is cut in two. Judge by what the block titles say, not by how many there are.
3. **Thin groups** — a group holding a single block is folded into its nearest neighbour, unless the subject is genuinely separate and the operator says to keep it.
4. **Naming law** — every surviving name is re-checked: drawn from the vocabulary the code itself uses and not colliding with a word the codebase spends on another subject, at least two dot-separated segments, the first naming the subject area and the second the topic inside it, plus whatever the dictionary's own prose adds — reserved prefixes, singular against plural. A single-segment name is always a defect at this step, never a style choice: it names an area with no topic, or a topic with no area. Candidates from independent dispatches routinely disagree on depth; settle it here.
5. **Glosses** — each surviving group's one-line gloss is rewritten to match what it actually ended up holding.

Do not ask. Settle the consolidated cut yourself and apply it, then report it in full — every surviving group, its gloss, and the blocks under it — so the operator can overrule a name or a boundary against a finished result rather than against a hypothetical. Keep the cut fine: consolidation removes divergence between independently proposed names, it does not merge subjects that a reader would look up separately.

On that cut, write the groups into the dictionary, then refile: for every block whose group changed, dispatch `lazy-python.domain-writer` with `refile=true` over its file. A header-only rewrite across many files is mechanical — do it directly, in one pass, and reserve the writer dispatch for a block whose body must change.

Outcome: `<N>-groups-final`, `<M>-blocks-refiled`, or `nothing-written` when Step 4 produced no blocks.

## Step 6 — Consolidate the contracts

Always runs when Step 4's contract half wrote anything. Each contract-writer saw one file and judged its guarantees in isolation; the defects that survive that view — divergent phrasings of one guarantee, blocks a sibling already carries, blocks the canon excludes — live only at corpus scale, and it is the reader of the published `Guarantees` sections who inherits them.

Collect every `Contract:` block the sweep wrote — file, symbol, guarantee text — plus the pre-existing blocks of the same classes for parity reference. Judge the set of guarantees, never re-derive them from the code: a writer already verified each block against its implementation. The one lookup this step does make is the audience check below — who overrides or calls a block's owner is a fact of the tree, not of the block.

Then put the corpus through three checks, in order:

1. **Canon exclusions** — a block the canon's "when not to use" list rejects (presentation details such as exact message text or output formatting, signature-obvious facts, implementation details) is removed together with the `Guarantees` bullet it backs. Independent writers drift toward formalism precisely on these; the corpus view is where the pattern shows.
2. **Sibling parity** — one guarantee stated across sibling classes converges to one phrasing, and moves to the base class when the base is what enforces it.
3. **Redundancy** — two blocks carrying one guarantee are folded ONLY when they address the same consumer. Audiences differ by surface: a public method speaks to external callers, a protected hook to the subclasses that override or call it, a base class to every subclasser, a private helper to the maintainer already reading its caller. Before folding anything, grep for overrides and callers of the candidate copy's owner: a block on a hook that any subclass overrides, or on a surface with its own readers, stays even when its text matches another block word for word. Fold only a copy whose readers already read the surviving block — a private helper with no overrides and a single caller that carries the same text is the canonical case.

Do not ask. Settle the cut yourself and apply it, then report it in full — every removed and reworded block with its file and symbol — so the operator can overrule against a finished result. Removal or rewording of a block is a contract edit: dispatch `lazy-python.contract-writer` per affected file with the explicit list of blocks to remove or rewrite — the settled cut is the approval the canon's treatment rules require. A pure wording alignment that changes no guarantee may be applied directly in one pass.

Outcome: `<N>-blocks-removed, <M>-blocks-reworded`, or `contracts-consistent`, or `nothing-written` when Step 4's contract half produced no blocks.

## Step 7 — Verify

Run the repo's check gate over the touched files: `chk-py all -q` (repo wrapper installed by `/lazy-python.install`; project `check_cmd` override wins when configured). Writers verify their own edits per dispatch, Step 5 rewrote only header lines, and Step 6's edits were re-checked by their own dispatches, so this pass catches only cross-file fallout. Fix regressions the sweep itself introduced; anything pre-existing is reported, not fixed.

Outcome: `verified-clean`, `<N>-issues-remain`, or `gate-absent` when the repo ships no wrapper to run.

## Step 8 — Commit

Commit every file the sweep touched (marker edits, plus the dictionary whenever Step 2 or Step 5 grew or created it) under the operator identity, with an explicit pathspec:

```bash
git commit -m "docs(py): backfill Domain/Contract knowledge markers" -- <touched paths>
```

The commit is what wakes the domain-spec generation routine in repos that run one — group hashes changed, the affected docs regenerate. On a checkout without a daemon, tell the operator to run `/lazy-wiki.domain-sync` next. In transactional git state (merge/rebase markers), skip the commit and report the paths instead.

Outcome: `committed` or `commit-skipped`.

## Step 9 — Log the run

Write a run log per `lazy-log.logging`:

- Path: `./.logs/claude/lazy-python.knowledge-sweep/YYYY-MM-DD_HH-MM-SS.md` (timestamp via `date -u +%Y-%m-%d_%H-%M-%S`).
- Steps: `Bash(mkdir -p ./.logs/claude/lazy-python.knowledge-sweep)` then a single `Write` — never chain with `&&`.
- Frontmatter: `git_sha`, `git_branch`, `date` (`YYYY-MM-DD HH:MM:SS UTC`), `input` (explicit paths or `none`).
- Body: `# lazy-python.knowledge-sweep` heading; `## Actions` with one bullet per step + outcome; `## Result` with the final state.

Outcome: `logged`.

## Report

One line per task in the canonical list above, each with its outcome word. A missing line is a bug.

## Failure modes

- **Step 2 proposes no candidate groups** — nothing is parked under `Domain(unfiled):` and the sources carry no recognizable subject-area vocabulary yet; the operator can still add groups by hand via "Other", or let the sweep run against the dictionary as it stands.
- **`chk-py` is not installed in the repo** — Step 7 has no gate to run; report it and point the operator at `/lazy-python.install`. The sweep's edits stay in the worktree uncommitted only if the operator asks to hold them.
- **A writer marks knowledge under `Domain(unfiled):`** — expected, not an error: no listed group fit, or the operator rejected the cluster that would have held it in Step 2. The block surfaces via the checker on every run until it is filed; the next sweep offers its cluster again.
