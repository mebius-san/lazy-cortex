---
name: lazy-guard.check-public
description: "Use when auditing a public repo (or a public subtree inside an otherwise private repo) for leaked secrets, PII, infrastructure details, or hardcoded local paths. Run before making a repo/subtree public, after adding new configs, or as a periodic hygiene check. Reads .guard-waivers.json for accepted exceptions and optional `public_scopes` globs."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git ls-files*), Bash(mkdir -p *), Bash(date *)
---

# Public Repo Security Audit

Scan all git-tracked files for content that should not be in a public repository. Collect all findings first, then report and offer fixes.

**This is a read-first skill.** Never fix silently. Show every finding, then ask which fixes to apply.

## Phase 1: Prepare

### 1a. Get tracked files

```bash
git ls-files
```

### 1b. Load waivers

Read `.guard-waivers.json` from repo root. If absent, use empty waiver set.

**This file also serves as the opt-in signal for the pre-commit hook.** The `lazy-guard.check-public.py` hook only runs in repos that have `.guard-waivers.json` at the root. To enable pre-commit checks on a repo, create this file (even with an empty `waivers` array). To disable, remove the file.

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

**`public_scopes`** (optional, default: empty) narrows the guard to a subtree
of the repo. Use this when the repo itself stays private but a specific
subtree (e.g., `Claude/**`) gets published elsewhere — the scan and the
pre-commit hook then only consider files matching one of these globs.
Absent or empty = legacy whole-repo-public mode (scan everything).

Globs support `**` (any depth) and `*` (single path segment). Paths are
evaluated relative to the repo root.

### 1c. Filter file list

Apply filters in this order:

1. If `public_scopes` is non-empty, **retain only** files matching at least
   one of the globs. Everything outside is implicitly private and skipped.
2. Remove `*.age` files (encrypted)
3. Remove paths matching `global_skip_paths` globs
4. Remove binary files (images, fonts, compiled assets)

Report: "Scanning N files in public scope (O outside scope, M encrypted, K excluded by skip paths)"

When `public_scopes` is empty, drop the "in public scope" / "outside scope"
numbers from the report and fall back to "Scanning N files (skipped M
encrypted, K excluded by skip paths)".

## Phase 2: Scan

Run each check using Grep with `output_mode: "content"`. For each match, record: `check_id`, `file_path`, `line_number`, `matched_text`, `full_line`.

### Category A: Secrets (FAIL)

**A1: Private key markers**
- Pattern: `-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----`
- Skip: `.pub` files

**A2: AWS access keys**
- Pattern: `AKIA[0-9A-Z]{16}`

**A3: API key/token/password literals**
- Pattern: `(?i)(api[_-]?key|api[_-]?secret|api[_-]?token|password|passwd)\s*[=:"']\s*["']?[A-Za-z0-9_\-/.+]{20,}`
- Skip if value is: `$VAR`, `${VAR}`, `{{ ... }}`, `<placeholder>`, `YOUR_KEY_HERE`, `changeme`, `xxx`
- Skip if value starts with `$` or `{{`

**A4: High-entropy base64 on secret-context lines**
- Pattern: `(?i)(key|token|secret|password|encryption|credential)\s*[=:"']\s*["']?[A-Za-z0-9+/]{32,}={0,2}["']?`
- Skip: lines inside `{{ ... }}` template expressions
- Skip: lines where value is a variable reference

**A5: Connection strings with credentials**
- Pattern: `(?i)(mysql|postgres|mongodb|redis|amqp|ftp)://[^@\s]+:[^@\s]+@`

**A6: Bearer token literals**
- Pattern: `(?i)bearer\s+[A-Za-z0-9_\-.]{20,}`
- Skip: inside `{{ ... }}`

### Category B: PII (WARN)

**B1: Email addresses**
- Pattern: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- Skip: `@example.com`, `@example.org`, `@test.com`, `@localhost`, `noreply@`, `no-reply@`
- Skip: vendored/third-party files (JS/CSS bundles)
- Skip: `Co-Authored-By` lines (standard git trailer)

