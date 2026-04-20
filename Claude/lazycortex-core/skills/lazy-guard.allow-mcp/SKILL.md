---
name: lazy-guard.allow-mcp
description: "Register tools of one or more MCP servers in Claude Code settings using a 3-bucket classifier — safe/reversible tools into permissions.allow (no prompt), truly destructive tools into permissions.ask (always prompt), and medium-risk tools skipped entirely so Claude Code prompts once per call and the user decides. Writes to settings.local.json (gitignored) by default to keep personal permissions out of tracked settings shared with teammates. For globally defined servers, asks whether to register at the global scope (~/.claude/settings.local.json) or per-project (./.claude/settings.local.json). Also strips redundant mcp__ entries from paired tracked settings.json after promotion. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(date -u *), Bash(git rev-parse *)
---

# Register MCP Server Tools

Register `mcp__<server>__<tool>` entries for one or more MCP servers using a **3-bucket classifier**:

- **`permissions.allow`** — safe/reversible tools. No prompt. Reads + low-risk writes the user has judged acceptable.
- **`permissions.ask`** — truly destructive tools (irreversible data loss, remote state mutation). Prompt every call.
- **Skip** — medium-risk tools. **Neither list.** Claude Code falls back to its built-in per-call prompt so the user decides in-context.

**Default target: `settings.local.json` (gitignored), not `settings.json` (tracked).** Permission choices are personal and machine-local — they must not leak into commits that teammates inherit. The skill writes to `settings.json` only when the user explicitly opts in (rare).

**Never write silently** — always show the planned diff (allow adds, ask adds, skipped tools, cross-scope cleanup) and get confirmation first.

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

- **Skip (medium-risk — neither list).** The tool has real consequences but is neither trivially reversible nor catastrophic. Examples: `git_commit` (creates a new commit — reversible locally with `reset`, but worth an acknowledgement per run), `cancel_operation`, network-side creates without a straightforward undo. **Do not write these to either list.** Claude Code will prompt the first time and remember the user's per-call choice.

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
2. For the servers routed to this file, compute five disjoint sets:
   - `to_allow_new     = allow-tools  \ current permissions.allow` (excluding any already in `ask` — handled by `to_move`).
   - `to_ask_new       = ask-tools    \ current permissions.ask`   (excluding any already in `allow` — handled by `to_move`).
   - `to_remove_skip   = skip-tools   ∩ (current permissions.allow ∪ current permissions.ask)` — medium-risk tools that were previously pinned. Remove from whichever list they're in; do not re-add.
   - `to_move_to_ask   = { t : classifier(t)=="ask"   AND t ∈ permissions.allow }` — truly-destructive tools that are currently (mis-)allowed. Remove from `allow`, add to `ask`.
   - `to_move_to_allow = { t : classifier(t)=="allow" AND t ∈ permissions.ask }` — safe tools pinned to always-prompt. A valid user choice (stricter than the heuristic), so **do NOT move these automatically**. Surface as an info note only: "<tool> is in ask but classified as allow — left as-is (stricter than default)".
3. Compute **cross-scope duplicates** to strip (Phase 6.5): for each server whose target is `settings.local.json`, inspect the paired tracked `settings.json` and list any `mcp__<server>__*` entry still there. Tracked settings shouldn't own per-tool permissions, so anything found is a leak to clean up.
4. Print a diff-style preview per file:
   ```
   <target file, absolute path>  (settings.local.json — gitignored)
     allow:
       + mcp__<server>__<safe-tool>            # new
       - mcp__<server>__<destructive-tool>     # promoting to ask
       - mcp__<server>__<medium-risk-tool>     # removing (now skip — Claude Code will prompt per call)
     ask:
       + mcp__<server>__<destructive-tool>     # new
       + mcp__<server>__<destructive-tool>     # promoted from allow
       - mcp__<server>__<medium-risk-tool>     # removing (now skip)
     skip (not written anywhere):
       mcp__<server>__<medium-risk-tool-1>
       mcp__<server>__<medium-risk-tool-2>
     notes:
       mcp__<server>__<safe-tool> is in ask but classified as allow — left as-is

   <paired tracked file, absolute path>  (settings.json — tracked — cleaning up leak)
     allow:
       - mcp__<server>__<any>                  # permissions belong in settings.local.json
     ask:
       - mcp__<server>__<any>
   ```
   Omit any sub-block with no entries.
5. Ask the user to confirm before any write. One confirmation covers: additions to both lists, promotions from allow→ask, skip-category removals, and tracked-scope cleanup. If `--dry-run`, stop here.

## Phase 6: Write

For each approved file:

- If the file exists: use the `Edit` tool to apply the changes from Phase 5, in order:
  1. Remove `to_remove_skip ∪ to_move_to_ask` entries from the `allow` array.
  2. Remove `to_remove_skip` entries from the `ask` array.
  3. Append `to_allow_new` entries to the `allow` array.
  4. Append `to_ask_new ∪ to_move_to_ask` entries to the `ask` array (creating the array if absent).
  Preserve original formatting, comments, and unrelated keys. Separate `Edit` calls per array are acceptable when ranges don't overlap.
- If the file doesn't exist: use the `Write` tool to create it with `{"permissions":{"allow":[<to_allow_new>],"ask":[<to_ask_new>]}}` plus a trailing newline. Omit either key if its list is empty.

