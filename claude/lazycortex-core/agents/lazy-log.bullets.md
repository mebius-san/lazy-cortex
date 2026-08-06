---
name: lazy-log.bullets
description: "Use when one plugin is being released and its CHANGELOG.public.md needs a release block drafted from a commit range — dispatched by any release-drafting flow, or directly with plugin + range + version. Renders the `### <version> — <date> UTC` block of user-visible bullets: the per-release public counterpart to lazy-log.distill's running internal changelog."
tools: Bash, Write, TaskCreate, TaskUpdate, TaskList
model: inherit
logging-waiver: "single-response synthesizer — output IS the prose response, no mutations to record"
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

**Judge the commit's diff inside this plugin, never its subject scope.** A repo-wide commit — `feat(repo): …`, `docs(repo): …`, a subject listing eight other plugins — reaches many trees at once, and the part that landed in *this* plugin is what the release block is about. Re-read it scoped: `git show <sha> -- <plugin_dir>`. A commit whose overall subject reads like plumbing routinely carries a real consumer-visible change to one plugin, and dropping it on the subject alone is how a release ships as "no user-visible changes" while its siblings, changed by the very same commit, each get a bullet. Conversely a repo-wide commit that only touched this plugin's README is still a drop.

If every commit is filtered out, mark Step 4 `all-internal` and render `- _no user-visible changes_`. Before you do, check the version delta: a plugin whose version moved but whose every commit filtered out is the signature of a mis-scoped judgement above, not of a genuinely silent release. Re-read the scoped diffs once before emitting an empty block — an empty release block is a claim to the consumer that nothing changed for them, and it must be true.

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
