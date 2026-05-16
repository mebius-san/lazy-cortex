---
name: lazy-log.distill
description: "Convert raw commit entries from .logs/commits.jsonl into themed functional prose in ./.logs/changelog.md. Output is theme-first (## <theme>) with one paragraph per day (### YYYY-MM-DD); same-day re-runs rewrite today's paragraph in place; touched theme blocks bump to the top. Throttled to once per 4h via mtime(.logs/changelog.md). Invoke after meaningful commits (see lazy-log.logging rule) or on demand."
tools: Read, Write, Edit, Glob, Bash, TaskCreate, TaskUpdate, TaskList
model: inherit
logging-waiver: "work output IS the changelog rewrite — per-run log duplicates the artifact"
---
# Distill Commits → Changelog

Turn raw commit entries into human-readable functional prose in `./.logs/changelog.md`.

## Execution discipline (MANDATORY — read before any action)

This agent has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read state`
   - `Step 2 — Throttle check`
   - `Step 3 — Determine commits to process`
   - `Step 4 — Read diffs`
   - `Step 5 — Group by theme, then write functional entries`
   - `Step 6 — Update changelog (theme-first, per-day)`
   - `Step 7 — Report`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `skipped-throttle`, `up-to-date`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Optional prompt may include `force` / `manual catch-up` to bypass the 4h throttle. Otherwise the agent reads state from the filesystem.

## Process

### Step 1: Read state

- Read `./.logs/commits.jsonl` (raw commit entries from the `lazy-log.commit-recorder` hook). Each line is a JSON object: `{sha, date, author, branch, subject, body, files, insertions, deletions}`.
- Read `./.logs/changelog.md`. Look for the marker `<!-- lazy-log: last-distilled-sha = <sha> -->` to find the last processed commit. If the marker is missing or says `none`, process from the beginning.
- Capture `mtime(./.logs/changelog.md)` (epoch seconds). If the file doesn't exist, treat mtime as `0`.
- If `commits.jsonl` doesn't exist or is empty, mark every later step `skipped (no-commits)`, jump to Step 7 with `up-to-date — no commits.jsonl`, and proceed to Step 8.

### Step 2: Throttle check

- If the invocation prompt contains `force` or `manual catch-up` (case-insensitive) → mark this step `completed (override)` and continue to Step 3.
- Else if `now - mtime(./.logs/changelog.md) < 4 * 3600` seconds → mark every later step `skipped (throttle)`, jump to Step 7 with `skipped-throttle — last write <Δt> ago`, then Step 8.
- Otherwise → mark `completed (eligible)` and continue.

### Step 3: Determine commits to process

Walk `commits.jsonl` in order. Skip everything up to and including the last-distilled-sha. Collect the rest as "pending commits".

If there are no pending commits → mark later steps `skipped (no-pending)`, jump to Step 7 with `up-to-date`, then Step 8.

### Step 4: Read diffs

For each pending commit, run `git show --stat --format=""  <sha>` to see what files changed and their stats. Do NOT read full diffs unless a commit's subject is unclear — the commit message + file list is usually enough.

### Step 5: Group by theme, then write functional entries

First **group** pending commits by theme. Then write a **1-3 sentence** paragraph per theme focused on what changed from the **user's perspective**.

**Theme extraction — in this order:**

1. **Conventional-commits scope.** Parse `^[a-z]+\(([^)]+)\):` from each commit subject (e.g. `feat(auth): add OAuth` → scope `auth`). Commits sharing the same scope form one theme.
2. **Subject keyword clustering** (fallback when scope is absent). Cluster by recurring nouns/verbs in the subjects (e.g. "login", "migration", "payments"). Use judgment — do not force grouping if commits are unrelated; leave them as singleton themes.

Do **not** group by file-path commonality — it's noisy and misleads when one commit touches many top-level dirs.

**Per-theme writing:**

- Theme label = the conventional-commits scope verbatim if available (e.g. `auth`, `lazy-core.doctor`), otherwise a short keyword phrase derived from the subjects (e.g. `login flow`).
- One paragraph (1-3 sentences) per theme covering all of today's contributing commits, with SHAs in backticks at the end: `` (`a2739ff`, `b3320cc`, `c89aa12`) ``.
- Singleton themes are fine — one commit, one paragraph.
- For commits whose subject already reads as functional prose, paraphrase minimally.

**Internal work:**

- Commits whose subjects are pure `chore:` / `refactor:` / `style:` / `test:` (no user-visible change) merge into a single `(internal)` theme, kept terse.
- If a feature/fix theme contains some refactor-tagged commits that *do* contribute to the user-visible change, keep them in the feature theme — don't split.

**Examples:**

Good:
```
Added MCP-permissions completeness check, plugin version currency check; doctor now flags unscoped rules and skips unversioned plugins. (`d6a41f0`, `de3f822`, `b139ecb`)
```

Bad (too technical):
```
Renamed 5 files, updated 11 cross-references, fixed 2 log path references. (`d6a41f0`, `de3f822`, `b139ecb`)
```

Bad (forced grouping under a generic theme):
```
### misc
Doctor MCP check; auth login fix; new payments endpoint. (`a1`, `b2`, `c3`)
```
(unrelated commits — leave as three singleton themes instead)

### Step 6: Update changelog (theme-first, per-day)

The changelog is **theme-first**: top-level `##` is the theme, second-level `###` is the date the paragraph covers.

