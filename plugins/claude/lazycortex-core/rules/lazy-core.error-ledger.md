---
description: Failures of a routine, a daemon, or the agents and skills a routine runs reach the lazycortex-core error ledger and nothing else — signal failure, report in-band failures through the core CLI, keep causes stable, and build no failure channel of your own. Loads when editing agents, skills, commands, or the routine registry.
paths:
  - ".claude/agents/**"
  - ".claude/skills/**"
  - ".claude/commands/**"
  - ".claude/lazy.settings.json"
---
# Error ledger

The lazycortex-core error ledger is the one place a failure of the autonomous runtime is recorded; `error-list`, the metrics and the alerts all read it. This rule applies to every routine registered in `.claude/lazy.settings.json`, to every daemon a project runs beside the runtime, and to every agent, skill and command a routine runs.

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

## 1. A failure is signalled, never described

A routine that failed exits non-zero; the daemon records it as a `routine_error`. An expert job that failed ends with a non-zero exit or a `response.json` whose `outcome` is `error`; the daemon records it as a `job_error`. An agent or skill that describes a failure in its report or a file and then finishes the job as done has hidden it: the ledger never sees it.

## 2. In-band failures go through `error-record`

A failure an exit code cannot express — a skipped item, a partial batch, a step that failed while the rest went through — is reported with the core CLI, from the repository root:

```
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> error-record --kind plugin_error --cause <stable-id> \
  --incident <key> --severity error|warn [--detail "<one line>"]
```

A later success closes the incident with `error-record --incident <key> --resolve`.

## 3. The cause is stable, the detail varies

`--cause` is a short identifier defined once, as a constant in the reporting code. It becomes a metrics label and an alert grouping key, so it never carries an exception text, a path, or any value that changes between failures; those go into `--detail`. `--incident` is a stable key: the same condition always produces the same key, and two conditions never share one.

## 4. Reporting never breaks the work

`error-record` is fire-and-forget. The caller does not branch on its result, and a failed report never aborts the work it reports on.

## 5. The ledger is the only failure channel

No routine, daemon, agent or skill builds a failure mechanism of its own: no private error file, no error sidecar, no stderr line standing in for a report, no alerting of its own. The ledger's metrics and alerts carry every failure from the one place.

## Enforcement

No audit check proves these invariants; a review of the routine, agent or skill holds the author to them.
