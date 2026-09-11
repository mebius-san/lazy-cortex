---
name: lazy-review.install
description: "Run when the operator asks to set up document review in this repo, after a lazycortex-review update, or when review skills fail because `lazy.settings.json` has no `review` section, the `.experts/.jobs/` queue is missing, or the coordinator routines were never registered. Per-repo bootstrap only — wiring the first document class is `/lazy-review.configure`. Idempotent and quiet on re-run."
allowed-tools: Read, Write, AskUserQuestion, Skill, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date *), Bash(cp *), Bash(test *), Bash(diff *), Bash(git rev-parse*), Bash(lazycortex-core *), Agent
---
# lazy-review.install

Per-repo bootstrap: gets a clean checkout to the point where the review loop can start ticking. The bin script does the actual mutation; this skill is the operator-facing pipeline that runs it, installs the review callout styling into the Obsidian vault, points at `/lazy-review.configure` for class wiring, and prints the optional `.gitignore` entries the operator may want to add by hand (the skill never touches `.gitignore` without explicit permission).

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. Canonical titles:
   - `Step 1 — Bootstrap settings + dirs`
   - `Step 3 — Attach routine protocols`
   - `Step 4 — Surface gitignore suggestions`
   - `Step 5 — Register the plugin-CLI Bash allow-pattern`
   - `Step 5.5 — Seed agent-model tiers`
   - `Step 5.6 — Install the review-callouts CSS snippet`
   - `Step 6 — Point user at /lazy-review.configure`
   - `Report`
   - `Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** Each step emits a one-word outcome (`installed` / `already-installed` / `registered` / `already-present` / `attached` / `surfaced` / `cli-allow-added` / `cli-allow-already-present` / `seeded` / `unchanged` / `merged` / `kept-local` / `enabled` / `already-enabled` / `deferred` / `no-vault` / `pointed` / `report-emitted`).
3. **Do not reach the Report step until every prior task is `completed`.**

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice is derived or read-first; the user is asked again only when nothing is on record.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-artifact opt-in.
- **Scope is not asked.** lazy-review is per-repo — all runtime artifacts land under the cwd's git root regardless of where the plugin is enabled, so there is no user-vs-project branch to resolve here. (Scope detection for plugins that DO branch their target lives in `lazy-core.install` Step 1, keyed on enablement rather than the install record's `scope`.)
- **No daemon gate.** The routine trio is registered unconditionally. `/lazy-runtime.tick` fires the same interval, git-watch, and cron routines on a checkout with no daemon, so gating registration on `daemon.enabled` would only withhold config the manual tick needs. The flag governs the supervisor unit and the metrics endpoint, both `lazy-core.install`'s business.
- **No Python re-probe.** The Python ≥ 3.12 floor is enforced once by `lazy-core.install`; this skill does NOT re-probe it.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write the new version silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged from shipped, but the shipped delta applies without contradicting local edits (new sections / keys / entries added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. The asking site prints its context first — where (`/lazy-review.install · Step <N>` and the target file), found (the conflicting region quoted as a unified diff, both sides), why asking (local and shipped changed the same region; nothing can tell which should survive), answers (`merge-shipped` — shipped wins for that region, local edits elsewhere kept, state `merged`; `keep-local` — local wins for that region, the non-conflicting shipped delta still applied, state `kept-local`; the answer is not persisted and is asked again on the next conflicting update) — then `AskUserQuestion` with the file named in the question and the two options carrying those consequences as descriptions.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

## Step 1 — Bootstrap settings + dirs

Run `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/install.py" --cwd .`. The script applies the File-sync policy at the section level:

- Creates `.claude/lazy.settings.json` if missing, or merges the defaults in for absent top-level keys and absent nested keys only — existing values are never overwritten (cases 1–2; the bin contains no contradicting-region path, so case 3 never arises here).
- Creates `.experts/.jobs/` and `.logs/lazy-review/runs/` if missing.
- Prints a JSON report of what changed, including a `migrated` list.

The script's default seed includes the routine trio the loop runs on — `routines["lazy-review.collect"]` (the interval postman that lands finished expert payloads), `routines["lazy-review.coordinator-watch"]` (the git-watch that turns a commit into a coordinator wake), and `routines["lazy-review.sanitize"]` (the daily deterministic sanitizer that repairs lost writer wakes, orphaned reviews, and markers on vanished documents) — plus `review.watch_root`, `review.coordination_rules`, and the `experts["review.coordinator"]` identity. All three routines stay registered whatever the project's daemon posture is.

**Migration on a repo installed before the coordinator.** The bin applies it in the same run, unconditionally — none of the three steps below reads a version number — and the `migrated` list names each change:

