---
name: lazy-memory.write
description: "Atomic memory-note writer for persona-marked experts. Writes one note under `.memory/<expert>/`, regenerates touched `.tags/` files (local + global), optionally drops consolidated log files. The only blessed writer of .memory/."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write
---
# Memory write

Write one memory note for an expert. Validates frontmatter, picks a non-colliding slug, regenerates touched `.tags/` files (local + global), optionally drops `--consolidate` log paths. Caller (or the expert that invoked the skill) commits.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Write note via worker`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it".
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above.

## Step 1 — Validate inputs

Required inputs from the caller:
- `expert` (string) — the expert name; must be a key in `lazy.settings.json[experts]` and must carry `lazycortex-core:lazy-memory.persona-aspect` in its `aspects[]`. If not persona-marked, abort with: "`<expert>` is not marked persona; run `/lazy-memory.mark-persona <expert>` first."
- `body` (markdown string with frontmatter) — the note text; must declare `title`, `tags` (every entry prefixed `memory/`), `type` (one of `persona | rule | example | warning | fact`), `summary`.

Optional inputs:
- `slug` (string) — override the auto-derived slug.
- `consolidate` (list of paths) — files to delete after a successful write. Every path MUST be under `.logs/` or `.memory/`; out-of-scope paths reject the entire op.

Outcome: `validated` or `aborted`.

## Step 2 — Write note via worker

Shell out to the worker:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-memory.write/bin/write.py <expert> [--slug <slug>] [--consolidate <path>]... <<EOF
<body>
EOF
)
```

Capture stdout (the resolved note path) or stderr (a `WriteError` line of the form `frontmatter-invalid: …` / `consolidate-out-of-scope: …` / `consolidate-io-error: …`).

Outcome: `written` (stdout has a path) or `error:<category>` (stderr has a WriteError).

## Step 3 — Report

One line per task. Print to the caller:

```
note_path:   <path>
touched_tags: <comma-list of topic names whose .tags/ files were regenerated>
consolidated: <count of dropped paths>
```

## Step 4 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-memory.write)
```

Write to `.logs/claude/lazy-memory.write/<UTC-timestamp>.md` per the logging rule.

## Failure modes

- **"`<expert>` is not marked persona"** — the expert entry's `aspects[]` does not contain `lazycortex-core:lazy-memory.persona-aspect` → run `/lazy-memory.mark-persona <expert>` to opt the expert in.
- **"frontmatter-invalid: missing required field: summary"** (or `title` / `tags` / `type`) → add the missing field to the note's frontmatter.
- **"frontmatter-invalid: tag must be prefixed `memory/`"** → every tag entry must read `memory/<topic>` (e.g. `memory/auth`).
- **"consolidate-out-of-scope: <path>"** → `--consolidate` only accepts paths under `.logs/` or `.memory/`. Move the file or remove it from the consolidate list.
- **"consolidate-target-missing: <path>"** → a non-fatal warning; the note still writes. Verify the path was correct or remove it from the consolidate list.
