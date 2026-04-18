---
name: lazy-guard.check-public
description: "Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git ls-files*), Bash(mkdir -p *), Bash(date *)
---

# Public Repo Security Audit

Coordinator skill. Dispatches four **Explore** subagents in parallel — one per finding category — merges their findings, applies waivers, presents a unified report, then walks the user through fixes.

See `rules/lazy-core.parallel-scan.md` for the pattern. Severity vocabulary: `FAIL` / `WARN` / `INFO` (and `WAIVED` after waiver matching).

**Read-first**. Never fix silently.

## Phase 1 — Prepare (main session)

### 1a. Get tracked files

```bash
git ls-files
```

### 1b. Load waivers

Read `.guard-waivers.json` from repo root. If absent, use empty waiver set.

**This file also serves as the opt-in signal for the pre-commit hook.** The `lazy-guard.check-public.py` hook only runs in repos that have `.guard-waivers.json` at the root. To enable pre-commit checks, create this file (even with an empty `waivers` array). To disable, remove the file.

Schema:

```json
{
  "version": 1,
  "public_scopes": [
    "Claude/**",
    "README.public.md",
    ".gitignore"
  ],
  "waivers": [
    {
      "pattern": "regex matching the finding text (case-insensitive)",
      "check": "A1|B1|C2|* (check ID or * for all)",
      "scope": "glob for file paths (default: *)",
      "reason": "human-readable justification",
      "added": "YYYY-MM-DD",
      "expires": "YYYY-MM-DD (optional, waiver ignored after this date)"
    }
  ],
  "global_skip_paths": [
    "example/vendored/**/*.js"
  ]
}
```

`public_scopes` (optional, default: empty) narrows the guard to a subtree of the repo. Globs support `**` (any depth) and `*` (single segment), relative to repo root. Absent or empty = legacy whole-repo-public mode (scan everything).

`public_author` (optional, default: absent) records the approved public identity for this repo. Shape: `{ "name": "<string>", "email": <string|null>, "notes": "<string>" }`. When set, B4 matches equal to `public_author.name` (or `public_author.email`, if set) auto-flip to WAIVED in Phase 3. When absent, every B4 match stays WARN and the user must confirm the intended value before any author field is written.

### 1c. Build the scan file list

Apply filters in this order:

1. If `public_scopes` is non-empty, retain only files matching at least one glob.
2. Remove `*.age` files (encrypted).
3. Remove paths matching `global_skip_paths` globs.
4. Remove binary files (images, fonts, compiled assets).

Report: "Scanning N files in public scope (O outside scope, M encrypted, K excluded by skip paths)" — or drop the scope counts if `public_scopes` is empty.

Hand the final file list to every dispatched agent.

## Phase 2 — Dispatch parallel scans

Dispatch these four Explore agents **in a single message with four Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each agent receives the filtered file list from Phase 1, the shared false-positive rules below, and the category-specific patterns. Each must return the structured report from `rules/lazy-core.parallel-scan.md`. Budget: "Report under 400 words".

### Shared false-positive rules (give to every agent)

Before recording any finding, the agent must verify:

1. Match is NOT inside a chezmoi template expression `{{ ... }}` (unless the pattern explicitly says otherwise).
2. Match is NOT a variable reference (`$VAR`, `${VAR}`, `$env.VAR`).
3. Match is NOT in a file excluded by `global_skip_paths` (already filtered out in Phase 1).
4. For `.tmpl` files: only flag **literal** values, not template-rendered references like `{{ index $secrets "..." }}`.

For each finding the agent records: `check_id`, `file_path`, `line_number`, `matched_text` (short), `full_line` (context), suggested `fix` one-liner.

### Agent A — Secrets (FAIL)

- **A1 Private key markers** — `-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----`. Skip `.pub` files.
- **A2 AWS access keys** — `AKIA[0-9A-Z]{16}`.
- **A3 API key/token/password literals** — `(?i)(api[_-]?key|api[_-]?secret|api[_-]?token|password|passwd)\s*[=:"']\s*["']?[A-Za-z0-9_\-/.+]{20,}`. Skip placeholder values (`$VAR`, `${VAR}`, `{{ ... }}`, `<placeholder>`, `YOUR_KEY_HERE`, `changeme`, `xxx`).
- **A4 High-entropy base64 on secret-context lines** — `(?i)(key|token|secret|password|encryption|credential)\s*[=:"']\s*["']?[A-Za-z0-9+/]{32,}={0,2}["']?`. Skip template / variable-reference values.
- **A5 Connection strings with credentials** — `(?i)(mysql|postgres|mongodb|redis|amqp|ftp)://[^@\s]+:[^@\s]+@`.
- **A6 Bearer token literals** — `(?i)bearer\s+[A-Za-z0-9_\-.]{20,}`. Skip inside `{{ ... }}`.