- **Retires `routines["lazy-review.scan"]`.** The md-scan sieve is gone with the script state machine; its `process-file` consumer no longer exists, so a surviving registration is a routine the daemon runs into a missing subcommand.
- **Derives `review.watch_root`** from the common wildcard-free root of that routine's `paths` before removing it (`specs/core/**/*.md` + `specs/review/**/*.md` → `specs`), falling back to `.` when the globs share no literal root. The watch routine's `path_filter` is `:(glob)<watch_root>/**/*.md` — a single pathspec, because core's git-watch takes one; class precision stays in `review.classes[].paths`. An operator's own `review.watch_root` is never re-derived.
- **Drops the `history` group** from every `review.classes[*].experts`. The historian is retired; the coordinator writes `# History` inline, so the link points at an expert nothing dispatches.
- **Leaves `review._version` alone.** The `review` section's version ladder belongs to `lazycortex-core`, which skips any section already standing at or beyond its own target — a number written from this side makes core skip its next step forever. The two cleanups above are version-independent and apply whatever the section's number is.

Outcome: `installed` (anything was created or merged) or `already-installed` (no-op).

## Step 3 — Attach routine protocols

Step 1's seed gives `lazy-review.coordinator-watch` its **mandatory** protocol, the coordination playbook the woken coordinator reasons from. The doc-review protocol is NOT attached here: the coordinator attaches it to each expert job it dispatches, and the routine's own job carries the playbook instead. Attach the shared markdown-style protocol too, since every wake produces markdown in the vault — a mandatory protocol is not an operator choice, so no question is asked:

```
Bash(lazycortex-core add-protocols --routine lazy-review.coordinator-watch --ids lazycortex-core:lazy-core.markdown-style)
```

That is the whole step. The coordinator is a system expert: its protocol set is fixed by design, so install never offers optional protocols for its routine and asks the operator nothing here. An operator who wants an extra protocol on a routine attaches it deliberately via `/lazy-routine.offer-protocols` — that skill is the operator-facing channel, not an install sub-step.

`lazy-review.collect` takes no protocols — it is a mechanical sweep that dispatches no agent.

Outcome: **attached** (the mandatory set is now on the routine, whether newly added or already present).

## Step 4 — Surface gitignore suggestions

The runtime writes operator-private state into the repo: the whole `.experts/` tree (job queue, subprocess locks) and tick logs under `.logs/lazy-review/`. Operators typically want both gitignored. This skill MUST NOT write to `.gitignore` itself — instead, print the recommended lines and tell the operator to add them by hand:

```
.experts/
.logs/lazy-review/
```

Outcome: `surfaced`.

## Step 5 — Register the plugin-CLI Bash allow-pattern

The plugin ships `bin/lazycortex-review` which is invoked from other skills via `Bash(lazycortex-review ...)` — `lazy-review.start`, `lazy-review.finalize`, and the review dispatcher all call it. Expert subprocesses spawned by the `lazy-core.runtime` daemon run under Claude Code's `dontAsk` permission mode — that mode silently denies any Bash command not on the auto-allow list. Without this entry, every cross-skill CLI invocation from a dispatched expert fails with `Permission to use Bash has been denied because Claude Code is running in don't ask mode`, and the agent drifts off-protocol mid-step.

Per `lazy-core.hygiene` § Settings split, per-tool permissions live in `settings.local.json` (gitignored), never tracked `settings.json`. Target file: `<repo-root>/.claude/settings.local.json` (lazy-review is a per-repo plugin, so user-scope is not a target).

Apply via the `lazycortex-core` CLI (idempotent — already-present patterns are no-ops):

```
Bash(lazycortex-core permission-allow <repo-root>/.claude/settings.local.json "Bash(lazycortex-review *)")
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 5.5 — Seed agent-model tiers

The plugin ships the `review.coordinator` and `lazy-review.doc_doctor` subagents. Seed their canonical model tiers into the `agent_models.lazycortex` group by dispatching the shared primitive — it owns the `default-tiers.json` locate, the `lazycortex-review:`-prefix filter, and the non-destructive per-key semantics (absent→add, equal→unchanged, different→kept-local). No inline tier logic here. lazy-review is per-repo, so the scope is always `project`.

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-review scope=project")
```

Fold the primitive's returned report block verbatim into this skill's Report. Surface its terminal outcomes:

- **`sot-missing`** — `lazycortex-core`'s `default-tiers.json` was not found → the primitive aborts; relay its message (`lazycortex-core not installed; install it before seeding lazycortex-review tiers`) and do not fabricate seed lines.
- **`no-entries`** — the SOT lists no `lazycortex-review:` agents → report it plainly (a maintainer must extend `default-tiers.json`); not an abort.

Outcome: `seeded` (any entry added) or `unchanged`.

## Step 5.6 — Install the review-callouts CSS snippet

The review loop's own callouts — the banner `[!note] #review/<state-tag>`, the operator command channel `[!todo] #review/command`, escalations `[!question] #review/question`, concerns `[!attention] #review/concern` — are ordinary Obsidian callouts until the styling that tells them apart is in the vault. The snippet keys off the `#review/*` tag inside each callout, so every kind reads differently at a glance.

