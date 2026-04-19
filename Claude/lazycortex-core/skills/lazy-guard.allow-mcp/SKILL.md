---
name: lazy-guard.allow-mcp
description: "Register all tools of one or more MCP servers in Claude Code settings — read-only tools into permissions.allow, destructive/mutating tools into permissions.ask so they keep prompting. Writes to the settings file at the same scope where the server is defined (global ~/.claude/settings.json for ~/.mcp.json servers, project .claude/settings.json for project-defined servers, project settings.local.json when the server is only enabled locally). Also strips redundant mcp__ entries from the paired settings.local.json after promotion. Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(date -u *), Bash(git rev-parse *)
---

# Register MCP Server Tools

Register every `mcp__<server>__<tool>` entry for one or more MCP servers in the settings file at the **same scope** where the server is defined — splitting them between `permissions.allow` (read-only tools, no prompt) and `permissions.ask` (destructive tools, always prompt).

**Destructive tools MUST go to `permissions.ask`, never `permissions.allow`.** The point of this skill is to stop per-tool prompts for safe reads while keeping explicit confirmation on anything that mutates state. Silent `allow` of destructive tools defeats that safety and is forbidden.

**This skill mutates settings files.** Never write silently — always show the planned diff (both `allow` and `ask` additions) and get confirmation first.

## Phase 1: Parse input

Accepted input forms:

- `<server-name>` — allow only this server (e.g. `context7`)
- `<server1> <server2> ...` — allow listed servers
- empty / `all` / `*` — allow every discovered server

If the user also passed `--dry-run` (or says "preview"), run all phases except the final `Edit` — just print the planned change.

## Phase 2: Discover MCP servers

