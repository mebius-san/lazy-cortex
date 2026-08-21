---
name: lazy-spec.gate-tick
description: "Dispatched per status folder-note by the daemon's `lazy-spec.gate-tick` md-scan routine to poll one asset's active job and structurally check its folder-note; not for direct use — it is a pure script and makes no Claude calls. Read it when asked why an active-job marker was cleared, why an asset went `spec_halted` from a dead job, or what a `note-check` violation folded into a tick result means. For why a launch checkbox appeared, disappeared, or dispatched a job — or why a gate flipped at all — see `lazy-spec.coordination-playbook.md`; none of that is this worker's decision anymore."
execution-discipline-waiver: "Documents a pure script (bin/gate_tick.py) dispatched by the daemon — there is no Claude-side execution to discipline."
logging-waiver: "script-only md-scan worker invoked per-file by the daemon; the routine's daemon log records execution"
---
# Gate Tick

`bin/gate_tick.py` is a pure, script-only worker — it makes **no Claude calls** and decides nothing. It is invoked once per matched status folder-note by the `lazy-spec.gate-tick` `md-scan` routine registered in `lazy.settings.json[routines]` with `command: ["lazycortex-specs", "gate-tick"]`. The daemon globs the matching folder-notes, applies the routine's frontmatter filter, and runs the worker as a blocking subprocess per match.

**What moved out of this file.** Every sequencing decision this worker used to make — sibling-doc stage promotion, gate readiness, downward reconciliation, the launch-checkbox ladder (hang / remove / dispatch), and change-cascade dispatch — now belongs to `spec.coordinator`, per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`. This worker keeps only the two mechanical concerns no LLM needs to be woken for. The gate model itself (the five flat booleans, the S0..S5 ladder, the shapes the coordinator's decisions produce) still lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md` — read it for what a healthy gate state looks like; read the playbook for who decides to reach it.

## What it does per tick

**Active-job polling.** When the runtime sidecar tracks an `active_job` for the asset, the worker checks that job's bundle for a terminal marker (`DONE` / `DEAD` / `CANCELLED`) before doing anything else. No marker yet → falls through to the structural check below untouched, and so does an asset that tracks no job at all.

- `DONE` clears the key and logs it; for `Start implementation` / `Start testing` specifically, it additionally opens `lazycortex-review` on the report sibling (`code-report.md` / `test-report.md`) the job just wrote — best-effort, degrading to a silent skip on any failure (report not yet written, review CLI unresolvable, non-zero exit), since the `DONE` marker is already applied regardless.
- `CANCELLED` clears the key and logs it; no further follow-up.
- `DEAD` clears the key, sets `spec_halted: true`, and appends a persistent `[!failure]` callout to `# Gates` — un-halting is a manual operator act, out of scope for this worker. It does NOT drop any launch checkbox; the coordinator owns the checkbox layer entirely and reconciles it on its next wake.

**Structural note-check.** The worker subprocesses `note-check` on the same folder-note and folds its violations (an unrecognized or mistyped frontmatter key, a missing or misordered required section from the canonical roster) into the tick's own result — read-only. Repairing a violation is `spec.coordinator`'s job, through its pen for body sections and `note-set-key` for frontmatter; this worker never fixes anything itself.

A no-op tick (no terminal marker yet, note structurally clean) reports `{"action": "noop"}`. The `lazy-spec.coordinator-watch` routine (`coordinator_dispatch.py`) is this worker's own sibling routine, not a step of this tick — it wakes `spec.coordinator` on its own schedule, independently of when this worker runs.

## CLI

```
lazycortex-specs gate-tick <asset_note> [--today YYYY-MM-DD]
```

`--today` overrides the date stamped into callouts (used by tests). Normal runs read the current UTC date.

## Run Log

This worker is exempt from `.claude/rules/lazy-log.logging.md` per the `logging-waiver` in frontmatter — it is a script-only md-scan worker invoked per-file by the daemon, and the routine's daemon log records each execution. The `lazycortex-review` subprocess it opens on a `DONE` report sibling writes its own log, per `lazycortex-review`'s own contract.