```markdown
# Changelog

<intro>

<!-- lazy-log: last-distilled-sha = <sha> -->

## <theme A>            ← bumped to top when touched this run

### 2026-04-28
<paragraph for theme A on this date, with SHAs>

### 2026-04-26
<earlier paragraph for the same theme, untouched>

## <theme B>

### 2026-04-27
<paragraph>
```

Get today's date in UTC: `date -u +%Y-%m-%d`.

For each theme touched in this run, in order from oldest contributing SHA to newest (so the freshest theme ends up bumped highest):

1. **If `## <theme>` block exists in the file:**
   - **If `### <today>` exists under it** → rewrite that day's paragraph in place, merging today's new commits into it (one paragraph for the whole day; SHAs accumulated).
   - **Else** → insert a new `### <today>` paragraph at the top of the theme block (above earlier dates).
   - **Then bump the entire `## <theme>` block** (header + all its date paragraphs) to the top of the file — directly under the `last-distilled-sha` marker, above all other theme blocks.
2. **If the theme block does not exist** → create a new `## <theme>` block at the top of the file (under the marker) with a `### <today>` paragraph as its only content.

Themes not touched this run stay in place; their relative order is preserved.

**Update the `last-distilled-sha` marker** to the newest SHA just processed.

**Pre-format compatibility:** if the file already contains older entries that don't follow this theme-first format, leave them where they are. Only new content uses the new format.

### Step 7: Report

One line per canonical task showing its outcome. The Report step is a structural verifier — every step from the canonical list must appear, even when skipped:

- `Step 1 — Read state: <ok | no-commits.jsonl>`
- `Step 2 — Throttle check: <eligible | override | skipped-throttle (Δt=<…>)>`
- `Step 3 — Determine commits to process: <N pending | up-to-date | skipped>`
- `Step 4 — Read diffs: <N diffs read | skipped>`
- `Step 5 — Group by theme: <K themes | skipped>`
- `Step 6 — Update changelog: <K themes touched, M new days, last-distilled-sha <old> → <new> | skipped>`
- `Step 7 — Report: rendered`
- `Step 8 — Log the run: written to <path>`

Also tell the user the path to the updated file (`.logs/changelog.md`).

## Guidelines

- **Today's paragraph is rewritable.** The same-day-rewrite rule means a same-day re-run merges new commits into today's paragraph rather than appending a fragment. Days other than today are append-only.
- **Never auto-commit the changelog** — `.logs/` is gitignored anyway, but in case the user later untracks: don't `git add` or commit on their behalf.
- **Stay short** — this is a changelog, not a blog post. If a commit really needs more detail, put the SHA and let the reader `git show` it.

## Logging

Log to `./.logs/claude/lazy-log.distill/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` in frontmatter). Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
