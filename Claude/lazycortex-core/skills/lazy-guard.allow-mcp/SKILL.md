---
name: lazy-guard.allow-mcp
description: "Add all tools of one or more MCP servers to permissions.allow. Writes to the settings file at the same scope where the server is defined (global ~/.claude/settings.json for ~/.mcp.json servers, project .claude/settings.json for project-defined servers, project settings.local.json when the server is only enabled locally). Use when the user says 'allow context7 mcp', 'allow all mcp tools', 'trust the brave-search MCP server', or similar."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(date -u *), Bash(git rev-parse *)
---

# Allow MCP Server Tools

Append every `mcp__<server>__<tool>` entry for one or more MCP servers to the `permissions.allow` array of the settings file at the **same scope** where the server is defined.

**This skill mutates settings files.** Never write silently — always show the planned diff and get confirmation first.

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

## Phase 3: Enumerate tools per server

For each target server, enumerate every tool name currently available to you in this session whose name matches `mcp__<server>__*`. These strings (full, verbatim, with the double underscores) are what gets written into `permissions.allow`.

**Do NOT invent tool names.** Only use names you can literally see in your active tool list. No wildcards — Claude Code's `permissions.allow` matches `mcp__` entries exactly; a glob like `mcp__context7__*` does not work.

If a server is defined but has zero matching tools in the current session, skip it and warn: the server isn't loaded — the user must restart Claude Code and re-run the skill.

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

## Phase 5: Merge and preview

For each target settings file:

1. Read current JSON. If the file doesn't exist, target content is `{"permissions":{"allow":[]}}`.
2. Compute the entries to add: new `mcp__<server>__<tool>` strings that are NOT already in `permissions.allow`.
3. Print a diff-style preview per file:
   ```
   <absolute path>
     + mcp__<server>__<tool1>
     + mcp__<server>__<tool2>
     ...
   ```
4. Ask the user to confirm before any write. If `--dry-run`, stop here.

## Phase 6: Write

For each approved file:

- If the file exists: use the `Edit` tool with a minimal old/new replacement that adds the new entries at the end of the existing `allow` array. Preserve original formatting, comments, and unrelated keys.
- If the file doesn't exist: use the `Write` tool to create it with exactly `{"permissions":{"allow":[<new entries>]}}` plus a trailing newline.

Never introduce any non-`mcp__*` entries. No `Bash(*)`, no `Edit`, no `Write` — MCP tool names only. The `lazy-guard.settings.py` PreToolUse hook will reject broad or destructive additions.

After writing, re-read each file to verify the JSON still parses and every target entry is present.

## Phase 7: Report

Print a short summary:

```
## Allow-MCP Result

| Server | Source | Target file | Tools added |
|--------|--------|-------------|-------------|
| context7 | ./.mcp.json | ./.claude/settings.json | 2 |
| memory-personal | ~/.mcp.json | ~/.claude/settings.json | 12 |
```

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

Body sections: `## Actions` (bullet list: files read, servers resolved, entries added, files written) and `## Result` (success / warnings / skipped).

## Safety notes

- **No wildcards.** Enumerate every tool by its exact name.
- **Never writes to `~/.claude/settings.local.json`.**
- **Never adds non-`mcp__` entries.**
- **Confirmation required before every write.**
- **Idempotent.** Re-running adds nothing new when everything is already allowed.
