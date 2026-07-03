---
name: lazy-runtime.preflight
description: Validate that every routine-dispatched expert is actually launchable — its spawn config is well-formed, its agent / aspects / protocols resolve, and its optional per-expert MCP servers initialize without hanging. Emulates each expert launch with a trivial prompt (no real work), then for a broken config proposes a concrete fix and applies it only after the operator confirms. Run before wiring a new expert or MCP server into a live routine, or when a routine's expert spawns keep timing out.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(git rev-parse *), Bash(date -u *), Write, Edit, AskUserQuestion
---
# Runtime Preflight

Every routine of type inbox / schedule / git / md-scan that carries an `expert` key dispatches that expert as a headless `claude -p` spawn. A malformed spawn config (unresolvable agent, missing aspect / protocol, a bad `mcp_config` path, or an MCP server that hangs / needs auth at init) fails silently at runtime — the job eats the routine's wall timeout and dies. This skill validates each such expert **before** it runs live: it enumerates the target experts, runs static config checks, then emulates the real launch (same command line as the pump, via `expert_pump.build_expert_argv`) with a trivial prompt that does no real work. On a failing expert it proposes a concrete fix and applies it only after the operator confirms.

The heavy lifting is in `${CLAUDE_PLUGIN_ROOT}/bin/expert_preflight.py`, which emits a JSON verdict document. This skill parses that JSON, renders a per-expert table, walks the operator through each proposed fix one question at a time, and logs the run. The bin never mutates settings; every write in this skill is gated on an explicit operator `yes`.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Run preflight`
   - `Step 2 — Render verdict table`
   - `Step 3 — Confirm + apply fixes`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Run preflight

Run the bin from the repo root, passing through an optional single-expert argument. When the operator invoked `/lazy-runtime.preflight <name>`, forward `--expert <name>`; otherwise run over every target expert:

```
Bash(LAZY_REPO_ROOT="$PWD" python3 "${CLAUDE_PLUGIN_ROOT}/bin/expert_preflight.py" [--expert <name>])
```

Parse the JSON on stdout. Its shape:

- `experts[]` — one entry per validated expert: `name`, `static[]` (`{level, message}`), `dynamic` (or `null` when the probe was skipped), `verdict` (`ok` / `fail`), `fixes[]`.
- `skipped_cross_repo[]` — `expert@<repo>` targets not validated (this preflight only checks local-repo experts).
- `summary` — one-line count.

The dynamic block, when present, carries `exit`, `duration_s`, `timed_out`, `agent_resolved`, `servers[]` (`{name, status, detail}` where status ∈ `connected` / `timed-out` / `auth-required` / `spawn-failed` / `pending-approval` / `unknown`), and `best_effort_plugin_dirs`.

The full dynamic probe spawns `claude` per expert (up to ~90s each) and may need MCP auth. When the operator wants a fast structural sweep with no spawn, run with `--no-probe` instead — static checks only.

Outcome: `preflight-run` or `no-targets` (empty `experts[]`).

## Step 2 — Render verdict table

If `experts[]` is empty: print "No expert-shape routines carry a local expert to validate." plus any `skipped_cross_repo` entries, and skip to Step 4 with outcome `no-targets`.

Otherwise render one markdown table row per expert:

| expert | verdict | static issues | server statuses |
|---|---|---|---|

- **verdict** — `ok` or `fail`.
- **static issues** — the `message` of each `static[]` finding, or `—` when none. Prefix each with its `level` (`fail` / `warn`).
- **server statuses** — `<name>: <status>` per `dynamic.servers[]`, or `—` when the expert declares no MCP servers or the probe was skipped.

Below the table, note any expert whose `dynamic.best_effort_plugin_dirs` is true: "plugin-dir resolution was best-effort for <expert> — a probe-only failure there may be a false negative; re-run under the daemon or with `LAZYCORTEX_PLUGIN_DIRS` set to confirm." List `skipped_cross_repo` targets as unvalidated.

Outcome: `table-shown` or `no-targets`.

## Step 3 — Confirm + apply fixes

For each expert with `verdict == "fail"`, walk its `fixes[]` in order. **One `AskUserQuestion` per fix — never batch.** If no expert failed, mark this step `skipped` with outcome `all-ok`.

Branch on each fix's `kind`:

### `drop-mcp-server` — offending server times out / fails to spawn

Ask via `AskUserQuestion`:

> Expert `<expert>`'s MCP server `<name>` <detail>. Drop it from `<expert>`'s `mcp_config`?
> - **drop** — remove server `<name>` from every `mcp_config` file the expert references. The expert spawns hermetically for that server.
> - **keep** — leave the config as-is. The expert stays failing until the server is fixed by hand.

On **drop**: locate the offending server. The `target` is `<expert>.mcp_config:<name>`. Read `experts.<expert>.mcp_config` from `.claude/lazy.settings.json` (a path string or list). For each referenced config file, if its `mcpServers` object contains `<name>`, remove that key via `Edit` on the config JSON file (not `lazy.settings.json` — the server lives in the MCP-config file the expert points at). Confirm the file still parses. Outcome `dropped`. On **keep**: outcome `kept-per-user-choice`.

### `mcp-login` / `pending-approval` — server needs interactive auth

These cannot be auto-fixed (the daemon spawns headless with no TTY). Print the exact instruction and ask only whether to continue to the next fix:

> Expert `<expert>`'s MCP server `<name>` requires authentication. Run this by hand in a terminal, then re-run `/lazy-runtime.preflight`:
>
>     claude mcp login <name>
>
> (For a headless host: `claude mcp login --no-browser <name>`.)

Do not mutate settings for this kind. Outcome `login-instructed`.

### `fix-path` — bad `mcp_config` path

Ask via `AskUserQuestion`:

> Expert `<expert>`'s `mcp_config` points at a path that <does not exist | does not parse>: <detail>. How should I resolve it?
> - **correct** — you supply the right repo-relative path; I write it into `experts.<expert>.mcp_config`.
> - **remove** — drop the bad path from `experts.<expert>.mcp_config` (or clear the field when it was the only entry).
> - **leave** — no change; the expert stays failing.

On **correct**: ask one follow-up for the replacement path, then `Edit` `experts.<expert>.mcp_config` in `.claude/lazy.settings.json`. On **remove**: `Edit` out the bad entry (clear the field entirely if it becomes empty). On **leave**: outcome `kept-per-user-choice`. Otherwise outcome `path-fixed`.

**Settings writes.** All mutations go through a careful `Edit` on the exact JSON file — never a blind overwrite. This repo ships no dedicated settings-writer CLI for surgical `experts.<expert>.mcp_config` edits (the `settings-set` CLI replaces a whole section, which would clobber sibling experts), so a scoped `Edit` on the JSON is the correct tool. NEVER mutate any settings file without a confirmed `yes` from the fix's `AskUserQuestion`.

Because a settings edit dirties a tracked file, commit it in the same execution: `git add .claude/lazy.settings.json` (plus any edited MCP-config file) and `git commit -m "fix(runtime): preflight drop/repair <expert> mcp_config"` — see `lazy-core.skill-writing § 6`. If the tree cannot be committed cleanly (transactional git state), do not write — report the finding and let the operator apply the fix.

Outcome: `dropped`, `path-fixed`, `login-instructed`, `kept-per-user-choice`, or `all-ok`.

## Step 4 — Report

Print the summary line from the JSON, then one line per task in the canonical list, each with its outcome word. A missing line is a bug; do not render the report with gaps.

If any expert still fails after applied fixes, remind the operator to re-run `/lazy-runtime.preflight` to confirm the config is now launchable.

Outcome: `reported`.

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-runtime.preflight)
```

