---
name: lazy-spec.upstream-run
description: "Run when the operator asks to fetch upstream sources now, check what changed in a configured `spec.upstream` source, or force a mirror/detect pass without waiting for the next `lazy-spec.upstream-tick` schedule tick. Manual, no-daemon counterpart of that routine — same underlying primitive, same result."
---
# Upstream Run

Run one full upstream tick over every source configured under the `spec` settings section's `upstream` sub-section, and report what it found. This skill is the operator-invoked entry point; `/lazy-spec.install` registers a `lazy-spec.upstream-tick` schedule routine that calls the same underlying primitive (`lazycortex-specs upstream-tick`) on a cadence — running this skill by hand and waiting for the routine produce identical results. One tick runs all three lifecycle phases: it mirrors and diffs each configured unit and derives its status (hanging an operator checkbox on `new`/`drifted`), opens a body-only request for any unit whose checkbox was ticked in a prior commit, and unfreezes an `in-review` unit once its linked request's review has concluded. It never dispatches an expert job itself — a landed request enters the standard review pipeline, which routes and dispatches on its own schedule, not this pass's.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical list:
   - `Step 1 — Run the fetch/detect pass`
   - `Step 2 — Render the summary`
   - `Step 3 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not finalise until `TaskList` shows every prior task `completed`.**

## Step 1 — Run the fetch/detect pass

Run `Bash(lazycortex-specs upstream-tick)`. It prints exactly one JSON object to stdout —
`{"units_ordered": <n>, "units_visited": <n>, "units_touched": <n>, "statuses": {"<status>": <n>, ...}, "errors": [<message>, ...]}`
— and always exits `0`; a per-source fetch failure is isolated into `errors`, never a process
failure, so one unreachable source does not abort the others. Parse the JSON.

Outcome: `ran:<units_touched>/<units_ordered>`.

## Step 2 — Render the summary

Render the parsed result:

| Field | Value |
|---|---|
| Units considered | `<units_ordered>` |
| Units visited this pass | `<units_visited>` |
| Units with new work | `<units_touched>` |

Below the table, list `statuses` as one line per status token present (`new: <n>`, `drifted:
<n>`, `processed: <n>`, `orphaned: <n>`, `invalid: <n>`, `excluded: <n>`, `postponed: <n>`,
`in-review: <n>`).

- When `units_touched > 0`, tell the operator which units now carry an operator checkbox: any
  unit whose status this pass is `new` or `drifted` has a `Take into work` / `Process update`
  checkbox waiting on its own folder-note under `upstream/<repo-key>/<mount>/<unit-path>/`.
  Ticking it and re-running this pass (or waiting for the next scheduled tick) opens a
  body-only request under `requests/` and freezes the unit onto `in-review`.
- When `units_visited < units_ordered`, note that this pass hit its `max_units_per_tick`
  budget and stopped partway; the next run (manual or scheduled) resumes from where this one
  left off, not from the beginning.
- When `errors` is non-empty, list each message below the table. That source's units were left
  exactly as the last successful fetch found them this pass; the other configured sources still
  ran normally.
- When `units_ordered` is `0`, say plainly that no `spec.upstream` source is configured yet (or
  none has landed a matching unit directory) — point at `lazy-spec.config-protocol.md` Part 4 for the
  config shape.

Outcome: `rendered`.

## Step 3 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to
`./.logs/claude/lazy-spec.upstream-run/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with
`Bash(mkdir -p ./.logs/claude/lazy-spec.upstream-run)`, then `Write` the file — never chain with
`&&`. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input: none`.
Body: `# lazy-spec.upstream-run` heading, `## Actions` (the parsed counts), `## Result` (the
rendered table plus any budget/error notes).

Outcome: `logged`.

## Failure modes

- **Every count is `0`** — no `<repo-key>` entry exists under `spec.upstream` in
  `lazy.settings.json` yet, or a configured mount's `units` glob matches nothing in the
  source's current tree. Add a source entry per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`
  Part 4, or widen the mount's `units` glob.
- **An entry shows up in `errors`** — that source's `url`/`branch` was unreachable, or an
  existing clone's `origin` no longer matches the configured `url` (the clone is never
  re-pointed automatically — fix the config or the clone by hand). The rest of the configured
  sources still ran normally this pass.
- **A unit stays `new` forever with no checkbox visible** — check its own folder-note's
  `# Actions` section directly; a unit whose mirrored root note (`source/<unit>.md`) carries
  `spec_draft: true` is deliberately gated and never gets a checkbox until the upstream design
  itself drops the draft flag.

## Key Rules

- **Non-interactive.** No `AskUserQuestion` anywhere — the primitive is shared with the
  unattended `lazy-spec.upstream-tick` daemon routine, so the manual path behaves identically
  without operator input.
- **Runs the full tick, never dispatches an expert.** This skill invokes all three lifecycle
  phases (mirror/detect, request, unfreeze) and renders the result; routing a landed request to
  an expert job is the standard review pipeline's own job, not this pass's.
- **Idempotent.** Re-running with nothing changed upstream reports every previously-processed
  unit as `processed` again; the exit code is always `0`.
