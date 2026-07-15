---
name: lazy-guard.allow-mcp
description: "Register tools of one or more MCP servers in Claude Code settings using a 3-bucket classifier — safe/reversible tools into permissions.allow (no prompt), truly destructive tools into permissions.ask (always prompt), and medium-risk tools skipped entirely so Claude Code prompts once per call and the user decides. Writes to settings.local.json (gitignored) by default to keep personal permissions out of tracked settings shared with teammates. For globally defined servers, asks whether to register at the global scope (~/.claude/settings.local.json) or per-project (./.claude/settings.local.json). Also strips redundant mcp__ entries from paired tracked settings.json after promotion. Optionally installs a SessionStart preload hook (in gitignored settings.local.json — a personal optimization, not universal enablement) that tells the agent to resolve the server's tool schemas via ToolSearch at session start — eliminates the deferred-loading round-trip that otherwise causes drift to Bash equivalents. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(date -u *), Bash(git rev-parse *)
lazy_setup_phase: post-install
requires_live_session: true
---
# Register MCP Server Tools

Register `mcp__<server>__<tool>` entries for one or more MCP servers using a **3-bucket classifier**:

- **`permissions.allow`** — safe/reversible tools. No prompt. Reads + low-risk writes the user has judged acceptable.
- **`permissions.ask`** — truly destructive tools (irreversible data loss, remote state mutation). Prompt every call.
- **Skip** — medium-risk tools. **Neither list.** Claude Code falls back to its built-in per-call prompt so the user decides in-context.

**Default target: `settings.local.json` (gitignored), not `settings.json` (tracked).** Permission choices are personal and machine-local — they must not leak into commits that teammates inherit. The skill writes to `settings.json` only when the user explicitly opts in (rare).