Read these files (skip any that don't exist; never create them in this phase):

- `~/.mcp.json` — global MCP server definitions
- `./.mcp.json` — project MCP server definitions
- `~/.claude/settings.json` — check `enableAllProjectMcpServers`
- `./.claude/settings.json` — check `enabledMcpjsonServers`
- `./.claude/settings.local.json` — check local-only `enabledMcpjsonServers`

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

### Classify each tool → `allow` or `ask`

For every enumerated tool, decide whether invoking it *reads* remote/local state or *mutates* it. Use this rule:

- **`permissions.allow` (read-only — no prompt)**: the tool only retrieves, inspects, or searches. Its action name matches one of: `get_*`, `list_*`, `search*`, `query*`, `read*`, `recall*`, `reflect*`, `resolve*`, `diff*`, `status*`, `show*`, `log*` (as a read, e.g. `git_log`), `fetch*`, `refresh*`, `audit*`.
- **`permissions.ask` (destructive/mutating — prompt every time)**: anything that writes, creates, deletes, updates, commits, resets, pushes, or changes persistent state. Action names with: `add*`, `create_*`, `update_*`, `delete_*`, `remove_*`, `clear_*`, `write*`, `commit*`, `reset*`, `push*`, `force*`, `retain*`, `sync_*`, `set_*`, `cancel_*`, `checkout*`, `merge*`, `stash*`, `rebase*`, `restore*`, `revert*`, or any verb you'd consider a mutation.
- **Default when uncertain: `ask`.** Never default to `allow`. If a tool name is ambiguous, the safe choice is to prompt.

Apply the same rule regardless of server. A read-shaped tool on a "dangerous" server still goes to `allow`; a write-shaped tool on a "safe" server still goes to `ask`. Tool-level classification, not server-level trust.

Concrete examples (canonical servers seen in this project):

| Tool name                                   | Bucket  |
|---------------------------------------------|---------|
| `mcp__context7__resolve-library-id`         | allow   |
| `mcp__context7__query-docs`                 | allow   |
| `mcp__brave-search__brave_web_search`       | allow   |
| `mcp__git__git_status` / `git_diff` / `git_log` / `git_show` / `git_branch` | allow |
| `mcp__git__git_add` / `git_commit` / `git_reset` / `git_checkout` / `git_create_branch` | ask |
| `mcp__memory-*__recall` / `reflect` / `get_*` / `list_*` / `refresh_mental_model` | allow |
| `mcp__memory-*__retain` / `sync_retain` / `create_*` / `update_*` / `delete_*` / `clear_memories` / `cancel_operation` | ask |

Build the per-server output as two sets: `to_allow` and `to_ask`.

## Phase 4: Route each server to the correct settings file

Apply this decision table (the "same level" rule):

| Server defined in | Enabled by | Write permissions to |
|---|---|---|
| `~/.mcp.json` | always available | `~/.claude/settings.json` |
| `./.mcp.json` | `enableAllProjectMcpServers: true` in `~/.claude/settings.json` | `./.claude/settings.json` |
| `./.mcp.json` | `enabledMcpjsonServers` in `./.claude/settings.json` | `./.claude/settings.json` |
| `./.mcp.json` | `enabledMcpjsonServers` only in `./.claude/settings.local.json` | `./.claude/settings.local.json` |
| both global and project definitions exist | — | ask the user which scope to target |

Never write MCP permissions to `~/.claude/settings.local.json` — that file should stay empty per the project's configuration hygiene rules.

## Phase 5: Reconcile and preview

The Phase 3 classifier is the source of truth — every `mcp__<server>__*` tool must exist exactly once in the correct list (read→`allow`, write→`ask`). Reconcile, don't just append.

For each target settings file:

1. Read current JSON. If the file doesn't exist, target content is `{"permissions":{"allow":[],"ask":[]}}`.
2. For the servers routed to this file, compute four disjoint sets:
   - `to_allow_new   = read-tools classified to this server   \ current permissions.allow`  (excluding any already in `ask` — covered by "to_move").
   - `to_ask_new     = write-tools classified to this server  \ current permissions.ask`    (excluding any already in `allow` — covered by "to_move").
   - `to_move_to_ask = { t : classifier(t)=="write" AND t ∈ permissions.allow }` — destructive tools that are currently (mis-)allowed. Remove from `allow`, add to `ask`.
   - `to_move_to_allow = { t : classifier(t)=="read" AND t ∈ permissions.ask }` — read tools pinned to always-prompt. This is a valid user choice (they're stricter than the heuristic), so **do NOT move these automatically**. Surface as an info note in the preview only: "<tool> is in ask but classified as read — left as-is (stricter than default)".
3. Also compute **cross-scope duplicates** to strip, per Phase 6.5: for each server whose target is a higher-scope file, inspect the paired `settings.local.json` and list any `mcp__<server>__*` entry that also exists in the higher-scope file's `allow` OR `ask` array.
4. Print a diff-style preview per file:
   ```
   <target file, absolute path>
     allow:
       + mcp__<server>__<read-tool1>          # new
       - mcp__<server>__<write-tool-misplaced># promoting to ask (destructive)
     ask:
       + mcp__<server>__<write-tool1>         # new
       + mcp__<server>__<write-tool-misplaced># promoted from allow

     notes:
       mcp__<server>__<read-tool> is in ask but classified as read — left as-is

   <paired lower-scope file, absolute path>
     allow:
       - mcp__<server>__<tool3>               # redundant with <target file>
     ask:
       - mcp__<server>__<tool4>               # redundant with <target file>
   ```
   Omit any sub-block (allow / ask / notes / lower-scope) with no entries.
5. Ask the user to confirm before any write. One confirmation covers: additions to both lists, promotions from allow→ask, and lower-scope removals. If `--dry-run`, stop here.

## Phase 6: Write

For each approved file:

- If the file exists: use the `Edit` tool to apply the four changes from Phase 5:
  1. Remove `to_move_to_ask` entries from the `allow` array.
  2. Append `to_allow_new` entries to the `allow` array.
  3. Append `to_ask_new ∪ to_move_to_ask` entries to the `ask` array (creating the array if absent).
  Preserve original formatting, comments, and unrelated keys. Separate `Edit` calls per array are acceptable when ranges don't overlap.
- If the file doesn't exist: use the `Write` tool to create it with `{"permissions":{"allow":[<to_allow_new>],"ask":[<to_ask_new>]}}` plus a trailing newline. Omit either key if its list is empty. (Promotions are N/A on a fresh file.)

Never introduce any non-`mcp__*` entries. No `Bash(*)`, no `Edit`, no `Write` — MCP tool names only. The `lazy-guard.settings.py` PreToolUse hook will reject broad or destructive additions to `allow`.

After writing, re-read each file and assert:
- JSON still parses.
- Every `to_allow_new` entry is now in `allow`.
- Every `to_ask_new` and `to_move_to_ask` entry is now in `ask`.
- No `to_move_to_ask` entry remains in `allow`.
- No tool appears in both lists simultaneously.

## Phase 6.5: Strip cross-scope duplicates

Once additions have landed in the higher-scope file, strip the same entries from the paired lower-scope `settings.local.json` — they were redundant the moment the higher-scope file took ownership.

For each server processed this run:

1. Identify the **higher-scope** target (the file Phase 4 picked).
2. Identify the paired **lower-scope** file:
   - Higher = `./.claude/settings.json` → Lower = `./.claude/settings.local.json`.
   - Higher = `~/.claude/settings.json` → no cleanup. `~/.claude/settings.local.json` must stay empty per project hygiene, and the `lazy-guard.settings.py` PreToolUse hook enforces that invariant by blocking any non-empty-producing edit. If it truly is empty (the enforced state), there's nothing to remove; if it somehow isn't, fixing that is out-of-scope here. Skip.
   - Higher = `./.claude/settings.local.json` → no lower scope; skip.
3. Load the lower-scope file. Skip if it doesn't exist or both `permissions.allow` and `permissions.ask` are empty/absent.
4. Compute per-list removals — both arrays are candidates for cleanup:
   - `to_remove_allow = { e ∈ lower.permissions.allow : e startswith "mcp__<server>__" AND e ∈ (higher.permissions.allow ∪ higher.permissions.ask) }`
   - `to_remove_ask   = { e ∈ lower.permissions.ask   : e startswith "mcp__<server>__" AND e ∈ (higher.permissions.allow ∪ higher.permissions.ask) }`
   Only entries owned by servers processed this run qualify — never touch unrelated entries.
5. If both sets are empty, skip this file.
6. Use `Edit` with minimal old/new replacements that drop only those entries. Preserve every other key, entry, and formatting detail. If a removal empties an array, leave `"allow": []` / `"ask": []` — do not delete the key.
7. Re-read the file; assert JSON still parses and each removed entry is gone.

Safety:

- Never removes non-`mcp__` entries.
- Never removes entries for servers not processed in the current run.
- Never removes an entry from the lower-scope file unless the same entry is already present in either list of the higher-scope file.
- Pure subtraction → idempotent on re-run.

## Phase 7: Report

Print a short summary:

```
## Allow-MCP Result

| Server          | Source      | Target file              | → allow | → ask | allow→ask | Removed from local |
|-----------------|-------------|--------------------------|---------|-------|-----------|--------------------|
| context7        | ./.mcp.json | ./.claude/settings.json  |    2    |   0   |     0     |         0          |
| memory-personal | ~/.mcp.json | ~/.claude/settings.json  |    5    |   7   |     0     |         0          |
| obsidian        | ./.mcp.json | ./.claude/settings.json  |    3    |   2   |     0     |         3          |
| git             | ~/.mcp.json | ~/.claude/settings.json  |    0    |   2   |     4     |         0          |
```

- `→ allow` / `→ ask`: entries newly added to each list this run.
- `allow→ask`: destructive tools promoted from a pre-existing (mis-placed) `allow` entry to `ask`. A non-zero value here means the user previously ran with the old "allow everything" behavior and those entries are now being moved to the safer bucket.
- `Removed from local`: entries stripped from the paired `settings.local.json` during Phase 6.5 (across both lists).

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

Body sections: `## Actions` (bullet list: files read, servers resolved, entries added to allow, entries added to ask, entries promoted allow→ask, entries removed from paired local, files written) and `## Result` (success / warnings / skipped).

## Safety notes

- **Destructive → `ask`, never `allow`.** Any tool that writes, creates, deletes, updates, or otherwise mutates state goes to `permissions.ask`. Silent `allow` of destructive MCP tools is forbidden. When in doubt, classify as `ask`.
- **No wildcards.** Enumerate every tool by its exact name. Claude Code matches exact strings in both `allow` and `ask`.
- **Never *adds* to `~/.claude/settings.local.json`** (global local must stay empty — enforced by `lazy-guard.settings.py`).
- **Phase 6.5 may only remove** `mcp__*` entries from `./.claude/settings.local.json` (project local) — never from the global local file, and never entries that aren't also present in the higher-scope file (in either `allow` or `ask`).
- **Never adds non-`mcp__` entries.** **Never removes non-`mcp__` entries.**
- **Confirmation required before every write.** One confirmation covers Phase 6 additions (to both `allow` and `ask`) plus Phase 6.5 removals.
- **Idempotent.** Re-running adds nothing new when everything is already registered, and removes nothing when no cross-scope duplicates remain.
