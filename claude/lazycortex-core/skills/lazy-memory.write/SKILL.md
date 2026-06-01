---
name: lazy-memory.write
description: "Atomic memory-note writer for persona-marked experts. Writes one note under `.memory/<expert>/`, regenerates touched `.tags/` files (local + global), optionally drops consolidated log files, then commits the change atomically under the memory-bot identity (`memory.<expert>`). The only blessed writer of .memory/."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Bash(git *), Write
---
# Memory write

Write one memory note for an expert. Validates frontmatter, picks a non-colliding slug, regenerates touched `.tags/` files (local + global), optionally drops `--consolidate` log paths, and lands the change as a single atomic git commit under the memory-bot identity derived from the expert (`memory.<expert>` / `memory.<expert>@bot.lazy-cortex`). The caller and the expert that invoked the skill do NOT commit memory paths themselves — the subsystem owns its own git visibility.

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

Capture stdout — on success the worker prints `<note_path>\t<commit_sha>` (or `<note_path>\tno-commit` when the write was a byte-identical no-op). On failure stderr carries a `WriteError` line of the form `frontmatter-invalid: …` / `consolidate-out-of-scope: …` / `consolidate-io-error: …` / `commit-failed: …`.

The worker derives its commit identity from `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` (set by the expert-pump when spawned inside a daemon-driven expert), falling back to `lazy.settings.json[experts][<expert>].git_author` when those env vars are empty (operator-driven `/lazy-memory.reflect` path). The `memory.` prefix is always applied to both name and email local-part.

Outcome: `written` (stdout has a path + sha), `written-no-commit` (sha = `no-commit`, idempotent re-run), or `error:<category>` (stderr has a WriteError).

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
- **"commit-failed: git add returned …" / "commit-failed: git commit returned …"** → the staged index is left intact for operator inspection. Usually means a pre-commit hook rejected the change or git was busy with another session's lock. Resolve the underlying cause and re-run the write (idempotent if the note body is unchanged) or commit the staged paths by hand.