Then `Write` to `.logs/claude/lazy-runtime.preflight/<UTC-timestamp>.md` (timestamp from `date -u +%Y-%m-%d_%H-%M-%S`):

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<--expert <name> | --no-probe | none>"
---
```

`# lazy-runtime.preflight`

`## Actions`
- Ran preflight (`<N>` experts, `<static-only|static+probe>`)
- Rendered verdict table (`<failing>` failing)
- Applied fixes (`<dropped|path-fixed|login-instructed|kept-per-user-choice|all-ok>` per expert)

`## Result` `<all-ok | fixes-applied | still-failing | no-targets>` + one-line summary.

## Failure modes

- **"No expert-shape routines carry a local expert to validate."** — every routine is `command`-shape or targets a cross-repo `expert@<repo>` → nothing to check; register an `expert`-shape routine first, or run the preflight in the repo that owns the expert.
- **A probe reports every server `timed-out` at once** — the probe hit its 90s wall budget (the whole spawn hung, not one server) → confirm `claude` is on PATH and authenticated (`claude -p "hi"` by hand), then re-run.
- **"plugin-dir resolution was best-effort"** in the table — the preflight ran interactively with no `LAZYCORTEX_PLUGIN_DIRS` and derived plugin dirs from the repo + cache → a probe-only failure may be a false negative; re-run under the daemon or export `LAZYCORTEX_PLUGIN_DIRS` and confirm.
- **A fix cannot be applied because the tree is mid-merge / rebase** — the skill refuses to write a settings change it cannot commit → finish the git transaction, then re-run `/lazy-runtime.preflight` to apply the fix.
