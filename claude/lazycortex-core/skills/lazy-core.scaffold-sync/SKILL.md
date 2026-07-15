---
name: lazy-core.scaffold-sync
description: "Install-time helper: copies a plugin's authoring templates into the consumer's `.claude/templates/<group>/` directories and upserts the corresponding scaffold-registry entries. Invoked by a plugin's install skill via Skill dispatch."
allowed-tools: Read, Write, Glob, Bash(find *), Bash(ls *), Bash(diff *), Bash(cp *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(python3 *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet
---
# Sync Scaffold Templates and Registry

Copies every authoring template shipped by a plugin into the consumer's `.claude/templates/<group>/` directories, then upserts the corresponding entries into the scaffold registry. Invoked from a plugin's own install skill via `Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=<name> installPath=<path> scope=<project|user>")`. Safe to re-invoke; all file operations are idempotent.

Note: `lazy-core.install` Step 4 becomes an invocation of this skill for `lazycortex-core` itself — this skill is its own registry sync path (dogfood).

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve inputs and registry path`
   - `Step 2 — Discover manifests`
   - `Step 3 — Copy templates per group`
   - `Step 4 — Merge entries`
   - `Step 5 — Resolve core CLI`
   - `Step 6 — Upsert registry`
   - `Step 7 — Report`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`none`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve inputs and registry path

Parse the three inputs from the `args` string (or from the invoking skill's context):

- `plugin` — the plugin's installed name (e.g. `lazycortex-core`).
- `installPath` — absolute path to the plugin's install root (from `installed_plugins.json`).
- `scope` — `project` or `user`.

Resolve the scaffold registry path:

| Scope | Registry path |
|---|---|
| `project` | `<repo-root>/.claude/rules/lazy-core.scaffold.md` |
| `user` | `~/.claude/rules/lazy-core.scaffold.md` |

Where `<repo-root>` is `git rev-parse --show-toplevel` in the current working directory.

State outcome `resolved`.

## Step 2 — Discover manifests

Run:

```bash
find "<installPath>/templates" -maxdepth 3 -name "scaffold.entries.json"
```

Do NOT use `Path.glob()` or `Path.rglob()` — per the tech-stack contract, those are banned.

Each result path has the form `<installPath>/templates/<group>/scaffold.entries.json`. The parent directory name is the `<group>`.

If no manifest files are found → state outcome `none` (no-op), emit a brief message ("no scaffold.entries.json manifests found under `<installPath>/templates/`"), and stop. The remaining steps are skipped with outcome `skipped-no-manifests`.

Otherwise state outcome `discovered-N` where N is the number of manifests found.

## Step 3 — Copy templates per group

For each `<group>` discovered in Step 2, sync the template files from `<installPath>/templates/<group>/` into the consumer's `.claude/templates/<group>/` directory (where "consumer" scope = `~/.claude/` for `user`, `<repo-root>/.claude/` for `project`) with the deterministic triage script — the current/not-current verdict comes from the receipt, never from impression:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py --src <installPath>/templates/<group> --dst <consumerScope>/.claude/templates/<group> --exclude scaffold.entries.json
```

`scaffold.entries.json` is plugin-internal and must not land in the consumer tree. The script creates the target directory, copies absent targets (state **installed**), byte-compares the rest (**unchanged**), and lists every genuinely differing file in the receipt's `diverged` array without touching it. Subdirectories are ignored — template groups are flat.

An enabled plugin installs its whole template surface — no per-template "install this?" prompt. Apply judgment ONLY to the `diverged` list:

1. **Drift, cleanly mergeable** — the shipped delta applies without contradicting local edits (new headings / list items / registry entries added; every local-only chunk preserved) → merge silently via `Edit`. Uncontroversial additions (new entries in a registry group that already exists locally with the same key) just land. State **merged**.
2. **Conflict** — the same region (a heading body, a block, an entry value) was changed both in shipped and local in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` quoting the conflicting region with a unified diff, options **merge-shipped** / **keep-local**. State **merged** or **kept-local**.

"Conflict" means you cannot determine what should survive — not merely "the files differ". No contradiction → no question.

State for the group as a whole: one line per file as `<group>/<filename>: <state>`.

## Step 4 — Merge entries

Read each group's `scaffold.entries.json`. Each manifest contains a `templates` map whose **keys are consumer-scope template paths verbatim** (e.g. `.claude/templates/<group>/<filename>`) and whose values are glob lists: `{ ".claude/templates/<group>/<filename>": ["<glob1>", "<glob2>", ...], ... }`. These keys are used **as-is** — they become `data[<plugin>]` verbatim, with no rewriting.

Union the `templates` maps from every group into a single merged map.

Collision rule: if two groups contribute the same template path key with **different** glob arrays, FAIL with the message:

> `scaffold-sync: collision — template path "<key>" declared by both group "<groupA>" and group "<groupB>" with conflicting globs; resolve before continuing`

State outcome `merged-N` where N is the total number of entries across all groups; `collision-FAIL` on error.

## Step 5 — Resolve core CLI

Read `~/.claude/plugins/installed_plugins.json`. Find the `lazycortex-core@lazycortex` key. If absent or its array is empty → FAIL with:

> `scaffold-sync: cannot resolve core CLI — lazycortex-core not installed; run /lazy-core.install first`

Take the first entry's `installPath` field. The core CLI is at `<installPath>/bin/lazycortex-core`.

Verify the file exists with `Bash(test -f <coreCli>)`. If not → FAIL with:

> `scaffold-sync: core CLI not found at <coreCli>; run /plugin update lazycortex-core@lazycortex to restore`

State outcome `resolved`.

Note: `$LAZYCORTEX_PLUGIN_DIRS` may be unset at install time — always resolve via `installed_plugins.json`.

## Step 6 — Upsert registry

Write the merged entries map to a temp file at `~/tmp/scaffold-sync-entries-<timestamp>.json`:

```bash
mkdir -p ~/tmp
```

Then `Write` the JSON to `~/tmp/scaffold-sync-entries-<timestamp>.json`.

Run:

```bash
<coreCli> scaffold upsert --plugin <plugin> --entries @~/tmp/scaffold-sync-entries-<timestamp>.json --registry <regPath>
```

Capture the JSON output on stdout. The primitive returns a top-level `status` field with one of: `registered`, `unchanged`, `created-and-registered`, `removed`, `absent`, `error`.

On `error` → FAIL, surfacing the full output as the error message.

State outcome: the value of `status` from the returned JSON.

## Step 7 — Report

Emit a table of per-template copy states (Step 3) plus the registry upsert outcome (Step 6):

```
Templates synced:
  <group>/<filename>: <state>
  ...

Registry upsert: <status>
```

One line per template file. State one of: `installed`, `unchanged`, `merged`, `kept-local`. Then the upsert status line.

## Failure modes

- **`scaffold-sync: no scaffold.entries.json manifests found`** — the plugin ships no `templates/*/scaffold.entries.json` files → no templates were registered; the plugin may not use the scaffold system. State `none` and stop normally.
- **`scaffold-sync: collision — template path "<key>" declared by …`** — two groups declare the same template path with different globs → resolve by editing the plugin's `scaffold.entries.json` manifests so there is no overlap, then re-run.
- **`scaffold-sync: cannot resolve core CLI — lazycortex-core not installed`** — `installed_plugins.json` has no `lazycortex-core@lazycortex` entry → install the plugin first (`/lazy-core.install`), then re-run.
- **`scaffold-sync: core CLI not found at <path>`** — the `installPath` in `installed_plugins.json` points to a path that no longer exists → run `/plugin update lazycortex-core@lazycortex` to refresh the cache, then re-run.
- **`scaffold upsert` returns `error`** — the core CLI rejected the entries (malformed JSON, schema mismatch, or registry write failure) → inspect the full error output, fix the manifest, then re-run.

## Logging

Log each run to `./.logs/claude/lazy-core.scaffold-sync/YYYY-MM-DD_HH-MM-SS.md`.

Timestamp: `date -u +%Y-%m-%d_%H-%M-%S`.

Use two separate steps:

```
Bash(mkdir -p ./.logs/claude/lazy-core.scaffold-sync)
```

Then `Write` the log file with this structure:

```markdown
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "plugin=<plugin> installPath=<installPath> scope=<scope>"
---
# lazy-core.scaffold-sync

## Actions
- <bullet per action, file modified, or decision>

## Result
<success/failure + one-line summary>
```
