---
name: lazy-review.install
description: "Per-repo bootstrap for lazycortex-review. Seeds lazy.settings.json with review.classes / experts defaults, creates .experts/.jobs/ and .logs/lazy-review/runs/ directories, registers the daemon-gated lazy-review.scan routine, and registers the plugin-CLI Bash allow-pattern in settings.local.json. Idempotent and quiet on re-run — every decision is derived or read-first, never re-asked; an enabled plugin installs its whole surface."
allowed-tools: Read, AskUserQuestion, Skill, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(lazycortex-core *)
lazy_setup_phase: install
---
# lazy-review.install

Per-repo bootstrap: gets a clean checkout to the point where the daemon can start ticking. The bin script does the actual mutation; this skill is the operator-facing pipeline that runs it, gates the daemon-dependent scan routine behind the project's `daemon.enabled` flag, points at `/lazy-review.configure` for class wiring, and prints the optional `.gitignore` entries the operator may want to add by hand (the skill never touches `.gitignore` without explicit permission).

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical titles:
   - `Step 1 — Bootstrap settings + dirs`
   - `Step 2 — Gate the lazy-review.scan routine on daemon.enabled`
   - `Step 3 — Attach optional routine protocols`
   - `Step 4 — Surface gitignore suggestions`
   - `Step 5 — Register the plugin-CLI Bash allow-pattern`
   - `Step 6 — Point user at /lazy-review.configure`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Each step emits a one-word outcome (`installed` / `already-installed` / `registered` / `already-present` / `skipped-daemon-disabled` / `attached` / `no-relevant-candidates` / `declined` / `surfaced` / `cli-allow-added` / `cli-allow-already-present` / `pointed` / `report-emitted`).
3. **Do not reach the Report step until every prior task is `completed`.**

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice is derived or read-first; the user is asked again only when nothing is on record.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-artifact opt-in.
- **Scope is not asked.** lazy-review is per-repo — all runtime artifacts land under the cwd's git root regardless of where the plugin is enabled, so there is no user-vs-project branch to resolve here. (Scope detection for plugins that DO branch their target lives in `lazy-core.install` Step 1, keyed on enablement rather than the install record's `scope`.)
- **Daemon gate is read-first.** Step 2 reads the tracked `daemon.enabled` flag and never re-raises Gate 1 (that gate belongs to `lazy-core.install`).
- **No Python re-probe.** The Python ≥ 3.12 floor is enforced once by `lazy-core.install`; this skill does NOT re-probe it.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write the new version silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged from shipped, but the shipped delta applies without contradicting local edits (new sections / keys / entries added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, and showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

## Step 1 — Bootstrap settings + dirs

Run `python3 claude/lazycortex-review/bin/install.py --cwd .`. The script applies the File-sync policy at the section level:

- Creates `.claude/lazy.settings.json` if missing, or merges the defaults in for absent top-level keys and absent nested keys only — existing values are never overwritten (cases 1–2; the bin contains no contradicting-region path, so case 3 never arises here).
- Creates `.experts/.jobs/` and `.logs/lazy-review/runs/` if missing.
- Prints a JSON report of what changed.

The script's default seed includes the `routines["lazy-review.scan"]` entry; Step 2 gates whether that entry survives.

Outcome: `installed` (anything was created or merged) or `already-installed` (no-op).

## Step 2 — Gate the lazy-review.scan routine on daemon.enabled

`lazy-review.scan` is an md-scan routine (`command: ["lazycortex-review", "process-file"]`) that ONLY works with the `lazycortex-core` runtime daemon — the daemon globs matching files and runs the consumer per-match. With the daemon off, the routine is dead config. So before leaving it registered, read the tracked `daemon.enabled` flag. Resolve the core bin via `$LAZYCORTEX_PLUGIN_DIRS` (fall back to the cache glob when unset, as at install time):

```bash
COREBIN=""
IFS=":" read -ra DIRS <<< "${LAZYCORTEX_PLUGIN_DIRS:-}"
for d in "${DIRS[@]}"; do
  if [[ "$d" == *"/lazycortex-core" ]] && [ -d "$d/bin" ]; then COREBIN="$d/bin"; break; fi
done
[ -z "$COREBIN" ] && COREBIN=$(ls -d ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/bin 2>/dev/null | sort -V | tail -1)
PYTHONPATH="$COREBIN" python3 -c "
from lazy_settings import load_tracked_section
from pathlib import Path
sec = load_tracked_section(Path('.claude/lazy.settings.json'), 'daemon')
print(sec.get('enabled', 'unset'))
"
```

Do NOT ask the user here — Gate 1 (`daemon.enabled`) is owned by `lazy-core.install`. Branch on the read value:

- **`False`** → the daemon is off for this project. Unregister the scan routine that Step 1's seed wrote, so the project carries no dead routine config. The non-daemon parts (settings sections, directories, the CLI allow-pattern) stay installed. State **skipped-daemon-disabled**.

```bash
PYTHONPATH="$COREBIN" python3 -c "
from expert_runtime import unregister_routine
from pathlib import Path
unregister_routine(Path('.'), 'lazy-review.scan')
"
```

- **`unset` or `True`** → proceed; leave the `lazy-review.scan` routine registered as seeded by Step 1. Do NOT re-seed if already present. State **registered** (newly seeded by Step 1) or **already-present** (the routine pre-existed).

## Step 3 — Attach optional routine protocols

If Step 2 unregistered `lazy-review.scan` (outcome **skipped-daemon-disabled**), skip this step with the same outcome — there is no routine to attach protocols to.

Step 1's seed gives `lazy-review.scan` its **mandatory** protocols (`lazy-review.doc-review-protocol` + `lazy-core.markdown-style`). Other plugins may ship references flagged `routine_protocol_candidate: true` that the operator may optionally attach. Delegate the discover → relevance-judge → offer → attach flow to the shared core helper, which leaves the routine config untouched apart from its `protocols` list:

```
Skill(skill: "lazycortex-core:lazy-routine.offer-protocols",
      args: "--routine lazy-review.scan --context 'review of authored markdown documents — prose the writer may want to illustrate'")
```

The helper reads each candidate's frontmatter essence, offers only the ones relevant to that context, and unions the operator's picks into `lazy-review.scan`'s existing `protocols` list (idempotent — already-attached ones are not re-offered). Record its returned outcome.

Outcome: the helper's return value — **attached:<n>** / **declined** / **no-relevant-candidates** — or **skipped-daemon-disabled** when Step 2 removed the routine.

## Step 4 — Surface gitignore suggestions

The runtime writes operator-private state into the repo: the whole `.experts/` tree (job queue, cross-repo trackers, subprocess locks) and tick logs under `.logs/lazy-review/`. Operators typically want both gitignored. This skill MUST NOT write to `.gitignore` itself — instead, print the recommended lines and tell the operator to add them by hand:

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

## Step 6 — Point user at /lazy-review.configure

Tell the operator: *"Settings scaffolded with empty `review.classes` — run `/lazy-review.configure` to register your first class."*

Outcome: `pointed`.

## Report

One line per task in the canonical list with its outcome word.

## Failure modes

- **Step 1 fails with permission error on `.claude/lazy.settings.json`** — operator's shell user can't write there → fix file ownership, re-run.
- **JSON parse error on existing settings** — operator's `.claude/lazy.settings.json` is hand-edited and malformed → fix the JSON manually, re-run.
- **Step 2 cannot resolve the core bin** — `$LAZYCORTEX_PLUGIN_DIRS` is unset and no `lazycortex-core` cache exists → install `lazycortex-core` first (`/lazy-core.install`), then re-run.
