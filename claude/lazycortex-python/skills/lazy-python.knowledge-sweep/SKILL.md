---
name: lazy-python.knowledge-sweep
description: "Run when the operator asks to update or grow the domain-groups dictionary — 'add these groups', 'the dictionary is missing half our domains', 'file the unfiled blocks' — or when parked `Domain(unfiled):` findings have piled up in the checker output and nobody can clear them by hand. Also the backfill route for a repo that just adopted domain markers: clusters the parked knowledge into candidate groups, writes the ones the operator accepts into the dictionary, then sweeps the sources so every block lands under a real group."
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
user-invocable: true
---
# Python knowledge sweep — backfill domain and contract markers

Sweeps the repo's Python sources with the `lazy-python.domain-writer` and `lazy-python.contract-writer` agents so existing code catches up with the canon's knowledge-marker discipline: domain mechanics get `Domain(<group>):` blocks, caller-visible guarantees get `Contract:` blocks with synced docstring `Guarantees` sections. Builds the domain-groups dictionary first when the repo has none. The canon requires markers at writing time; this sweep pays down the debt of code written before the discipline (or before the current dictionary).

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve dictionary`
   - `Step 2 — Grow the dictionary from parked knowledge`
   - `Step 3 — Enumerate files`
   - `Step 4 — Dispatch writers`
   - `Step 5 — Verify`
   - `Step 6 — Commit`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND emitted a one-word outcome. A step the run skips must be marked explicitly with the outcome that justified the skip (`no-files`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly skipped with an outcome.** A still-`pending` task is a bug — execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above.

## Step 1 — Resolve dictionary

Resolve the dictionary path: `.claude/lazy.settings.json[wiki.domains.dictionary]` when set, else the conventional `docs/guidelines/domain-groups.md`.

Read it when it exists; note its absence when it does not. Either way Step 2 is what fills it — starting from the existing groups, or from nothing.

Outcome: `dictionary-read` or `dictionary-absent`.

## Step 2 — Grow the dictionary from parked knowledge

Always runs. Parked knowledge is the whole reason a sweep is invoked: `Domain(unfiled):` blocks accumulate because no listed group fit, and they keep burning as checker findings until the dictionary grows to hold them. Walking straight to the writers with an unchanged dictionary would re-park every one of them.

1. **Collect.** "The sources" everywhere in this step means the scope Step 3 resolves — resolve it here rather than grepping the whole tree, so the candidate groups describe the code the sweep will actually mark. Grep them for `Domain(unfiled):` blocks and read each block's body. Also read the sources' subject-area vocabulary the way Step 1 of a from-scratch build would — module and package names, recurring domain nouns in docstrings — so a repo with no markers yet still yields candidates.
2. **Cluster.** Group the parked blocks by the subject area they describe, not by file or module. Each cluster is one candidate group: a dot-hierarchy name, a one-line gloss, and the parked blocks it would absorb.
3. **Propose.** Present the candidates to the operator with `AskUserQuestion`, one question at a time (multi-select where the choices are independent). Show each candidate's name, gloss, and how many parked blocks it covers. The operator ticks, edits, adds their own via "Other", or rejects. A rejected cluster stays parked — that is a legitimate answer.
4. **Write.** Append every accepted group to the dictionary as a `## <group>` heading plus its gloss line, preserving the existing entries byte-for-byte. Create the file when Step 1 reported `dictionary-absent`. `unfiled` is never listed — it is reserved, not a domain.
5. **Reconcile unknown groups.** Parked blocks are not the only broken filing: a block can carry a group that is simply not in the dictionary — a typo, or a name invented at the keyboard — and nothing in the pipeline repairs those. Grep the sources for every `Domain(<group>):` whose group is neither `unfiled` nor listed in the dictionary as it now stands, then put each one to the operator with `AskUserQuestion`, showing the group, how many blocks use it, and the listed groups closest to it. Two answers act: **add** appends it to the dictionary like any accepted candidate (name plus gloss), **rename** picks a listed group to move its blocks under — carried into Step 4 as a `rename=<old>-><new>` instruction, since only the writer agent edits code. Declining both leaves the group as it is; the next sweep offers it again.

