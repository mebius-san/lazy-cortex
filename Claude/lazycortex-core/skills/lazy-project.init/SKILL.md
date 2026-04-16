---
name: lazy-project.init
description: "Bootstrap Claude Code project settings for a new or existing repo. Creates .claude/settings.json with tracked permissions (Skill, MCP tools) and .claude/settings.local.json with machine-local permissions (Edit, Write, Bash, WebSearch). Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(date *)
---

# Project Settings Init

Create or update `.claude/settings.json` and `.claude/settings.local.json` with a standard permission template.

## What goes where

**`settings.json`** (git-tracked) — permissions any contributor needs:
- `Skill` — allow all plugin skills without prompting
- All MCP server tools that are enabled for the project

**`settings.local.json`** (gitignored) — machine-specific permissions:
- `Edit` — edit files without prompting
- `Write` — write files without prompting
- `Bash` — run bash commands without prompting
- `WebSearch` — search the web without prompting
- `additionalDirectories` — if the project works with other local repos
- `enabledMcpjsonServers` — which MCP servers from `.mcp.json` to activate

## Steps

### 1. Discover MCP servers

Read `.mcp.json` (project) and `~/.mcp.json` (global) to find all available MCP server names.

For each server, discover its tools by checking system context or known tool patterns:
- `context7` -> `mcp__context7__resolve-library-id`, `mcp__context7__query-docs`
- `brave-search` -> `mcp__brave-search__brave_web_search`, `mcp__brave-search__brave_local_search`
- `git` -> `mcp__git__git_status`, `mcp__git__git_log`, `mcp__git__git_diff`, `mcp__git__git_diff_staged`, `mcp__git__git_diff_unstaged`, `mcp__git__git_show`, `mcp__git__git_branch`, `mcp__git__git_checkout`, `mcp__git__git_create_branch`, `mcp__git__git_add`, `mcp__git__git_commit`, `mcp__git__git_reset`
- For other servers: use `mcp__<server-name>__*` wildcard pattern

### 2. Ask the user

Ask:
- Should `Bash(git push *)` be in settings.local.json allow (auto-push) or ask list? Default: ask.
- Any additional directories to include?
- Any extra permissions needed?

### 3. Create/update settings.json

```json
{
  "permissions": {
    "allow": [
      "Skill",
      ...MCP tool entries from step 1...
    ]
  }
}
```

Do NOT include `model` — that's a user preference, not a project default.

If `settings.json` already exists, merge: add missing entries to the allow list, don't remove existing ones.

### 4. Create/update settings.local.json

```json
{
  "permissions": {
    "allow": [
      "Edit",
      "Write",
      "Bash",
      "WebSearch"
    ],
    "additionalDirectories": [
      ...if any...
    ]
  },
  "enabledMcpjsonServers": [
    ...all discovered server names...
  ]
}
```

If user wants auto-push, add `"Bash(git push *)"` to the allow list.

If `settings.local.json` already exists, merge carefully: preserve `additionalDirectories` and `enabledMcpjsonServers`, add missing permission entries.

### 5. Ensure .gitignore

Check that `.gitignore` contains `.claude/settings.local.json`. If not, ask to add it.

### 6. Report

Show the created/updated files and their contents.

## Logging

Log to `./.logs/claude/lazy-project.init/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