Never introduce any non-`mcp__*` entries. No `Bash(*)`, no `Edit`, no `Write` — MCP tool names only. The `lazy-guard.settings.py` PreToolUse hook will reject broad or destructive additions to `allow`.

After writing, re-read each file and assert:
- JSON still parses.
- Every `to_allow_new` entry is now in `allow`.
- Every `to_ask_new` and `to_move_to_ask` entry is now in `ask`.
- No `to_move_to_ask` entry remains in `allow`.
- No `to_remove_skip` entry remains in either list.
- No tool appears in both lists simultaneously.

## Phase 6.5: Strip cross-scope leaks from tracked settings

Permission entries should not live in tracked `settings.json`. Once the target `settings.local.json` owns the entries, strip any redundant `mcp__<server>__*` entries from the paired tracked `settings.json`.

For each server processed this run:

1. Identify the **target** (a `settings.local.json`, per Phase 4).
2. Identify the paired **tracked** file:
   - Target = `./.claude/settings.local.json` → Tracked = `./.claude/settings.json`.
   - Target = `~/.claude/settings.local.json` → Tracked = `~/.claude/settings.json`.
3. Load the tracked file. Skip if it doesn't exist or both `permissions.allow` and `permissions.ask` are empty/absent for this server.
4. Compute removals (both arrays are candidates; entries for servers processed this run only):
   - `to_remove_tracked_allow = { e ∈ tracked.permissions.allow : e startswith "mcp__<server>__" }`
   - `to_remove_tracked_ask   = { e ∈ tracked.permissions.ask   : e startswith "mcp__<server>__" }`
   The removal is unconditional: tracked `settings.json` should not carry per-tool permission entries at all. Any matching entry is a leak regardless of whether the target file already has it.
5. If both sets are empty, skip this file.
6. Use `Edit` with minimal old/new replacements that drop only those entries. Preserve every other key, entry, and formatting detail. If a removal empties an array, leave `"allow": []` / `"ask": []` — do not delete the key.
7. Re-read the file; assert JSON still parses and each removed entry is gone.

Safety:

- Never removes non-`mcp__` entries.
- Never removes entries for servers not processed in the current run.
- Pure subtraction → idempotent on re-run.

## Phase 7: Report

Print a short summary:

```
## Allow-MCP Result

| Server          | Source      | Target file                        | → allow | → ask | skipped | allow→ask | Removed from tracked |
|-----------------|-------------|------------------------------------|---------|-------|---------|-----------|----------------------|
| context7        | ./.mcp.json | ./.claude/settings.local.json      |    2    |   0   |    0    |     0     |          0           |
| memory-project  | ./.mcp.json | ./.claude/settings.local.json      |   19    |   6   |    1    |     0     |          3           |
| git             | ~/.mcp.json | ./.claude/settings.local.json      |    9    |   2   |    1    |     3     |          0           |
```

- `→ allow` / `→ ask`: entries newly added to each list this run.
- `skipped`: tools classified as medium-risk and deliberately left out of both lists this run.
- `allow→ask`: destructive tools promoted from a pre-existing (mis-placed) `allow` entry to `ask`.
- `Removed from tracked`: entries stripped from the paired tracked `settings.json` during Phase 6.5.

Include warnings for:
- servers that were defined but had zero tools loaded in this session
- servers the user asked for but weren't discovered
- target files skipped because everything was already allowed (idempotent no-op)

## Logging

Log to `./.logs/claude/lazy-guard.allow-mcp/YYYY-MM-DD_HH-MM-SS.md` (UTC timestamp).

Use two separate tool calls: `Bash(mkdir -p ./.logs/claude/lazy-guard.allow-mcp)` then the `Write` tool. Never chain with `&&` or heredoc-redirect.

Frontmatter must include:
- `git_sha` — output of `git rev-parse HEAD` (or `no-git`)
- `git_branch` — output of `git rev-parse --abbrev-ref HEAD` (or `no-git`)
- `date` — UTC timestamp
- `input` — the server names / flags passed in, or `none`

Body sections: `## Actions` (bullet list: files read, servers resolved, scope chosen for global servers, entries added to allow, entries added to ask, entries skipped, entries promoted allow→ask, entries removed from paired tracked settings, files written) and `## Result` (success / warnings / skipped).

## Safety notes

- **3-bucket classifier.** Safe/reversible → `allow`. Truly destructive → `ask`. Medium-risk → skip (neither list). When uncertain → skip, not allow.
- **Default target is `settings.local.json` (gitignored).** Permissions are personal. Never write per-tool permission entries into tracked `settings.json`.
- **No wildcards.** Enumerate every tool by its exact name. Claude Code matches exact strings in both `allow` and `ask`.
- **Global scope requires explicit user confirmation** via Phase 4b `AskUserQuestion` — but only when the scope is genuinely undetermined. If existing `mcp__<server>__*` entries already pin the server to global or project scope, infer from state and skip the prompt.
- **No-op runs are silent.** If the classifier produces no new writes at the inferred scope, do not ask the scope question and do not request a write confirmation — just report the idempotent no-op.
- **Phase 6.5 may only remove** `mcp__*` entries from the paired tracked `settings.json` — never from unrelated files, never non-`mcp__*` entries.
- **Never adds non-`mcp__` entries.** **Never removes non-`mcp__` entries.**
- **Confirmation required before every write.** One confirmation covers Phase 6 additions + Phase 6.5 tracked-scope cleanup.
- **Idempotent.** Re-running adds nothing new when everything is already registered, and removes nothing when no cross-scope leaks remain.
