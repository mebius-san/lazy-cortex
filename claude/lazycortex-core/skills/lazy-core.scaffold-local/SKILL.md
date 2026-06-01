---
name: lazy-core.scaffold-local
description: "Manage `_local` scaffold entries in the consumer repo: add a new repo-specific template type (group + kind + globs) or remove an existing one. Safe path to author `_local` entries without hand-editing the fragile registry YAML."
allowed-tools: Read, Write, Glob, Bash(find *), Bash(ls *), Bash(test *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(python3 *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet
---
# Manage Local Scaffold Entries

Adds or removes repo-specific scaffold types under the reserved `_local` key in the consumer's scaffold registry. The `_local` key has no plugin manifest — the registry entry is its own source of truth, and the template is authored in place inside the consumer repo. Use this skill instead of hand-editing `lazy-core.scaffold.md` directly.

Invoked with optional args: `mode=<add|remove>` (default: `add`), `group=<group>`, `kind=<kind>`.

Note: `_local` is just another top-level key to the `lazycortex-core scaffold` primitive — no special-casing; the same surgical write protects sibling plugin keys and surrounding prose.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve inputs and registry path`
   - `Step 2 — Resolve core CLI`
   - `Step 3 — Gather user inputs`
   - `Step 4 — Execute add or remove`
   - `Step 5 — Validate registry`
   - `Step 6 — Report`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`skipped-per-user-choice`, `absent`, `unchanged`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve inputs and registry path

Determine the mode from args: `add` (default) or `remove`.

Resolve the scaffold registry path. Scope is always `project` for `_local` entries (they belong in the consumer repo):

| Scope | Registry path |
|---|---|
| `project` | `<repo-root>/.claude/rules/lazy-core.scaffold.md` |

Where `<repo-root>` is `git rev-parse --show-toplevel`.

Verify the registry file exists with `Bash(test -f <regPath>)`. If absent → FAIL with:

> `scaffold-local: registry not found at <regPath>; run /lazy-core.install to initialise the scaffold registry`

State outcome `resolved`.

## Step 2 — Resolve core CLI

Read `~/.claude/plugins/installed_plugins.json`. Find the `lazycortex-core@lazycortex` key. If absent or its array is empty → FAIL with:

> `scaffold-local: cannot resolve core CLI — lazycortex-core not installed; run /lazy-core.install first`

Take the first entry's `installPath` field. The core CLI is at `<installPath>/bin/lazycortex-core`.

Verify the file exists with `Bash(test -f <coreCli>)`. If not → FAIL with:

> `scaffold-local: core CLI not found at <coreCli>; run /plugin update lazycortex-core@lazycortex to restore`

Note: `$LAZYCORTEX_PLUGIN_DIRS` may be unset at install time — always resolve via `installed_plugins.json`.

State outcome `resolved`.

## Step 3 — Gather user inputs

Ask one `AskUserQuestion` at a time. Wait for each answer before the next.

**For both `add` and `remove`:**

1. If `group` was not provided in args, ask:
   - question: `Which template group does this entry belong to?`
   - description: `The group is the subdirectory name under \`.claude/templates/\` (e.g. \`core\`, \`help\`, \`review\`). It groups related template kinds.`

2. If `kind` was not provided in args, ask:
   - question: `What is the kind (template name) for this entry?`
   - description: `The kind names the template file: \`.claude/templates/<group>/<kind>-template.md\`. For \`add\`, this file will be created if it does not already exist. For \`remove\`, this entry and its template file will be deleted.`

**For `add` only:**

3. Ask for the glob list:
   - question: `Enter the glob patterns (one per line) that this template should match.`
   - description: `These are the file globs that trigger this template in \`lazy-core.scaffold\`. Example: \`.claude/rules/*.md\` or \`claude/*/references/*-schema.md\`. Provide one glob per line.`
   - Parse the answer into a list by splitting on newlines; trim whitespace; discard empty lines.

**For `remove` only:**

After collecting `group` and `kind`, read the current `_local` map (Step 4 — `scaffold list`) to confirm the entry exists. If the entry is absent → FAIL with:

> `scaffold-local: entry \`.claude/templates/<group>/<kind>-template.md\` not found in the _local registry map`

State outcome `gathered`.

## Step 4 — Execute add or remove

### `add` path

**4a. Create the template in place.**

Template path: `.claude/templates/<group>/<kind>-template.md` (relative to `<repo-root>`).

Check whether the file exists:

- **Absent** → `mkdir -p <repo-root>/.claude/templates/<group>/` then `Write` the file with a minimal seed header:

  ```markdown
  ---
  # <kind> template
  # Group: <group>
  # Created by: lazy-core.scaffold-local
  ---
  # <Kind> — <brief description>

  <Replace this with the template body.>
  ```

  State **created**.

- **Present** → `AskUserQuestion`:
  - question: ``Template \`.claude/templates/<group>/<kind>-template.md\` already exists — overwrite it?``
  - description: `Overwriting replaces the current file with a fresh seed. Choose \`keep\` to leave the file untouched and only update the registry entry.`
  - options: **keep** / **overwrite**
  - **keep** → no file write. State **kept**.
  - **overwrite** → write the seed as above. State **overwritten**.

**4b. Read the current `_local` map.**

Run:

```bash
<coreCli> scaffold list --registry <regPath>
```

Parse the JSON output. Extract `data._local` — if the key is absent, start with `{}`.

**4c. Merge and upsert.**

Add or update the entry:

```json
".claude/templates/<group>/<kind>-template.md": ["<glob1>", "<glob2>", ...]
```

Write the updated `_local` map to `~/tmp/scaffold-local-entries-<timestamp>.json`:

```bash
mkdir -p ~/tmp
```

Then `Write` the JSON to that path.

Run:

```bash
<coreCli> scaffold upsert --plugin _local --entries @~/tmp/scaffold-local-entries-<timestamp>.json --registry <regPath>
```

Capture the JSON output. On `error` status → FAIL, surfacing the full output.

State outcome: value of `status` from the returned JSON.

### `remove` path

**4a. Read the current `_local` map.**

Run:

```bash
<coreCli> scaffold list --registry <regPath>
```

Parse `data._local`. If the key is absent or the target entry is missing → FAIL with:

> `scaffold-local: entry \`.claude/templates/<group>/<kind>-template.md\` not found; nothing to remove`

**4b. Drop the entry and write.**

Remove the key `.claude/templates/<group>/<kind>-template.md` from the map.

- If the resulting map is empty → run:

  ```bash
  <coreCli> scaffold remove --plugin _local --registry <regPath>
  ```

  Capture JSON output. On `error` → FAIL.
  State outcome: `removed-plugin`.

- If the map still has entries → write the reduced map to `~/tmp/scaffold-local-entries-<timestamp>.json`, then:

  ```bash
  <coreCli> scaffold upsert --plugin _local --entries @~/tmp/scaffold-local-entries-<timestamp>.json --registry <regPath>
  ```

  Capture JSON output. On `error` → FAIL.
  State outcome: value of `status` from returned JSON.

**4c. Delete the template file (confirm first).**

`AskUserQuestion`:
- question: ``Also delete the template file \`.claude/templates/<group>/<kind>-template.md\`?``
- description: `The registry entry has been removed. Deleting the file removes it entirely; keeping it leaves an unused file on disk.`
- options: **delete** / **keep**
- **delete** → `Bash(rm "<repo-root>/.claude/templates/<group>/<kind>-template.md")`. State **deleted**.
- **keep** → no action. State **kept**.

## Step 5 — Validate registry

Run:

```bash
<coreCli> scaffold validate --registry <regPath>
```

Parse the JSON output. Surface any `WARN` findings (e.g. `glob_overlap`) to the operator:

> `scaffold-local: validation warnings — <finding>. Confirm intended or narrow the glob before proceeding.`

`FAIL`-level findings are hard errors; surface them and stop.

If no findings → state outcome `clean`. If warnings only → state outcome `warned`. If hard errors → FAIL.

## Failure modes

- **`scaffold-local: registry not found at <path>`** — `.claude/rules/lazy-core.scaffold.md` does not exist → run `/lazy-core.install` to initialise the scaffold registry, then re-run.
- **`scaffold-local: cannot resolve core CLI — lazycortex-core not installed`** — `installed_plugins.json` has no `lazycortex-core@lazycortex` entry → install the plugin first (`/lazy-core.install`), then re-run.
- **`scaffold-local: core CLI not found at <path>`** — the `installPath` in `installed_plugins.json` points to a missing path → run `/plugin update lazycortex-core@lazycortex` to refresh, then re-run.
- **`scaffold-local: entry … not found in the _local registry map`** — attempting to remove an entry that is not registered → check the entry name with `scaffold list --registry <regPath>`.
- **`scaffold upsert` / `scaffold remove` returns `error`** — the core CLI rejected the operation → inspect the full error output, fix the input, then re-run.
- **`scaffold validate` returns FAIL-level findings** — the registry has structural errors after the upsert → inspect the validation output and edit `.claude/rules/lazy-core.scaffold.md` directly to resolve, then validate again.

## Logging

Log each run to `./.logs/claude/lazy-core.scaffold-local/YYYY-MM-DD_HH-MM-SS.md`.

Timestamp: `date -u +%Y-%m-%d_%H-%M-%S`.

Use two separate steps:

```
Bash(mkdir -p ./.logs/claude/lazy-core.scaffold-local)
```

Then `Write` the log file with this structure:

```markdown
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "mode=<add|remove> group=<group> kind=<kind>"
---
# lazy-core.scaffold-local

## Actions
- <bullet per action, file modified, or decision>

## Result
<success/failure + one-line summary>
```
