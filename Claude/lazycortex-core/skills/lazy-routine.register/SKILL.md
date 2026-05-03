---
name: lazy-routine.register
description: Register a named routine in lazy.settings.json. Wraps expert_runtime.register_routine. Used by plugin install skills.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Write, AskUserQuestion
---
# Routine Register

Register a named routine in the `lazy-core.runtime` section of `.claude/lazy.settings.json`. Enforces `<plugin>.<verb>` naming. Refuses to overwrite an existing routine unless `--force` is set.

Used by plugin install skills to register their scheduled routines (e.g. `lazy-review.install` registers `lazy-review.tick`).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Check for existing registration`
   - `Step 3 — Register routine`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs:
- `name` (string) — routine name.
- `command` (list of strings) — command to execute.
- `interval_sec` (int) — polling interval in seconds.

Optional inputs:
- `timeout_sec` (int) — per-run timeout; omit to use the daemon default.
- `--force` (flag) — allow overwriting an existing registration.

Pre-flight checks:
1. `name` must match `<plugin>.<verb>` pattern (contains exactly one dot, both parts non-empty). If it does not → abort: "routine names must be `<plugin>.<verb>` format (e.g. `lazy-review.tick`). Got: `<name>`."
2. `command` must be a non-empty list.
3. `interval_sec` must be a positive integer.

Outcome: `validated` or `aborted`.

## Step 2 — Check for existing registration

Load the current `lazy-core.runtime` section and check if `name` is already in `routines`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from pathlib import Path
from lazy_settings import load_section
section = load_section(Path('./.claude/lazy.settings.json'), 'lazy-core.runtime')
routines = section.get('routines', {})
print('present' if sys.argv[1] in routines else 'absent')
" '<name>')
```

If `present` and `--force` not set → abort: "routine `<name>` already registered. Use `--force` to overwrite, or call `/lazy-routine.unregister` first."

If `present` and `--force` is set → proceed (will overwrite).

Outcome: `absent`, `overwrite-forced`, or `aborted`.

## Step 3 — Register routine

Shell out to `expert_runtime.register_routine`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys, json
from pathlib import Path
from expert_runtime import register_routine
name = sys.argv[1]
command = json.loads(sys.argv[2])
interval_sec = int(sys.argv[3])
timeout_sec = int(sys.argv[4]) if sys.argv[4] else None
register_routine(Path('.'), name, command, interval_sec, timeout_sec=timeout_sec)
print('registered')
" '<name>' '<command-json>' '<interval_sec>' '<timeout_sec|>')
```

Outcome: `registered` or `error`.

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print: "registered routine `<name>` (interval=<interval_sec>s, command=<command>)".

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-routine.register)
```

Then `Write` to `.logs/claude/lazy-routine.register/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "name=<name> interval_sec=<interval_sec>"
---
```

`# lazy-routine.register`

`## Actions`
- Validated inputs
- Checked existing registration
- Registered routine in lazy.settings.json

`## Result`
`<success|failure>` — name=`<name>`, interval=`<interval_sec>`s.

## Failure modes

- **"routine names must be `<plugin>.<verb>` format"** — name does not contain a dot or has an empty part → rename to follow the convention (e.g. `lazy-review.tick`).
- **"routine `<name>` already registered"** — a routine with this name exists in settings → call `/lazy-routine.unregister` first, or retry with `--force`.
- **"`.claude/lazy.settings.json` unwritable"** — file permissions or directory absent → check that `/lazy-core.install` has bootstrapped the file and it is not read-only.
