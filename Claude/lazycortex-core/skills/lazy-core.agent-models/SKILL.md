---
name: lazy-core.agent-models
description: "Interactively assign model tiers (haiku/sonnet/opus/inherit) to every dispatchable subagent missing from `lazy.settings.json`. Auto-routes each entry to its structurally-correct scope: `_user.*` → global file, `_project.*` → project file, `_builtin.*` → global (override with `--scope=project|global`). Cheap, standalone, idempotent — safe to re-run. Invoked directly or by `lazy-core.optimize` Phase 7."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, Bash(mkdir -p *), Bash(git rev-parse*), Bash(date *), Bash(test *)
---
# Fill agent_models

Standalone wizard for the `agent_models` section of `lazy.settings.json`. Extracted from `lazy-core.optimize` so you can fill model routes without paying for the full optimize pipeline (Phases 1–6: audit-repair, metadata, hygiene checks, parallel-scan refactor candidates, etc.).

## When to invoke

- **Directly**: `/lazy-core.agent-models` — after adding new agents, after a fresh `lazy-core.install`, or when `lazy-core.audit` reports missing `agent_models` entries.
- **From `lazy-core.optimize`**: Phase 7 of that skill delegates to this one. Running optimize end-to-end triggers this skill as its final interactive phase.

## Arguments

Optional flags on invocation:

- `--scope=auto|project|global` — default `auto`. Overrides per-entry routing.
  - `auto` (default) — route each entry by its group: `_user.*` → global file, `_project.*` → project file, `_builtin.*` → global file, plugin-domain groups → follow the plugin's own install scope (from `~/.claude/plugins/installed_plugins.json`; if the plugin is installed at both scopes, default global).
  - `project` — force every answered entry into `./.claude/lazy.settings.json` regardless of group. Useful when overriding globally-set tiers for just this repo.
  - `global` — force every answered entry into `~/.claude/lazy.settings.json`. Useful when bulk-promoting project answers to user-global.
- `--dry-run` — walk the wizard and report what would be written, but skip all `Write` calls. Useful for previewing scope routing.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical list (titles verbatim):
   - `Step 1 — Parse arguments`
   - `Step 2 — Load or initialize configs`
   - `Step 3 — Discover agents`
   - `Step 4 — Build missing-entries list`
   - `Step 5 — Resolve scope per entry`
   - `Step 6 — Wizard loop`
   - `Step 7 — Write back`
   - `Step 8 — Report and log`
2. **Mark each task `in_progress` on enter and `completed` on exit.** A no-op counts only if it produced an explicit outcome line in the Report (e.g. `nothing to do`, `dry-run — N entries would write`).
3. **Do not reach Report until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per step above. A missing line is a bug.

## Step 1: Parse arguments

Parse `$ARGUMENTS`:

- Extract `--scope=<value>` → `scopeMode`. Default: `auto`. Validate against `{auto, project, global}` — anything else → FAIL with a clear usage message.
- Extract `--dry-run` → `dryRun` (boolean). Default: `false`.
- Any other token → FAIL with usage. Ignore trailing whitespace.

Record the parsed values in the report.

## Step 2: Load or initialize configs

Read both `./.claude/lazy.settings.json` (project) and `~/.claude/lazy.settings.json` (user). For each:

- Missing or unparseable → treat as `{"version": 1, "agent_models": {}}` *in memory only*. Don't write yet.
- Parseable → use as-is.

Project root is `git rev-parse --show-toplevel` or cwd (warn if not in a git repo).

Build an in-memory merged view: `projectConfig` wins per-group over `userConfig`. Flatten to `{dispatch_string: value}` for lookup in Step 4.

**Do not write in this step.** Writes happen in Step 7 only for scopes that actually receive new entries.

## Step 3: Discover agents

Shared enumeration (same as `lazy-core.audit` / `lazy-core.doctor` Phase), deduped by full dispatch string:

1. **Built-ins** — hardcoded: `Explore`, `Plan`, `general-purpose`, `statusline-setup`. Group: `_builtin`. Dispatch: bare name.
2. **User-authored, global** — `~/.claude/agents/*.md`. Group: `_user`. Dispatch: filename stem.
3. **User-authored, project** — `./.claude/agents/*.md`. Group: `_project`. Dispatch: filename stem.
4. **Plugin-shipped** — `~/.claude/plugins/cache/**/agents/*.md`. Extract plugin name from path. Group: domain (plugin name up to first `-`, else whole name). Dispatch: `<plugin-name>:<stem>`.

For each, record: dispatch string, target group, plugin name (if applicable), source path, and whether a merged-config entry exists.

## Step 4: Build missing-entries list

For each discovered agent, if its dispatch string is absent from the flat map from Step 2, add it to the missing list. Entries explicitly set to `"inherit"` in either scope count as decided — exclude them.

