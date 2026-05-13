---
name: lazy-memory.mark-persona
description: Opt one expert into the memory subsystem by appending `lazycortex-core:lazy-memory.persona-aspect` to its `aspects[]` in `lazy.settings.json[experts][<expert>]`. Idempotent — re-running on an already-marked expert is a no-op.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion
---
# Mark expert as persona

Opt one expert into the memory subsystem. After running this skill, the expert may write under `.memory/<self>/` via `lazy-memory.write`, must consult `.memory/<self>/.tags/*.md` before primary work, and must handle `kind=reflect` jobs per `lazy-memory.persona-aspect.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Read expert entry`
   - `Step 3 — Append persona aspect`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.**

## Step 1 — Validate inputs

Required input from the caller:
- `expert` (string) — must be a key in `.claude/lazy.settings.json[experts]` (excluding `_version`).

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_section
experts = load_section(Path('.claude/lazy.settings.json'), 'experts')
import sys
name = sys.argv[1]
if name == '_version' or name not in experts:
    print('absent'); sys.exit(0)
print('present')
" '<expert>')
```

If output is `absent`, abort: "`<expert>` is not registered in `lazy.settings.json[experts]`."

Outcome: `validated` or `aborted-unknown-expert`.

## Step 2 — Read expert entry

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json
from pathlib import Path
from lazy_settings import load_section
experts = load_section(Path('.claude/lazy.settings.json'), 'experts')
import sys
entry = experts.get(sys.argv[1], {})
print(json.dumps({'aspects': entry.get('aspects', [])}))
" '<expert>')
```

Parse the JSON. If `lazycortex-core:lazy-memory.persona-aspect` is already in `aspects`, state outcome `already-marked` and skip Step 3 (Report still runs).

Outcome: `read` or `already-marked`.

## Step 3 — Append persona aspect

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_section, save_section
import sys
name = sys.argv[1]
section = load_section(Path('.claude/lazy.settings.json'), 'experts')
entry = section.get(name, {})
aspects = list(entry.get('aspects', []))
ref = 'lazycortex-core:lazy-memory.persona-aspect'
if ref not in aspects:
    aspects.append(ref)
entry['aspects'] = aspects
section[name] = entry
save_section(Path('.claude/lazy.settings.json'), 'experts', section)
print('marked')
" '<expert>')
```

Outcome: `marked`.

## Step 4 — Report

One line per task. Print to the caller:

```
expert:        <name>
aspects_after: <comma list>
```

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-memory.mark-persona)
```

Write to `.logs/claude/lazy-memory.mark-persona/<UTC-timestamp>.md` per the logging rule.

## Failure modes

- **"`<expert>` is not registered in `lazy.settings.json[experts]`"** — typo or the expert was never registered. Verify the name and re-run, or register the expert via `/lazy-core.install` first.