Never invent a group without the operator's tick: the dictionary is the operator's registry, this step only proposes. When nothing is parked and no candidate survives, the dictionary is left untouched.

Outcome: `<N>-groups-added`, `<K>-groups-renamed`, `dictionary-unchanged`, or `nothing-parked`.

## Step 3 — Enumerate files

List the sweep scope in this precedence, first hit wins:

1. Explicit paths the operator passed to the skill.
2. The globs in `.claude/lazy.settings.json[wiki.domains.code]` when the section is configured — `git ls-files -- <glob> …`, one pathspec per glob. That key already declares which code the domain tooling reads; sweeping wider marks files the generator will never look at, and on a repo whose tests outnumber its sources it multiplies the dispatch count for nothing.
3. `git ls-files -- '*.py'` when neither is available.

In every case, subtract the paths the project's settings exclude from checking (same exclusions `chk-py` honors, if any are configured).

Report which of the three the scope came from — the operator has to know whether a file missing from the sweep was excluded or simply outside the configured globs.

Empty scope → outcome `no-files`; mark Steps 4, 5, and 6 skipped with that same outcome and go to Step 7.

Outcome: `<N>-files-enumerated-<explicit|domains-globs|all-python>`.

## Step 4 — Dispatch writers

For each file, dispatch the two writer agents from this plugin — `lazy-python.domain-writer` (domain mechanics, validates groups against the dictionary, parks unmatched knowledge under `Domain(unfiled):`; refiles existing `unfiled` blocks when the dictionary now has a fitting group) and `lazy-python.contract-writer` (caller-visible guarantees plus the docstring `Guarantees` sync). Batch dispatches — up to 4 parallel agents, domain-writer and contract-writer for the same file never concurrently (both edit it).

Both agents read the canon and the dictionary themselves on every dispatch, so the prompt carries only what they cannot resolve alone:

- **Every dispatch** — the file path and `dictionary=<the path Step 1 resolved>`; the resolved path wins over the agent's conventional fallback.
- **Every `lazy-python.domain-writer` dispatch** — `refile=true`, which is what licenses the agent to re-pick a group for the file's already-parked blocks against the grown dictionary and rewrite their header lines. Without the token it only ever writes new blocks and Step 2's growth reaches nothing that is already parked.
- **Renames accepted in Step 2** — one `rename=<old>-><new>` token per group the operator chose to rename, on the domain-writer dispatch for each file that uses it.

A file where an agent finds nothing to mark is a legitimate no-op.

Outcome: `<N>-files-swept`.

## Step 5 — Verify

Run the repo's check gate over the touched files: `chk-py all -q` (repo wrapper installed by `/lazy-python.install`; project `check_cmd` override wins when configured). Writers verify their own edits per dispatch, so this pass catches only cross-file fallout. Fix regressions the sweep itself introduced; anything pre-existing is reported, not fixed.

Outcome: `verified-clean`, `<N>-issues-remain`, or `gate-absent` when the repo ships no wrapper to run.

## Step 6 — Commit

Commit every file the sweep touched (marker edits, plus the dictionary whenever Step 2 grew or created it) under the operator identity, with an explicit pathspec:

```bash
git commit -m "docs(py): backfill Domain/Contract knowledge markers" -- <touched paths>
```

The commit is what wakes the domain-spec generation routine in repos that run one — group hashes changed, the affected docs regenerate. On a checkout without a daemon, tell the operator to run `/lazy-wiki.domain-sync` next. In transactional git state (merge/rebase markers), skip the commit and report the paths instead.

Outcome: `committed` or `commit-skipped`.

## Step 7 — Log the run

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
- **`chk-py` is not installed in the repo** — Step 5 has no gate to run; report it and point the operator at `/lazy-python.install`. The sweep's edits stay in the worktree uncommitted only if the operator asks to hold them.
- **A writer marks knowledge under `Domain(unfiled):`** — expected, not an error: no listed group fit, or the operator rejected the cluster that would have held it in Step 2. The block surfaces via the checker on every run until it is filed; the next sweep offers its cluster again.