**B2: Service user IDs in config context**
- Pattern: `(?i)(telegram|tg|user[_-]?id|chat[_-]?id|allow[_-]?from)\s*[=:"'\[]\s*\d{6,12}`
- This catches numeric IDs (6-12 digits) only when near service/identity keywords

**B3: Personal names in git config**
- Pattern: `(?i)name\s*=\s*\w+\s+\w+` (in `*gitconfig*` files only)
- Severity: INFO (expected in dotfiles, but worth flagging)

### Category C: Infrastructure (WARN)

**C1: Tailscale/CGNAT IPs**
- Pattern: `\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b`
- Skip: inside `{{ ... }}`

**C2: Public routable IPs**
- Pattern: `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`
- After matching, **exclude** these safe ranges:
  - `127.0.0.0/8` (localhost)
  - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (RFC1918)
  - `0.0.0.0`
  - Well-known DNS: `1.1.1.1`, `1.0.0.1`, `8.8.8.8`, `8.8.4.4`, `9.9.9.9`, `208.67.222.222`, `208.67.220.220`
- Also exclude IPs already caught by C1 (Tailscale range)
- Skip: vendored files

**C3: Internal hostnames in SSH/deploy context**
- Pattern: `(?i)(ssh|scp|rsync|ssh-copy-id)\s+.*[\s@]([\w-]+)\b` — hostnames in SSH commands
- Additional: `(?i)^Host\s+([\w-]+)` in SSH config files
- Additional: `/etc/hosts`-style lines `\d+\.\d+\.\d+\.\d+\s+([\w-]+)`
- Skip well-known hosts: `github.com`, `gitlab.com`, `bitbucket.org`, `localhost`

### Category D: Local Repo Refs (WARN)

**D1: Hardcoded absolute user paths**
- Pattern: `/(Users|home)/\w+/`
- Skip: inside `{{ .chezmoi.homeDir }}` or similar template expressions
- Skip: lines that are purely comments explaining path conventions
- Severity: WARN in config/scripts; INFO in plist files (macOS requires absolute paths)

**D2: Home subdirectory refs that won't exist for others**
- Pattern: `~/[A-Z][a-zA-Z ]+/` (e.g., `~/Dropbox/`, `~/Docker/`, `~/Documents/`)
- Skip: well-known standard dirs: `~/.ssh/`, `~/.config/`, `~/.local/`, `~/.cache/`
- Skip: inside `{{ ... }}`

### False positive mitigation (all checks)

Before recording any finding, verify:
1. The match is NOT inside a chezmoi template expression `{{ ... }}` (unless the check specifically says otherwise)
2. The match is NOT a variable reference (`$VAR`, `${VAR}`, `$env.VAR`)
3. The match is NOT in a file excluded by `global_skip_paths`
4. For `.tmpl` files: only flag **literal** values, not template-rendered references like `{{ index $secrets "..." }}`

## Phase 3: Analyze

1. **Deduplicate**: same matched text appearing on multiple lines in the same file becomes one finding with a line range
2. **Apply waivers**: for each finding, check all waivers. A waiver matches when ALL of:
   - `waiver.check` equals `finding.check_id` OR `waiver.check == "*"`
   - `waiver.scope` glob matches `finding.file_path` (or scope is `"*"`)
   - `waiver.pattern` regex matches `finding.matched_text` (case-insensitive)
   - If `waiver.expires` is set, today's date < expiry
3. **Count**: totals per category and severity

## Phase 4: Report

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

**WAIVED findings**: do NOT show in the report by default. Mention the count only. Show details if user asks.

## Phase 5: Fix

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

**S5 (Template path)**: Replace `/Users/<name>/` with `{{ .chezmoi.homeDir }}/`. For plist files where absolute paths are required, suggest S4 waiver instead.

After all fixes: re-run the scan to show updated summary.

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
