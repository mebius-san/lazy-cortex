---
name: lazy-routine.unregister
description: Remove a named routine from lazy.settings.json. Wraps expert_runtime.unregister_routine. Protects the built-in lazy-expert.pump routine.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Write, AskUserQuestion
---
# Routine Unregister

Remove a named routine from the `lazy-core.runtime` section of `.claude/lazy.settings.json`. Idempotent — unregistering a routine that does not exist is a no-op (INFO, not an error). Protects `lazy-expert.pump` (the built-in pump) from accidental removal unless `--force` is passed.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Built-in protection check`
   - `Step 3 — Verify registration`
   - `Step 4 — Unregister routine`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs:
- `name` (string) — routine name to remove.

Optional inputs:
- `--force` (flag) — required to remove `lazy-expert.pump`.

`name` must be a non-empty string. If absent → abort: "`name` is required."

Outcome: `validated` or `aborted`.

## Step 2 — Built-in protection check

If `name == "lazy-expert.pump"`:
- If `--force` is NOT set → abort: "`lazy-expert.pump` is the built-in expert pump; removing it breaks the experts pipeline. Pass `--force` to override."
- If `--force` IS set → warn: "WARNING: removing `lazy-expert.pump`. Expert jobs will not be processed until the routine is re-registered or `/lazy-core.install` is re-run." Then proceed.

Outcome: `allowed`, `force-override`, or `aborted`.

## Step 3 — Verify registration

Load the current `lazy-core.runtime` section and check if `name` is present in `routines`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys
from pathlib import Path
from lazy_settings import load_section
section = load_section(Path('./.claude/lazy.settings.json'), 'lazy-core.runtime')
routines = section.get('routines', {})
print('present' if sys.argv[1] in routines else 'absent')
" '<name>')
```

If `absent` → print "INFO: routine `<name>` not found — nothing to unregister." and exit with outcome `already-absent`.

Outcome: `present` or `already-absent`.

## Step 4 — Unregister routine

Shell out to `expert_runtime.unregister_routine`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys
from pathlib import Path
from expert_runtime import unregister_routine
unregister_routine(Path('.'), sys.argv[1])
print('unregistered')
" '<name>')
```

Print: "unregistered routine `<name>`."

Outcome: `unregistered` or `error`.

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-routine.unregister)
```

Then `Write` to `.logs/claude/lazy-routine.unregister/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "name=<name> force=<true|false>"
---
```

`# lazy-routine.unregister`

`## Actions`
- Validated inputs
- Built-in protection check
- Verified registration status
- Unregistration result

`## Result` `<success|aborted>` — name=`<name>`, outcome=`<unregistered|already-absent|aborted>`.

## Failure modes

- **"`lazy-expert.pump` is the built-in expert pump"** — attempting to remove the pump without `--force` → pass `--force` only if intentional; expert jobs will stop processing until re-registered.
- **"`.claude/lazy.settings.json` unwritable"** — file permissions issue → verify the file exists and is writable; run `/lazy-core.install` if the file is absent.