**Never write silently** — always show the planned diff (allow adds, ask adds, skipped tools, cross-scope cleanup) and get confirmation first. The only exception is § Non-interactive execution: an executor with no user channel writes mechanical extensions of recorded decisions and routes the diff into the run report instead.

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Parse input`
   - `Phase 2 — Discover MCP servers`
   - `Phase 3 — Enumerate and classify tools per server`
   - `Phase 4 — Route each server to the correct settings file`
   - `Phase 5 — Reconcile and preview`
   - `Phase 6 — Write`
   - `Phase 6.5 — Strip cross-scope leaks`
   - `Phase 7 — SessionStart preload hook`
   - `Phase 8 — Report`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1: Parse input

Accepted input forms:

- `<server-name>` — allow only this server (e.g. `context7`)
- `<server1> <server2> ...` — allow listed servers
- empty / `all` / `*` — allow every discovered server

If the user also passed `--dry-run` (or says "preview"), run all phases except the final write — just print the planned change.

## Phase 2: Discover MCP servers

Read these files (skip any that don't exist; never create them in this phase):

- `~/.mcp.json` — global MCP server definitions
- `./.mcp.json` — project MCP server definitions
- `~/.claude/settings.json`, `~/.claude/settings.local.json` — check `enableAllProjectMcpServers` and global `enabledMcpjsonServers`
- `./.claude/settings.json`, `./.claude/settings.local.json` — check project `enabledMcpjsonServers`

Build an in-memory map for every server you find:

```
server_name -> {
  defined_in: "global" | "project",
  source_file: "<absolute path to the .mcp.json file>",
  enabled_by: "global-auto" | "project-settings" | "project-local" | "unknown"
}
```

If the user named a server that isn't present in any source, stop and show them the discovered servers so they can retry with a valid name.

## Phase 3: Enumerate and classify tools per server

For each target server, enumerate every tool name currently available to you in this session whose name matches `mcp__<server>__*`. These strings (full, verbatim, with the double underscores) are what gets written into the settings file.

**Do NOT invent tool names.** Only use names you can literally see in your active tool list. No wildcards — Claude Code matches `mcp__` entries exactly in both `allow` and `ask`; a glob like `mcp__context7__*` does not work.

If a server is defined but has zero matching tools in the current session, skip it and warn: the server isn't loaded — the user must restart Claude Code and re-run the skill.

### Classify each tool → `allow` / `ask` / `skip`

The classifier has three buckets. The goal: stop per-call prompts on things the user already trusts, keep hard stops on irreversible destruction, and **leave medium-risk tools alone** so Claude Code's default behavior (prompt once per call, user decides) applies.

- **`allow` (safe/reversible — no prompt).** The tool reads, or writes in a way the user considers trivially reversible:
  - All read verbs: `get_*`, `list_*`, `search*`, `query*`, `read*`, `recall*`, `reflect*`, `resolve*`, `diff*`, `status*`, `show*`, `log*` (as a read, e.g. `git_log`), `fetch*`, `refresh*`, `audit*`.
  - Low-risk writes that stage/create content the user can easily undo: staging changes, creating new isolated entities (branches, directives, mental models), appending to bank-style stores.

- **`ask` (truly destructive — always prompt).** The tool causes irreversible or hard-to-recover change:
  - Deletion verbs: `delete_*`, `remove_*`, `clear_*`, `drop_*`.
  - Working-tree mutations that throw away local state: `reset`, `checkout` (branch switch discards unstaged changes), `restore`, `revert`.
  - Force-pushes and anything that rewrites shared history: `push --force`, `force*`, history-rewrites on published refs.
  - Bulk destructive ops on remote stores.

- **Skip (medium-risk — neither list).** The tool has real consequences but is neither trivially reversible nor catastrophic. Examples: `git_commit` (creates a new commit — reversible locally with `reset`, but worth an acknowledgement per run), `cancel_operation`, network-side creates without a straightforward undo. **Do not write these to either list, and do not touch them if they are already pinned by the user.** A user who explicitly pinned a skip-bucket tool to `allow` or `ask` made a deliberate trust decision; this skill never re-asks or removes it. Claude Code will prompt the first time and remember the user's per-call choice for tools that aren't pinned.

**When uncertain → skip, not allow.** Never silently allow an unknown-shape mutation. Skip is the safe default for ambiguity.

Apply the same rule regardless of server. A read-shaped tool on a "dangerous" server still goes to `allow`; a destructive tool on a "safe" server still goes to `ask`. Tool-level classification, not server-level trust.

Concrete examples (canonical servers seen in this project):

| Tool name                                                                           | Bucket |
|-------------------------------------------------------------------------------------|--------|
| `mcp__context7__resolve-library-id` / `query-docs`                                  | allow  |
| `mcp__brave-search__brave_web_search` / `brave_local_search`                        | allow  |
| `mcp__git__git_status` / `git_diff*` / `git_log` / `git_show` / `git_branch`        | allow  |
| `mcp__git__git_add` / `git_create_branch`                                           | allow  |
| `mcp__git__git_commit`                                                              | skip   |
| `mcp__git__git_reset` / `git_checkout`                                              | ask    |
| `mcp__memory-*__get_*` / `list_*` / `recall` / `reflect` / `refresh_mental_model`   | allow  |
| `mcp__memory-*__retain` / `sync_retain` / `create_directive` / `create_mental_model` / `update_bank` / `update_mental_model` | allow |
| `mcp__memory-*__cancel_operation`                                                   | skip   |
| `mcp__memory-*__delete_*` / `clear_memories`                                        | ask    |

Build the per-server output as three sets: `to_allow`, `to_ask`, `to_skip`.

## Phase 4: Route each server to the correct settings file

### 4a. Default target: `settings.local.json`

Permission choices are per-developer, per-machine. Writing them into tracked `settings.json` leaks them to teammates who may have different risk preferences. **The default target is always the `settings.local.json` at the appropriate scope.**

| Server defined in         | Default target                      |
|---------------------------|-------------------------------------|
| `./.mcp.json` (project)   | `./.claude/settings.local.json`     |
| `~/.mcp.json` (global)    | ask the user — see 4b               |

The skill never writes to tracked `settings.json` unless the user explicitly overrides the default in Phase 5 confirmation. Direct writes to tracked settings are reserved for enablement flags (`enabledPlugins`, `enabledMcpjsonServers`, `hooks`) — not per-tool permission lists.

### 4b. Globally-defined servers: detect existing scope first, only ask if ambiguous

When a server is defined in `~/.mcp.json`, a permission entry at either scope is valid:

- **Global scope** (`~/.claude/settings.local.json`): one registration covers every project on this machine.
- **Project scope** (`./.claude/settings.local.json`): the registration only applies inside this repo.

**Check existing state before asking.** For each globally-defined server, inspect both `~/.claude/settings.local.json` and `./.claude/settings.local.json` for any `mcp__<server>__*` entries in `permissions.allow` or `permissions.ask`. Decide scope by inference, not by prompt:

| Existing `mcp__<server>__*` entries found in      | Action                                                                 |
|---------------------------------------------------|------------------------------------------------------------------------|
| Global only                                       | Route to **global**. Do not ask.                                       |
| Project only                                      | Route to **project**. Do not ask.                                      |
| Neither                                           | Ask via `AskUserQuestion` (default recommendation: **Project only**).  |
| Both scopes                                       | Ask via `AskUserQuestion` — state is ambiguous; user must pick one and the other scope's entries will be surfaced as a cross-scope leak in Phase 6.5. |

**Silence on no-ops is mandatory.** If the inferred target scope already contains every tool the Phase 3 classifier would route to `allow`/`ask` for that server, there is nothing to write — skip the question entirely and let Phase 5 report the idempotent no-op. Only prompt when a write is actually going to happen *and* the scope is genuinely undetermined.

When a prompt is required, use `AskUserQuestion` with two options — "Global (all projects on this machine)" and "Project only (this repo)". Ask at most once per run, batched across all servers that still need a scope decision. Default recommendation: **Project only** — smaller blast radius, easier to revert by deleting the file.

If both a global and project definition exist for the same server name in `.mcp.json` sources, ask which server definition is authoritative before routing.

### 4c. Never add to `~/.claude/settings.local.json` unless user explicitly chose "Global" in 4b

Global `settings.local.json` is normally kept empty by the `lazy-guard.settings.py` PreToolUse hook. The hook has a narrow exception for entries added through this skill after the user confirms the global-scope choice — the confirmation is the audit trail. Without that confirmation, never write to it.

## Phase 5: Reconcile and preview

The Phase 3 classifier is the source of truth — every `mcp__<server>__*` tool must exist at most once across the target file's `allow` + `ask` lists, and not at all if classified as `skip`. Reconcile, don't just append.

For each target settings file (always a `settings.local.json` unless user overrode):

1. Read current JSON. If the file doesn't exist, target content is `{"permissions":{"allow":[],"ask":[]}}`.
2. For the servers routed to this file, compute four disjoint sets:
   - `to_allow_new     = allow-tools  \ current permissions.allow` (excluding any already in `ask` — handled by `to_move`).
   - `to_ask_new       = ask-tools    \ current permissions.ask`   (excluding any already in `allow` — handled by `to_move`).
   - `to_move_to_ask   = { t : classifier(t)=="ask"   AND t ∈ permissions.allow }` — truly-destructive tools that are currently (mis-)allowed. Remove from `allow`, add to `ask`.
   - `to_move_to_allow = { t : classifier(t)=="allow" AND t ∈ permissions.ask }` — safe tools pinned to always-prompt. A valid user choice (stricter than the heuristic), so **do NOT move these automatically**. Surface as an info note only: "<tool> is in ask but classified as allow — left as-is (stricter than default)".

   **Skip-bucket tools are deliberately not reconciled.** A skip-classified tool that the user has pinned to `allow` or `ask` stays exactly where it is — no comparison, no removal, no prompt. This avoids re-asking the same "remove `git_commit`?" question on every run. Skip-bucket tools that are *not* pinned simply aren't written; Claude Code's per-call prompt handles them.
3. Compute **cross-scope duplicates** to strip (Phase 6.5): for each server whose target is `settings.local.json`, inspect the paired tracked `settings.json` and list any `mcp__<server>__*` entry still there. Tracked settings shouldn't own per-tool permissions, so anything found is a leak to clean up.
4. Print a diff-style preview per file: ``` <target file, absolute path>  (settings.local.json — gitignored) allow:
       + mcp__<server>__<safe-tool>            # new
       - mcp__<server>__<destructive-tool>     # promoting to ask
     ask:
       + mcp__<server>__<destructive-tool>     # new
       + mcp__<server>__<destructive-tool>     # promoted from allow
     skip (not written anywhere — pinned skip-bucket entries left untouched):
       mcp__<server>__<medium-risk-tool-1>
       mcp__<server>__<medium-risk-tool-2>
     notes:
       mcp__<server>__<safe-tool> is in ask but classified as allow — left as-is
       mcp__<server>__<medium-risk-tool-3> is in allow but classified as skip — left as-is (user-pinned)

   <paired tracked file, absolute path>  (settings.json — tracked — cleaning up leak)
     allow:
       - mcp__<server>__<any>                  # permissions belong in settings.local.json
     ask:
       - mcp__<server>__<any>
   ``` Omit any sub-block with no entries.
5. **Per-tool confirmation for every reversal of a prior trust choice.** Any entry in `to_move_to_ask` (user previously allowed → classifier now says destructive) is a reversal of a choice the user made in a past run or by hand. These MUST NOT be bundled into the general write confirmation — each needs its own `AskUserQuestion`, one at a time:

   - For each `t ∈ to_move_to_ask`: `AskUserQuestion` **"Promote `<t>` from `allow` to `ask`? Classifier marks it destructive; promotion means Claude Code prompts every call."** options: `promote` (default) / `keep-in-allow`. On `keep-in-allow`, drop `t` from `to_move_to_ask` for this run (and surface as a note: "left in allow per user override — classifier considered it destructive").

   Skip-bucket tools that the user pinned in a prior run are **never** subject to this confirmation — Phase 5 step 2 deliberately omits a `to_remove_skip` set. The user's pin stands until they un-pin it by hand.

   One tool call per question — never combined. After all per-tool answers are collected, re-render the preview reflecting the user's overrides, then ask a single bundled confirmation covering: additions to both lists, any promotions/removals the user approved, and tracked-scope cleanup. If `--dry-run`, stop here after the per-tool questions (preview reflects the dry-run outcome).

## Phase 6: Write

For each approved file:

- If the file exists: use the `Edit` tool to apply the changes from Phase 5, in order:
  1. Remove `to_move_to_ask` entries from the `allow` array.
  2. Append `to_allow_new` entries to the `allow` array.
  3. Append `to_ask_new ∪ to_move_to_ask` entries to the `ask` array (creating the array if absent).
  Preserve original formatting, comments, and unrelated keys. Separate `Edit` calls per array are acceptable when ranges don't overlap.
- If the file doesn't exist: use the `Write` tool to create it with `{"permissions":{"allow":[<to_allow_new>],"ask":[<to_ask_new>]}}` plus a trailing newline. Omit either key if its list is empty.

Never introduce any non-`mcp__*` entries. No `Bash(*)`, no `Edit`, no `Write` — MCP tool names only. The `lazy-guard.settings.py` PreToolUse hook will reject broad or destructive additions to `allow`.

After writing, re-read each file and assert:
- JSON still parses.
- Every `to_allow_new` entry is now in `allow`.
- Every `to_ask_new` and `to_move_to_ask` entry is now in `ask`.
- No `to_move_to_ask` entry remains in `allow`.
- No tool appears in both lists simultaneously.
- Skip-bucket entries that were pre-existing in `allow` or `ask` remain exactly where they were (the skill never touches them).

## Phase 6.5: Strip cross-scope leaks

Two kinds of leak must be cleaned up, both per-entry with explicit user confirmation. **Never silently flag-and-continue; never silently remove.**

For each server processed this run:

### 6.5a. Paired tracked `settings.json` (permissions in the wrong *file*)

Permission entries should not live in tracked `settings.json`. Once the target `settings.local.json` owns the entries, any leftover `mcp__<server>__*` in the paired tracked file is a leak.

1. Identify the **target** (a `settings.local.json`, per Phase 4).
2. Identify the paired **tracked** file:
   - Target = `./.claude/settings.local.json` → Tracked = `./.claude/settings.json`.
   - Target = `~/.claude/settings.local.json` → Tracked = `~/.claude/settings.json`.
3. Load the tracked file. Skip if it doesn't exist or has no `mcp__<server>__*` entries in `permissions.allow` or `permissions.ask`.
4. Enumerate every such entry (both arrays):
   - `tracked_leaks = { e ∈ allow ∪ ask : e startswith "mcp__<server>__" }`
5. **For each leak**, `AskUserQuestion` (one at a time): **"`<entry>` is in tracked `<tracked-file>` — permissions belong in `settings.local.json`. Remove from tracked?"** options: `remove` (default) / `keep`. On `keep`, leave untouched and record as a "user-kept leak" note in Phase 8.
6. For every leak the user approved, use `Edit` with minimal old/new replacements to drop just that entry. Preserve all other keys, entries, formatting, and comments. If a removal empties an array, leave `"allow": []` / `"ask": []` — do not delete the key.
7. Re-read the file; assert JSON still parses and each approved removal is gone.

### 6.5b. Opposite-scope `settings.local.json` (permissions in the wrong *scope*)

A project-scoped server's permissions should live in `./.claude/settings.local.json`; a global-scoped server's in `~/.claude/settings.local.json`. Entries for a project server that ended up in the global local file (or vice versa) are wrong-scope leaks.

1. Identify the **target scope** chosen in Phase 4 for this server.
2. Identify the **opposite-scope `settings.local.json`**:
   - Target = `./.claude/settings.local.json` → Opposite = `~/.claude/settings.local.json`.
   - Target = `~/.claude/settings.local.json` → Opposite = `./.claude/settings.local.json`.
3. Load the opposite file. Skip if it doesn't exist or has no `mcp__<server>__*` entries.
4. Enumerate every such entry in both `permissions.allow` and `permissions.ask`:
   - `opposite_scope_leaks = { e ∈ allow ∪ ask : e startswith "mcp__<server>__" }`
5. **For each leak**, `AskUserQuestion` (one at a time): **"`<entry>` is in `<opposite-file>` (wrong scope — `<server>` is routed to `<target-scope>`). Remove from `<opposite-file>`?"** options: `remove` (default) / `keep` (retain out-of-scope entry). On `keep`, record as a "user-kept wrong-scope entry" note in Phase 8.
6. For every leak the user approved, `Edit` with minimal old/new replacements. Same preservation rules as 6.5a.
7. Re-read and re-verify.

### Safety

- Never removes non-`mcp__` entries.
- Never removes entries for servers not processed in the current run.
- **Never removes without a per-entry `AskUserQuestion`.** A user-kept leak becomes a Phase 8 note, not a silent pass.
- Pure subtraction → idempotent on re-run. Previously-kept leaks will be re-asked next run (hook presence/absence is not remembered; re-asking is safe because the default is `remove`).

## Phase 7 — SessionStart preload hook for deferred MCP tool schemas

**Why.** MCP tools are surfaced to the agent as **deferred** — only tool names appear at session start; calling one requires a prior `ToolSearch` round-trip to load its schema. That friction is asymmetric with the always-loaded `Bash` tool, so the agent drifts to shell equivalents (e.g. `Bash(git status)` instead of `mcp__git__git_status`) even when a rule forbids it. A SessionStart hook can inject a short instruction telling the agent to resolve specific MCP tool schemas via `ToolSearch` on the first turn — one-time cost ≈1.1k tokens per session, and MCP tools become first-class for the rest of the session.

**Scope target.** This preload hook is a **personal optimization** (≈1.1k tokens/session cost, whose value each user weighs differently), not universal enablement. The global hygiene rule carves out personal-optimization hooks to `settings.local.json`, so Phase 7 writes there — never to tracked `settings.json`. The user still chooses **global** (`~/.claude/settings.local.json`) vs **project** (`./.claude/settings.local.json`).

### 7a. Decide which servers to preload

Only offer preload for servers that had **at least one tool enumerated in Phase 3** (no point preloading a server with zero live tools). The preload set for each server is the **full Phase 3 enumeration** — `allow` + `ask` + `skip` — because `ToolSearch` friction affects every bucket, not just allowed tools.

Skip this phase entirely if Phase 3 produced an empty preload set across every processed server.

### 7b. Detect existing hook state, then ask only if ambiguous

Inspect both gitignored local settings files for an existing SessionStart hook whose command mentions `ToolSearch` and `select:mcp__`:

- `~/.claude/settings.local.json`
- `./.claude/settings.local.json`

Routing rules (mirror Phase 4b's "infer first, ask only if undetermined"):

| Existing preload hook found in | Action |
|--------------------------------|--------|
| Global only                    | Route to **global**. Merge new tool names into its `select:` list. Do not ask scope. |
| Project only                   | Route to **project**. Merge new tool names into its `select:` list. Do not ask scope. |
| Both scopes                    | Ask via `AskUserQuestion` — state is ambiguous. Surface the other scope as a note in Phase 8. |
| Neither                        | Ask via `AskUserQuestion`: first whether to install the hook at all, then scope if yes. |

**Two separate `AskUserQuestion` calls in the "neither" case** — never combined (one question at a time is mandatory per the interaction rule):

1. **Install?** options:
   - `Yes — install SessionStart preload hook (Recommended)` — description: "Pays ≈1.1k tokens per session so MCP tools are first-class; the alternative `ENABLE_TOOL_SEARCH=false` costs ≈13–16k tokens per session by loading every tool upfront."
   - `No — skip, accept ToolSearch round-trips per call` — description: "Keeps session-start context minimal. The agent may still drift to Bash equivalents when MCP schemas feel expensive to fetch."
2. **Scope?** (only if the user chose Yes) options:
   - `Project (./.claude/settings.local.json) (Recommended)` — description: "Smaller blast radius; easier to revert by deleting the hook entry. Right choice when the servers being registered are project-specific."
   - `Global (~/.claude/settings.local.json)` — description: "One install covers every project on this machine (personal preference — not shared with other contributors since this is gitignored). Right choice when the server is always loaded everywhere (e.g. `git`, `memory-personal`)."

If the user chose **No** on a prior run, re-ask on subsequent runs — hook presence/absence is the only persistent state; don't treat a past decline as permanent.

**Silence on no-ops.** If the inferred-target hook's `select:` list already contains every tool name in the preload set (union equals the current list), there is nothing to write — skip the prompt and report an idempotent no-op.

### 7c. Hook shape

Exactly one SessionStart hook per scope. Matcher covers `startup`, `resume`, and `clear` so the preload fires whenever the session resets:

```jsonc
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "printf '%s' 'Preload MCP tool schemas now: before your next action, call ToolSearch with query \"select:mcp__<server1>__<tool1>,mcp__<server1>__<tool2>,mcp__<server2>__<tool1>,...\" so the schemas are resident and you do not drift to Bash equivalents.'"
          }
        ]
      }
    ]
  }
}
```

Tool names in the `select:` list are **sorted alphabetically** and **comma-separated with no spaces**. Always regenerate the full list from the union of existing + new — don't append — so output is deterministic and dedup-safe.

### 7d. Merge logic

For the chosen scope's `settings.local.json`:

1. If the file doesn't exist: create it with `{"hooks": {"SessionStart": [ … the hook above … ]}}` plus trailing newline.
2. If `hooks.SessionStart` is absent: add the SessionStart array with the single entry.
3. If a SessionStart matcher entry exists whose `hooks[].command` contains `ToolSearch` and `select:mcp__`: replace its `select:...` argument with the union (sorted, deduped) of the existing list and the new preload set. Do not touch any other field of the entry.
4. If SessionStart matcher entries exist but none of their commands contain `ToolSearch`: append a **new** hook entry under its own matcher block rather than mutating unrelated entries. Never clobber hooks owned by other features.
5. Preserve all other keys, entries, formatting, and comments. Use `Edit` with minimal old/new ranges.

### 7e. Preview + confirm

Extend the Phase 5 preview with a `hooks:` block when a write is planned, e.g.:

```
<target file, absolute path>  (settings.local.json — gitignored — personal optimization)
  SessionStart preload:
    + mcp__git__git_add
    + mcp__git__git_commit
    + mcp__git__git_diff
    …
    (merging into existing select: list of N entries → new list of M entries)
  cost: ≈1.1k tokens per session, one-time at session start
