---
name: lazy-memory.reflect
description: Dispatch a single `kind=reflect` job for one persona-marked expert. The expert reviews recent `.logs/claude/<self>/*.md` runs + current `.memory/<self>/*.md` and consolidates via `lazy-memory.write`. Refuses non-persona-marked experts.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write
---
# Memory reflect

Dispatch a `kind=reflect` job to one expert. The expert receives recent run logs and current memory as input, applies its memory aspect's obligations, and returns `outcome=edited` (notes changed) or `outcome=empty` (nothing to consolidate).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Confirm expert is persona-marked`
   - `Step 3 — Dispatch reflect job`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.**

## Step 1 — Validate inputs

Required input:
- `expert` (string) — a key in `.claude/lazy.settings.json[experts]`.

Optional input:
- `days` (int, default 30) — how far back to pull `.logs/claude/<expert>/*.md` files into `source[]`.

Outcome: `validated` or `aborted`.

## Step 2 — Confirm expert is persona-marked

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_section
import sys
experts = load_section(Path('.claude/lazy.settings.json'), 'experts')
entry = experts.get(sys.argv[1], {})
aspects = entry.get('aspects') or []
print('ok' if 'lazycortex-core:lazy-memory.persona-aspect' in aspects else 'not-persona')
" '<expert>')
```

If output is `not-persona`, abort: "`<expert>` is not marked persona; run `/lazy-memory.mark-persona <expert>`."

Outcome: `persona-confirmed` or `aborted-not-persona`.

## Step 3 — Dispatch reflect job

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, os, time
from pathlib import Path
from expert_runtime import dispatch_job
from routine_types import _write_job_config
from lazy_settings import load_section
import sys
repo = Path('.')
expert = sys.argv[1]
days = int(sys.argv[2]) if len(sys.argv) > 2 else 30

# Pull source: recent run logs + every memory note for this expert
cutoff = time.time() - days * 86400
sources = []
log_root = repo / '.logs/claude' / expert
if log_root.is_dir():
    for p in sorted(log_root.iterdir()):
        if p.is_file() and p.suffix == '.md' and p.stat().st_mtime >= cutoff:
            sources.append({'path': str(p), 'description': 'recent run log'})
mem_root = repo / '.memory' / expert
if mem_root.is_dir():
    for p in sorted(mem_root.iterdir()):
        if p.is_file() and p.suffix == '.md':
            sources.append({'path': str(p), 'description': 'current memory note'})

payload = {
    'kind': 'reflect',
    'role': 'reflect',
    'request': 'Consolidate recent runs into memory per lazy-memory.persona-aspect §Obligations. '
               'On finding patterns worth retaining, call /lazy-memory.write. On finding nothing '
               'new, return outcome=empty.',
    'source': sources,
}

experts = load_section(repo / '.claude/lazy.settings.json', 'experts')
entry = experts[expert]
aspects = entry.get('aspects') or []
arguments = entry.get('arguments') or {}
# Protocols default to none for reflect — the aspect itself carries obligations.
protocols = []

result = dispatch_job(repo, expert, payload)
_write_job_config(result['queue_path'], expert, entry, protocols, aspects, arguments)
print(json.dumps(result))
" '<expert>' '<days>')
```

Parse `{job_id, queue_path}`.

Outcome: `dispatched` or `error`.

## Step 4 — Report

One line per task. Print:

```
expert:    <expert>
job_id:    <job_id>
queue_path: <queue_path>
source_count: <N>
```

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-memory.reflect)
```

Write to `.logs/claude/lazy-memory.reflect/<UTC-timestamp>.md` per the logging rule.

## Failure modes

- **"`<expert>` is not marked persona"** — opt the expert in via `/lazy-memory.mark-persona <expert>` and re-run.
- **`<expert>` not in `lazy.settings.json[experts]`** — the expert is unknown; verify the name or register via `/lazy-core.install`.
- **No source files found** — the expert has no recent run logs and no existing memory notes. The reflect job will be a no-op; consider skipping until the expert has run jobs to consolidate.
