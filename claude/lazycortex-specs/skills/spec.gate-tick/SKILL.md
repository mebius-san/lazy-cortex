---
name: spec.gate-tick
description: Script-only md-scan worker that advances one asset's gates per tick — auto-flips the next derived gate, drops a readiness callout for the next human-signal gate, or withdraws a stale readiness callout. Dispatched per-file by the daemon; performs no Claude calls.
execution-discipline-waiver: "Documents a pure script (bin/gate_tick.py) dispatched by the daemon — there is no Claude-side execution to discipline."
logging-waiver: "script-only md-scan worker invoked per-file by the daemon; the routine's daemon log records execution"
---
# Gate Tick

`bin/gate_tick.py` is a pure, script-only worker — it makes **no Claude calls** and emits **no task checkboxes**. It is invoked once per matched status folder-note by the `spec.gate-tick` `md-scan` routine registered in `lazy.settings.json[routines]` with `command: ["lazycortex-specs", "gate-tick"]`. The daemon globs the matching folder-notes, applies the routine's frontmatter filter, and runs the worker as a blocking subprocess per match.

This file documents the worker for operators and maintainers; there is no interactive surface. The full gate model — the five flat booleans, the S0..S5 ladder, the precondition table, and the derived-vs-human-signal distinction that determines what the worker does — lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`.

## What it does per tick

For each matched asset folder-note, the worker finds the lowest gate that is currently false and whose precondition holds, then advances the asset one notch:

- **Next gate is derived** (`spec_design_done` / `spec_plan_done`) → auto-flip it in-process via the `flip_gate` primitive with `--auto`, so the callout / history / log side effects are produced exactly once by their one owner.
- **Next gate is human-signal** (`spec_develop_done` / `spec_tests_passing` / `spec_released`) → drop or refresh a `> [!ready]` callout in `## Gates` telling the operator how to flip it by hand (idempotent — appended once).
- **A previously-dropped `[!ready]` whose precondition has since regressed** → rewrite it in place as a `> [!info] readiness withdrawn — <gate> precondition no longer met` callout.

When no gate is both false and ready, the tick is a no-op.

## CLI

```
lazycortex-specs gate-tick <asset_note> [--today YYYY-MM-DD]
```

`--today` overrides the date stamped into callouts (used by tests). Normal runs read the current UTC date.

## Run Log

This worker is exempt from `.claude/rules/lazy-log.logging.md` per the `logging-waiver` in frontmatter — it is a script-only md-scan worker invoked per-file by the daemon, and the routine's daemon log records each execution. The `flip_gate` primitive it calls writes its own log under `.logs/claude/spec.flip-gate/` whenever it performs an auto-flip.