If the missing list is empty → skip Steps 5–7, go to Step 8 with outcome `nothing to do`.

## Step 5: Resolve scope per entry

Map each missing entry to its destination file. Behavior depends on `scopeMode` from Step 1:

### `scopeMode = project`

Every entry → `./.claude/lazy.settings.json`. No ambiguity, no plugin-scope lookup.

### `scopeMode = global`

Every entry → `~/.claude/lazy.settings.json`. No ambiguity.

### `scopeMode = auto` (default)

Per-group routing:

| Group | Destination |
|---|---|
| `_user` | `~/.claude/lazy.settings.json` (global — `_user.*` is globally-authored agents) |
| `_project` | `./.claude/lazy.settings.json` (project — `_project.*` is this repo's agents) |
| `_builtin` | `~/.claude/lazy.settings.json` (global — built-ins are identical everywhere) |
| Plugin-domain (e.g. `lazycortex`, `superpowers`) | Read `~/.claude/plugins/installed_plugins.json` and find the plugin's `scope` field. `user` → global file; `project` → project file; both scopes → global (most common). Plugin not found in installed_plugins.json → global (WARN in report). |

Record the resolved destination per entry for Step 6's question body and Step 7's write plan.

### File existence guarantee

If any resolved destination file does not yet exist, initialize it in memory as `{"version": 1, "agent_models": {}}`. Actual file creation happens in Step 7 only if that destination receives at least one new entry.

## Step 6: Wizard loop (one AskUserQuestion per agent)

For each missing entry, fire a single `AskUserQuestion`:

- **question**: `` `<dispatch-string>` — assign model tier? ``
- **description**:
  ```
  **Group:** <group>
  **Source:** <path or "(built-in)">
  **Description:** <agent's frontmatter `description:` field, or "(no description)">
  **Will write to:** <resolved destination path> (<scopeMode>)
  **Suggested tier:** <heuristic-tier>

  Heuristic:
  - _builtin: Explore→haiku, Plan→opus, general-purpose→inherit, statusline-setup→haiku.
  - *log*/*distill*/*tag*/*timeline* + description mentions rewriter/formatter/distill/prose/mechanical → haiku.
  - *review*/*audit*/*plan*/*design* → opus.
  - Otherwise → sonnet.
  ```
- **options** (exactly six):
  - `add as <suggested>` *(Recommended)*
  - `add as haiku`
  - `add as sonnet`
  - `add as opus`
  - `add as inherit`
  - `skip`

On answer:

- `skip` → record **skipped**; no write planned. Next run re-prompts.
- any `add as <tier>` → record **planned**: `(destination, group, dispatch, tier)`.

One `AskUserQuestion` at a time. Wait for each answer before the next prompt.

## Step 7: Write back

Group the planned writes from Step 6 by destination file. For each destination that has at least one planned entry:

1. If the file does not yet exist, `Write` with `{"version": 1, "agent_models": {}}` as base (creating parent dir with `mkdir -p` first if needed).
2. Read the file fresh, apply all planned entries for this destination (creating missing groups on demand, preserving all existing keys — never overwrite; this loop only writes *missing* entries), and write back.

If `dryRun = true`, skip all writes. Report what *would* have been written, per destination.

## Step 8: Report and log

### Report

Render a compact table:

```
destination                         | added | skipped | via-scope
-----------------------------------+-------+---------+----------
./.claude/lazy.settings.json        |   N   |    S    | <mode>
~/.claude/lazy.settings.json        |   N   |    S    | <mode>
```

Plus one line per *added* entry: `<group>.<dispatch> = <tier> → <destination>`.

If `dryRun = true`, wrap the whole table with `[DRY RUN — no files modified]`.

If the missing list was empty in Step 4, render: `nothing to do — all agents have routing entries`.

### Log

Log the run to `./.logs/claude/lazy-core.agent-models/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (`git_sha` frontmatter, Actions + Result body). Use two separate steps: `Bash(mkdir -p ...)` then `Write`.

## Notes

- **Idempotent**: a second run on a fully-configured vault shows "nothing to do".
- **No destructive writes**: never overwrites existing entries; only adds missing ones.
- **Scope auto-routing is structural**, not cosmetic. `_user.*` lives in the global file by definition (the agents themselves live in `~/.claude/agents/`); `_project.*` in the project file for the same reason. Writing them elsewhere creates split-brain configs that `lazy-core.audit` will flag.
- **Override scope deliberately**: use `--scope=project` when you want a project-specific override of a globally-set tier, or `--scope=global` when bulk-promoting decisions. These are intentional deviations from the structural default; document the reason in your run log.
- **Relationship to `lazy-core.install`**: `install` seeds `_builtin` defaults at the install scope (non-interactive). This skill fills *missing* per-agent entries across all discovered sources (interactive wizard). They do not overlap.