```

Request a second confirmation specifically for this write — Phase 5's confirmation covered only permissions + cross-scope cleanup. One tool call per question per Phase 7b.

### 7f. Post-write verification

After the `Edit`/`Write`:

- Re-read the file; assert JSON parses.
- Assert `hooks.SessionStart` exists and contains exactly one entry whose command mentions `ToolSearch`.
- Assert that entry's `select:` list is sorted, deduped, and contains every tool name in the preload set.
- Assert no unrelated hook entry was altered.

### 7g. Safety

- **Gitignored `settings.local.json` only.** Never install this hook into tracked `settings.json`. The preload hook is a personal optimization (≈1.1k tokens/session) whose cost/value each user weighs differently — it must not leak into commits shared with teammates.
- **No arbitrary shell.** The hook's `command` is `printf` (or equivalent `echo`) of a fixed preload-instruction string. Never any other binary, no network calls, no file writes.
- **Union-only mutations.** The hook's `select:` list only ever grows or stays the same during this phase. Removing tools from the preload list is out of scope for `lazy-guard.allow-mcp` — the user does it by hand, or via a future `lazy-guard.revoke-mcp`.
- **Idempotent.** Re-running with the same server set produces no change.

## Phase 8: Report

Print a short summary:

```
## Allow-MCP Result