| Artifact | Target | Source |
|---|---|---|
| `review-callouts.css` snippet | `<vault>/.obsidian/snippets/review-callouts.css` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/review-callouts.css` |

1. **Locate the vault.** Repo root is `git rev-parse --show-toplevel` (fall back to cwd); vault is `<repo-root>/.obsidian`. If it does not exist, this repo is not an Obsidian vault — state **no-vault** and continue to Step 6. Otherwise `mkdir -p <vault>/snippets`.
2. **Sync the snippet** per the File-sync policy above: absent or byte-identical → `cp` silently (**installed** / **unchanged**); locally changed with the shipped delta applying to disjoint regions → merge silently (**merged**); same region changed incompatibly on both sides → the only case that asks (**merged** / **kept-local**):

   ```
   Context (print before asking):
   - Where: /lazy-review.install · Step 5.6 — Install the review-callouts CSS snippet; target <vault>/snippets/review-callouts.css
   - Found: local and shipped both changed the same region — the conflicting hunk(s), both sides, quoted as a unified diff
   - Why asking: you customized the snippet where the shipped version changed; nothing can tell which should survive
   - Answers: `merge-shipped` — shipped version written for that region, your non-conflicting edits kept (**merged**); `keep-local` — your version kept for that region, the rest of the shipped delta still applied (**kept-local**); not persisted, asked again on the next conflicting update
   AskUserQuestion: header "Snippet conflict", question "review-callouts.css in <vault>/snippets/ — conflicting edits in the same region. Which version wins for that region?", options `merge-shipped` — "shipped wins for the conflicting region; your edits elsewhere are kept", `keep-local` — "your edits win; the rest of the upstream change still applies".
   ```

   **Under a no-questions run** (`lazy-core.autosetup` and anything else driving this skill without an operator channel), do not stall on the question: keep the local region, apply the rest of the shipped delta, and state **kept-local-unattended**, naming the conflicting file so the operator can resolve it by running this skill by hand. The conflict genuinely cannot be decided without them — but a question nobody can answer must still leave a determinate outcome, or the step reports `needs-interactive` on every unattended run for as long as the customisation stands.
3. **Enable it in `<vault>/appearance.json`.** Read the file (treat missing or unparseable as `{}`), ensure `enabledCssSnippets` exists as an array, and append `"review-callouts"` when absent. Write only when the array changed. Do NOT add the entry when the snippet file is not on disk — a stale registration points at nothing; state **deferred** in that case. Outcome otherwise: **enabled** (added this run) or **already-enabled**.

Obsidian does not watch `appearance.json` mid-session, so when the outcome is **enabled** the Report tells the operator to reload Obsidian (or click ↻ next to the snippet in Settings → Appearance → CSS snippets).

Outcome: the snippet's sync word plus the enablement word (`installed+enabled`, `unchanged+already-enabled`, …), or **no-vault**.

## Step 6 — Point user at /lazy-review.configure

Tell the operator: *"Settings scaffolded with empty `review.classes` — run `/lazy-review.configure` to register your first class."*

Outcome: `pointed`.

## Report

One line per task in the canonical list with its outcome word.

## Logging

Log the run to `./.logs/claude/lazy-review.install/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-review.install)` — a separate step from the `Write`, never chained.
2. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` for the filename; `Bash(git rev-parse HEAD)` and `Bash(git rev-parse --abbrev-ref HEAD)` for `git_sha` / `git_branch` (`no-git` when either fails).
3. `Write` the file. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input` (the arguments passed, or `none`).
4. Body: `# lazy-review.install` heading, then `## Actions` — one line per Step in the canonical list with its outcome word — and `## Result` with the outcome word and a one-sentence summary.

## Failure modes

- **Step 1 fails with permission error on `.claude/lazy.settings.json`** — operator's shell user can't write there → fix file ownership, re-run.
- **JSON parse error on existing settings** — operator's `.claude/lazy.settings.json` is hand-edited and malformed → fix the JSON manually, re-run.
- **Step 1 reports `review.watch_root` as `.` on a repo that used to scan a narrow subtree** — the retired routine's `paths` shared no literal directory prefix, so the watch fell back to the whole repo → set `review.watch_root` by hand and re-run; the bin never re-derives an operator-set value.
- **Step 5.6 states `no-vault`** — this repo has no `.obsidian/` directory → nothing to style; review still works, the callouts just render with Obsidian's default look.
- **Review callouts still look alike after install** — `appearance.json` changed while Obsidian was running → reload the vault, or click ↻ next to `review-callouts` in Settings → Appearance → CSS snippets.
