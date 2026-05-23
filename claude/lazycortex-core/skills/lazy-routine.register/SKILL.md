---
name: lazy-routine.register
description: Register a named routine in lazy.settings.json. Type-aware wizard (subprocess / inbox / schedule / git / md-scan). Wraps expert_runtime.register_routine with closed-set validation. Used by plugin install skills.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(git check-ignore *), Write, AskUserQuestion
dirty-tree-waiver: "registers a routine in lazy.settings.json — operator commits explicitly to coordinate with sibling routines / install steps"
---
# Routine Register

Register a named routine in the `lazy-core.runtime` section of `.claude/lazy.settings.json`. Enforces `<plugin>.<verb>` naming. Refuses to overwrite an existing routine unless `--force` is set. Validates the per-type schema via `routine_types.validate_routine_entry`.

Used by plugin install skills (programmatic call) and by humans via `/lazy-routine.register` (wizard mode).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Collect + validate inputs`
   - `Step 2 — Check for existing registration`
   - `Step 3 — Register routine`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Collect + validate inputs

Required: `name` (string, `<plugin>.<verb>` pattern).

The remaining fields depend on the routine **type**. Allowed types: `subprocess` (default), `inbox`, `schedule`, `git`, `md-scan`.

### 1a. Resolve the type

If the caller passed a `cfg` dict, take `cfg.get("type", "subprocess")` and skip to 1c with the dict.

In wizard mode (no `cfg`), ask via `AskUserQuestion`:

> Which routine type?
> - subprocess — periodic command (default)
> - inbox — scan a dir, fire once per file (job-queue moves the file; command leaves it in place)
> - schedule — cron-driven; one fire per cron boundary
> - git — watch <remote>/<branch>; fire once per item
> - md-scan — scan markdown files matching globs, filter by frontmatter; fire in-place (no file move)

### 1b. Collect type-specific fields

Per type, ask only the required + commonly-needed optional fields. Schemas live in `claude/lazycortex-core/bin/routine_types.py::SCHEMAS`. Wizard prompts:

Every type ends with the same EITHER/OR question — `command` (list) OR `expert` (name) + `request` (JSON-shaped block). The validator enforces exactly-one; the wizard asks the question once at the end of the type-specific fields.

- **subprocess** — `interval_sec` (int), `timeout_sec?` (int). Then EITHER `command` OR `expert` + `request`.
- **inbox** — `inbox_dir` (path relative to repo), `interval_sec`, `timeout_sec?`. Then EITHER `command` OR `expert` + `request`. With `expert + request`: files are moved into job staging; with `command`: files stay in the inbox until the consumer removes them.
- **schedule** — `cron` (5-field expression). Then EITHER `command` OR `expert` + `request`.
- **git** — `repo_dir?` (default `.`), `remote?` (default `origin`), `branch`, `watch` (one of `new_commits` / `new_files` / `changed_files` / `deleted_files` / `renamed_files`), `path_filter?`, `interval_sec`. Then EITHER `command` OR `expert` + `request`.
- **md-scan** — `paths` (list of vault-relative globs, e.g. `["requests/*.md"]`), `frontmatter_filter` (dict of `key → value-or-list-of-values`; `null` matches missing keys, e.g. `{"request_status": [null, "draft"]}`), `interval_sec`, `timeout_sec?`. Then EITHER `command` OR `expert` + `request`. No file move — the consumer gets the absolute path of each match and edits in place.

Build a single `cfg` dict carrying `type` + the collected fields.

### 1c. Pre-flight validation

1. `name` matches `<plugin>.<verb>` (exactly one dot, both parts non-empty). Else abort: "routine names must be `<plugin>.<verb>` format. Got: `<name>`."
2. Call `validate_routine_entry(name, cfg)` to enforce the per-type schema. On `RoutineConfigError`, abort with the message verbatim.
3. **Working-area gitignore check** — for `inbox` routines, run `git check-ignore -q <inbox_dir>`. Exit 0 = ignored. Exit 1 = tracked → ask via `AskUserQuestion`: > `<inbox_dir>` is not gitignored. Inbox routines move tracked files between iterations, which dirties the working tree and triggers the daemon's halt protection. > - Add `<inbox_dir>/` to `.gitignore` now (recommended) > - Continue anyway — I will commit moves manually > - Abort registration

   On "Add" → append to `.gitignore`; do not auto-commit (operator commits when ready). On "Abort" → outcome `aborted`.

Outcome: `validated`, `aborted`, or `gitignore-warned`.

## Step 2 — Check for existing registration

Load the current `lazy-core.runtime` section and check if `name` is already in `routines`:

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

If `present` and `--force` not set → abort: "routine `<name>` already registered. Use `--force` to overwrite, or call `/lazy-routine.unregister` first."

If `present` and `--force` is set → proceed (will overwrite).

Outcome: `absent`, `overwrite-forced`, or `aborted`.

## Step 3 — Register routine

Pass the typed cfg dict to `expert_runtime.register_routine`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys, json
from pathlib import Path
from expert_runtime import register_routine
name = sys.argv[1]
cfg  = json.loads(sys.argv[2])
register_routine(Path('.'), name, cfg)
print('registered')
" '<name>' '<cfg-json>')
```

`register_routine` validates again before write; if anything slipped past Step 1, it raises `RoutineConfigError` here.

Outcome: `registered` or `error`.

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print: "registered routine `<name>` (type=<type>, <key params>)".

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
input: "name=<name> type=<type>"
---
```

`# lazy-routine.register`

`## Actions`
- Collected + validated inputs (type=`<type>`)
- Checked existing registration
- Registered routine in lazy.settings.json

`## Result` `<success|failure>` — name=`<name>`, type=`<type>`.

## Failure modes

- **"routine names must be `<plugin>.<verb>` format"** — name does not contain a dot or has an empty part → rename to follow the convention (e.g. `lazy-review.tick`).
- **"routine `<name>` already registered"** — a routine with this name exists in settings → call `/lazy-routine.unregister` first, or retry with `--force`.
- **"unknown type 'X'"** — `cfg.type` is not one of `subprocess`/`inbox`/`schedule`/`git`/`md-scan` → fix the type or upgrade `lazycortex-core` to a version that supports it.
- **"missing required field(s): […]"** — per-type schema rejected the input → fill the missing fields and retry.
- **"`<inbox_dir>` is not gitignored"** — inbox-type routine working area is tracked → add it to `.gitignore` (the wizard offers this) or restructure the routine to operate in a gitignored path.
- **"`.claude/lazy.settings.json` unwritable"** — file permissions or directory absent → check that `/lazy-core.install` has bootstrapped the file and it is not read-only.