| Server          | Source      | Target file                        | → allow | → ask | skipped | allow→ask | Removed from tracked | Preload hook |
|-----------------|-------------|------------------------------------|---------|-------|---------|-----------|----------------------|--------------|
| context7        | ./.mcp.json | ./.claude/settings.local.json      |    2    |   0   |    0    |     0     |          0           | project (+2) |
| memory-project  | ./.mcp.json | ./.claude/settings.local.json      |   19    |   6   |    1    |     0     |          3           | project (+26)|
| git             | ~/.mcp.json | ./.claude/settings.local.json      |    9    |   2   |    1    |     3     |          0           | global (+12) |
```

- `→ allow` / `→ ask`: entries newly added to each list this run.
- `skipped`: tools classified as medium-risk and deliberately left out of both lists this run.
- `allow→ask`: destructive tools promoted from a pre-existing (mis-placed) `allow` entry to `ask` **after explicit per-tool confirmation** (Phase 5 step 5).
- `Removed from tracked`: entries stripped from the paired tracked `settings.json` during Phase 6.5a (each removed after explicit confirmation).
- `Removed wrong-scope`: entries stripped from the opposite-scope `settings.local.json` during Phase 6.5b (each removed after explicit confirmation).
- `Preload hook`: scope of the SessionStart preload hook (`global` / `project` / `—` for declined / `—` for no-op), plus the number of tool names added to its `select:` list.

Include notes for:
- **user-pinned skip-bucket entries** — skip-classified tools that were already present in the target file's `allow` or `ask` and were left untouched (informational; not a finding)
- **user-kept allow→ask overrides** — per-tool `keep-in-allow` answers in Phase 5 (user overrode the classifier's promote-to-ask)
- **user-kept leaks** — per-entry `keep` answers in Phase 6.5a / 6.5b (user chose to leave a leak in place)

Include warnings for:
- servers that were defined but had zero tools loaded in this session
- servers the user asked for but weren't discovered
- target files skipped because everything was already allowed (idempotent no-op)

## Non-interactive execution (no user channel)

The setup chain never reaches here headless — `requires_live_session: true` in frontmatter makes `lazy-core.autosetup` skip this skill at discovery (subagents have no live `mcp__*` tools). If some other executor without a user channel runs this skill anyway, every interactive point resolves by inference-or-skip — recorded state applies, nothing preference-shaped is guessed:

- **Server set (Phase 1)** — all discovered servers (the empty-input form).
- **Scope (Phase 4b)** — inferred from existing `mcp__<server>__*` entries exactly per the 4b table. The `Neither` and `Both` rows, and the duplicate-definition prompt, resolve to `needs-interactive: <server> — scope` — that server's writes are skipped entirely.
- **Additions (Phases 5–6)** — `to_allow_new` / `to_ask_new` entries at an inferred scope are a mechanical extension of a recorded trust decision (the operator registered this server's tools at this scope through a previous interactive run; the classifier is deterministic) — write them without the bundled confirmation. The Phase 5 preview renders into the run report and log instead of a confirmation prompt.
- **Reversals (Phase 5 step 5)** — `to_move_to_ask` promotions undo a prior operator choice: never applied; each reports `needs-interactive: <tool> — allow→ask`.
- **Leak cleanup (Phase 6.5)** — removals are per-entry operator decisions: never applied; each found leak reports `needs-interactive`.
- **Preload hook (Phase 7)** — hook already present at exactly one scope → merge the preload set into its `select:` list (union-only growth of a recorded decision, no confirmation). The `Neither` (install at all?) and `Both` (ambiguous) rows → `needs-interactive: preload-hook`.

## Failure modes

- **`/lazy-guard.allow-mcp` stops: "server not found — discovered servers are: …"** — the server name passed as input is not defined in `~/.mcp.json` or `./.mcp.json` → check the server name against the list shown, correct the typo or add the server to `.mcp.json`, then re-run.
- **Server skipped with warning: "server isn't loaded — restart Claude Code and re-run"** — the server is defined in `.mcp.json` but has zero matching tools in the current session → restart Claude Code so the server loads, then re-run `/lazy-guard.allow-mcp`.

## Logging

Log to `./.logs/claude/lazy-guard.allow-mcp/YYYY-MM-DD_HH-MM-SS.md` (UTC timestamp).

Use two separate tool calls: `Bash(mkdir -p ./.logs/claude/lazy-guard.allow-mcp)` then the `Write` tool. Never chain with `&&` or heredoc-redirect.

Frontmatter must include:
- `git_sha` — output of `git rev-parse HEAD` (or `no-git`)
- `git_branch` — output of `git rev-parse --abbrev-ref HEAD` (or `no-git`)
- `date` — UTC timestamp
- `input` — the server names / flags passed in, or `none`

Body sections: `## Actions` (bullet list: files read, servers resolved, scope chosen for global servers, entries added to allow, entries added to ask, entries skipped, entries promoted allow→ask, entries removed from paired tracked settings, preload-hook install choice + scope + tool names added to `select:`, files written) and `## Result` (success / warnings / skipped).

