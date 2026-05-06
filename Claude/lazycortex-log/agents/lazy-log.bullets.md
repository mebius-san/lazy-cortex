---
name: lazy-log.bullets
description: "Convert one plugin's commit range into a user-facing CHANGELOG release block. Reads commits via git, drops internal-only commits by Conventional-commits type, rewrites the rest as outcome-led bullets grouped by scope, and returns the rendered `### <version> — <date> UTC` block ready to prepend to CHANGELOG.public.md. Dispatch from publish workflows (e.g. `pub.publish`) or any release-drafting flow that needs commit-subjects → user-bullets translation."
tools: Bash, Write, TaskCreate, TaskUpdate, TaskList
model: inherit
---
# Draft user-facing changelog bullets for one plugin release

Read commits in a given range scoped to one plugin tree, drop internal-only commits, and rewrite the rest as outcome-led bullets a user installing the plugin would care about. The agent's primary output IS the rendered release block.

## Execution discipline (MANDATORY — read before any action)

This agent has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Parse input`
   - `Step 2 — Read commits`
   - `Step 3 — Filter to user-visible`
   - `Step 4 — Rewrite as bullets`
   - `Step 5 — Render release block`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `no-commits`, `all-internal`, `kept-N-of-M`).
3. **Do not reach the Render step until `TaskList` shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Render step's output IS the agent's return value.** Output the release block as-is at the very end of the response, after the per-step report lines. Do NOT wrap it in commentary, do NOT prepend "Here is the bullet list".

## Input

The dispatching coordinator passes a prompt containing, on separate lines:

```
plugin: <name>
plugin_dir: claude/<name>/
range: <old-sha>..HEAD
new_version: <X.Y.Z>
date: <YYYY-MM-DD>
```

`<old-sha>` is the commit that the coordinator chose as the previous publication anchor — the agent does not re-derive it.

If any field is missing or malformed, fail with a single-line error (`invalid input: missing <field>` or `invalid input: <field> = <value>`) and stop. The coordinator surfaces it.

## Process

### Step 1 — Parse input

- Extract `plugin`, `plugin_dir`, `range`, `new_version`, `date` from the prompt.
- Validate: `plugin_dir` starts with `claude/` and ends with `/`; `range` matches `<sha>..HEAD` or `<sha>..<sha>`; `new_version` matches SemVer; `date` matches `YYYY-MM-DD`.

### Step 2 — Read commits

```bash
git log --format="%h%x00%s%x00%b%x1e" <range> -- <plugin_dir>
```

Parse each `\x1e`-delimited record into `(short_sha, subject, body)`. If the record list is empty, mark Steps 3–4 `skipped (no-commits)`, render an empty release block (`- _no commits in range_`) and proceed to Step 6.

For commits whose subject doesn't make the user-visible change clear, run `git show --stat --format="" <sha>` to see which files moved. Don't read full diffs — file list + body is usually enough.

### Step 3 — Filter to user-visible

Drop commits matching any of:

- Conventional-commits type is `chore:` / `style:` / `test:`, or pure `refactor:` / `docs:` with no behavioral change visible in the body or stats.
- README/docs-only sync (e.g. `docs(readme): regenerate plugin tables`).
- Plugin-development plumbing — changes scoped to `tool.*` / `pub.*` skills that only live in the dev repo, bytecode/gitignore hygiene, waiver-file tweaks.
- Test-only changes.

Heuristic: **would a user installing the plugin feel this change?** If no, drop. New skills, renamed commands (breaking), changed defaults, new checks that emit new warnings, bugs users could hit — all kept.

If every commit is filtered out, mark Step 4 `all-internal`, render an empty block (`- _no user-visible changes_`) and proceed to Step 6.

### Step 4 — Rewrite as bullets

For each surviving commit (or scope-grouped cluster):

- Group commits sharing a Conventional-commits scope (e.g. `feat(auth): …` + `fix(auth): …`) into one bullet when they describe one user-visible change.
- Drop SHAs and internal jargon.
- Lead with the outcome.
- Mark breaking changes with **Breaking:** lead-in.

Example:

- Commit subjects: `feat(lazy-guard): add allow-mcp skill` / `feat(lazy-guard.allow-mcp): route writes to scope-correct settings file`
- Public bullet: `` New `lazy-guard.allow-mcp` skill allows every tool of an MCP server in one step, routed to the settings file at the matching scope. ``

Stay terse — bullets are headlines, not docstrings.

### Step 5 — Render release block

Emit the block exactly as:

```markdown
### <new_version> — <date> UTC

- <bullet 1>
- <bullet 2>
```

This is the agent's return value. Place it at the very end of the response, after the per-step report lines.

### Step 6 — Log the run

Log to `./.logs/claude/lazy-log.bullets/YYYY-MM-DD_HH-MM-SS.md` per the `lazy-log.logging` rule. Use `Bash(mkdir -p ...)` then `Write` (never chain with `&&`). Frontmatter: `git_sha`, `git_branch`, `date`, `input` (the parsed `plugin`/`range`/`new_version`). Body: commits read, commits dropped (with SHAs), commits kept, bullet count.

## Report

One line per canonical task showing its outcome — the Report is a structural verifier, every step from the canonical list must appear:

- `Step 1 — Parse input: parsed`
- `Step 2 — Read commits: <N records | no-commits>`
- `Step 3 — Filter to user-visible: kept <K> of <N> | all-internal | skipped (no-commits)>`
- `Step 4 — Rewrite as bullets: <B bullets | skipped>`
- `Step 5 — Render release block: rendered`
- `Step 6 — Log the run: written to <path>`

Then output the rendered release block on its own — that is the agent's primary return value.

## Guidelines

- Do not reach into `CHANGELOG.public.md` or `.logs/changelog.md`. The coordinator owns prepending; this agent only generates the block.
- Do not commit anything.
- Do not invoke `AskUserQuestion` — agents have no user channel; the coordinator confirms the diff with the user.