### Agent B — PII (WARN)

- **B1 Email addresses** — `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`. Skip `@example.com`, `@example.org`, `@test.com`, `@localhost`, `noreply@`, `no-reply@`, vendored files (bundled JS/CSS), and `Co-Authored-By` git-trailer lines.
- **B2 Service user IDs in config context** — `(?i)(telegram|tg|user[_-]?id|chat[_-]?id|allow[_-]?from)\s*[=:"'\[]\s*\d{6,12}`. Matches numeric IDs 6–12 digits only when near service/identity keywords.
- **B3 Personal names in git config** — `(?i)name\s*=\s*\w+\s+\w+` (only in `*gitconfig*` files). Severity INFO (expected in dotfiles, still worth flagging).
- **B4 Author identity in manifests** — detect literal author name/email in tracked package manifests and doc files. Patterns:
  - `(?i)"author"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"` — `plugin.json`, `package.json`, `composer.json`.
  - `(?i)"author"\s*:\s*"([^"]+)"` — short form in the same JSON manifests.
  - `(?i)^author(s)?\s*=\s*\[?\s*["']([^"']+)["']` — `pyproject.toml`, `Cargo.toml`.
  - `(?i)^(authors?|name)\s*:\s*(.+)` inside `CITATION.cff`.
  - A plain body line immediately following a `## Author` / `## Authors` heading in `README*.md`.
  Severity WARN. Rationale: legitimate authorship is common but every match is a candidate for identity leakage (real name inferred from `git config` instead of the user's chosen public handle). Skip `@example.com` / placeholder values. See Phase 3 for auto-waive against `public_author`.

### Agent C — Infrastructure (WARN)

- **C1 Tailscale/CGNAT IPs** — `\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b`. Skip inside `{{ ... }}`.
- **C2 Public routable IPs** — `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`, excluding:
  - `127.0.0.0/8` (localhost)
  - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (RFC1918)
  - `0.0.0.0`
  - Well-known DNS: `1.1.1.1`, `1.0.0.1`, `8.8.8.8`, `8.8.4.4`, `9.9.9.9`, `208.67.222.222`, `208.67.220.220`
  - IPs already in C1 (Tailscale range)
  - Vendored files
- **C3 Internal hostnames in SSH/deploy context** — `(?i)(ssh|scp|rsync|ssh-copy-id)\s+.*[\s@]([\w-]+)\b` plus `(?i)^Host\s+([\w-]+)` in SSH config files and `/etc/hosts`-style lines `\d+\.\d+\.\d+\.\d+\s+([\w-]+)`. Skip `github.com`, `gitlab.com`, `bitbucket.org`, `localhost`.

### Agent D — Local repo refs (WARN)

- **D1 Hardcoded absolute user paths** — `/(Users|home)/\w+/`. Skip inside `{{ .chezmoi.homeDir }}` or similar template expressions. Skip comment-only lines explaining path conventions. Severity WARN in config/scripts; INFO in plist files (macOS requires absolute paths).
- **D2 Home subdirectory refs that won't exist for others** — `~/[A-Z][a-zA-Z ]+/` (e.g., `~/Dropbox/`, `~/Docker/`, `~/Documents/`). Skip well-known standard dirs (`~/.ssh/`, `~/.config/`, `~/.local/`, `~/.cache/`). Skip inside `{{ ... }}`.

## Phase 3 — Collect, dedupe, apply waivers (main session)

1. **Parse** each returned block by splitting on `## scan:` headings; merge findings from all four agents.
2. **Deduplicate**: same matched text on multiple lines in the same file becomes one finding with a line range.
3. **Auto-waive B4 against `public_author`** (runs before regex-based waiver matching): for any B4 finding, if `public_author.name` is set and the captured match equals it (or equals `public_author.email`, when `public_author.email` is a non-null string), flip the finding to `WAIVED` with the synthetic reason `matches .guard-waivers.json public_author`. No entry in `waivers[]` is needed for this path.
4. **Apply waivers**: a waiver matches when ALL of:
   - `waiver.check` equals `finding.check_id` OR `waiver.check == "*"`
   - `waiver.scope` glob matches `finding.file_path` (or scope is `"*"`)
   - `waiver.pattern` regex matches `finding.matched_text` (case-insensitive)
   - If `waiver.expires` is set, today's date < expiry
   Matched findings flip to severity `WAIVED`.
5. **Count**: totals per category and severity.

## Phase 4 — Report

```markdown
## lazy-guard.check-public -- Security Audit

**Public scopes**: `Claude/**`, `README.public.md`, `.gitignore`  (or "whole repo" if unset)
**Files scanned**: N in scope (O outside, M encrypted, K excluded)
**Waivers loaded**: W from .guard-waivers.json

| Category | FAIL | WARN | INFO | WAIVED |
|----------|------|------|------|--------|
| A: Secrets | | | | |
| B: PII | | | | |
| C: Infrastructure | | | | |
| D: Local-repo-refs | | | | |
| **Total** | | | | |

### Findings

#### [FAIL] A4: High-entropy base64 (potential key)
**File**: `path/to/file:19`
**Match**: `key_name: "ABCD...XYZ="` (N chars base64)
**Fix**: Move to encrypted secrets store, reference via template variable

#### [WARN] B1: Email address
**File**: `path/to/file:20`
**Match**: `user@example.com`
**Fix**: Template-ize or add waiver if intentionally public

(... one section per finding, FAIL first, then WARN, then INFO ...)

### Fix Strategies

- [ ] S1: Encrypt via secrets pipeline (for plaintext secrets)
- [ ] S2: Template-ize with config data (for infrastructure details)
- [ ] S3: Redact or move PII to secrets/templates
- [ ] S4: Accept with waiver (auto-generate .guard-waivers.json entry)
- [ ] S5: Convert hardcoded path to template expression

Apply which fixes? (list numbers, 'all auto', or 'waivers only')
```

**WAIVED findings**: do NOT show in the report by default. Show the count only; expand details only if the user asks.

## Phase 5 — Fix

For each confirmed fix strategy:

**S1 (Encrypt)**: Guide user through: create 1Password item with `Config` tag, run `sync-secrets.sh`, replace literal with `{{ index $secrets "Name" }}` in template, `chezmoi apply`. If the repo has a `secrets.manage` skill, reference it.

**S2 (Template-ize)**: Replace literal with chezmoi template variable. Rename file to `.tmpl` if needed. Add the value to the appropriate data source (host config, chezmoi data).

**S3 (Redact PII)**: Move to template variable or secrets depending on sensitivity. For git author emails that are intentionally public, suggest S4 instead.

**S4 (Waiver)**: Auto-generate a waiver entry:
```json
{
  "pattern": "<escaped match>",
  "check": "<check_id>",
  "scope": "<file path or glob>",
  "reason": "<ask user for justification>",
  "added": "<today>"
}
```
Show for approval, then append to `.guard-waivers.json` (create file if needed).

**Author identity**: prefer setting `public_author` at the top of `.guard-waivers.json` over writing per-match B4 waivers. One `public_author` record governs every author field under `public_scopes`, survives scope changes, and makes the intended identity discoverable instead of scattering it across waiver entries.

**S5 (Template path)**: Replace `/Users/<name>/` with `{{ .chezmoi.homeDir }}/`. For plist files where absolute paths are required, suggest S4 waiver instead.

After all fixes: re-run the scan (re-dispatch the four agents) to show updated summary.

## Logging

Log to `./.logs/claude/lazy-guard.check-public/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).

Log format:
```markdown
# lazy-guard.check-public

**Date**: YYYY-MM-DD HH:MM:SS UTC
**Input**: <repo path or "current repo">

## Actions

- Scanned N files (skipped M encrypted, K excluded)
- Loaded W waivers
- Found: X FAIL, Y WARN, Z INFO, W WAIVED

## Findings

<full findings list including WAIVED items>

## Fixes Applied

<list of fixes applied, or "none">

## Result

<success/failure, summary>
```