## Safety notes

- **3-bucket classifier.** Safe/reversible → `allow`. Truly destructive → `ask`. Medium-risk → skip (neither list). When uncertain → skip, not allow.
- **Default target is `settings.local.json` (gitignored).** Permissions are personal. Never write per-tool permission entries into tracked `settings.json`.
- **No wildcards.** Enumerate every tool by its exact name. Claude Code matches exact strings in both `allow` and `ask`.
- **Global scope requires explicit user confirmation** via Phase 4b `AskUserQuestion` — but only when the scope is genuinely undetermined. If existing `mcp__<server>__*` entries already pin the server to global or project scope, infer from state and skip the prompt.
- **No-op runs are silent.** If the classifier produces no new writes at the inferred scope, do not ask the scope question and do not request a write confirmation — just report the idempotent no-op.
- **Never silently reverses a user's prior trust choice.** Every `allow`→`ask` promotion requires an explicit per-tool `AskUserQuestion` in Phase 5. Bundling these into a single "approve the whole diff" confirmation is forbidden — a user's prior `allow` entry is a durable choice and must be unmade deliberately, one tool at a time. Skip-bucket pins are stronger still: the skill never even asks about them — a user who pinned a skip-classified tool gets to keep it pinned silently.
- **Phase 6.5 may only remove** `mcp__*` entries, and only after a per-entry `AskUserQuestion`. It cleans two kinds of leak: (6.5a) the paired tracked `settings.json`, and (6.5b) the opposite-scope `settings.local.json`. Never silently flag-and-continue on a leak — ask, then remove or record as user-kept.
- **Never adds non-`mcp__` entries.** **Never removes non-`mcp__` entries.**
- **Confirmation required before every write.** Per-tool confirmations in Phase 5 (allow→ask promotions only) + per-entry confirmations in Phase 6.5 (paired tracked leaks, opposite-scope leaks) + one bundled confirmation for the remaining additions. Phase 7 (SessionStart preload hook) requires its own separate confirmation. Exception: § Non-interactive execution waives the bundled-additions and preload-merge confirmations only — reversals and removals stay operator-gated there too.
- **Phase 7 writes gitignored `settings.local.json`, never tracked `settings.json`.** The preload hook is a personal optimization — ≈1.1k tokens/session cost that each user weighs differently — not universal enablement. Personal-optimization hooks follow the same personal/local rule as permissions.
- **Idempotent.** Re-running adds nothing new when everything is already registered, and removes nothing when no cross-scope leaks remain.
