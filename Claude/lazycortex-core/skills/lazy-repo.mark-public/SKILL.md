---
name: lazy-repo.mark-public
description: "Use when preparing a local/private repo to become public. Runs the full lazy-guard.check-public-repo audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git ls-files*), Bash(git remote*), Bash(gh repo*), Bash(gh api*), Bash(mkdir -p *), Bash(date *)
---

# Make a Repo Public

End-to-end workflow for taking a private/local repo public. Runs the security audit, resolves all findings, creates the waiver file (which activates the pre-commit hook), and optionally changes GitHub visibility.

## Step 1: Preflight

1. Confirm with the user which repo (default: current working directory)
2. Check it's a git repo: `git remote -v`
3. Check current GitHub visibility: `gh repo view --json visibility -q .visibility`
4. If already public, ask if the user wants to re-audit instead (invoke `/lazy-guard.check-public-repo`)

## Step 2: Run full audit

Invoke the `/lazy-guard.check-public-repo` skill. Follow its full Phase 1-4 (Prepare, Scan, Analyze, Report). Do NOT proceed to Phase 5 (Fix) yet — present the full report first.

## Step 3: Resolve findings

Work through findings by severity:

**FAIL findings (secrets)**: These MUST be resolved before going public. For each:
- Offer fix strategy (S1: encrypt, S2: template-ize, S3: redact)
- Apply the fix
- Verify the finding is gone

**WARN findings (PII, infra, paths)**: For each, ask the user:
- **Fix it** — apply appropriate strategy
- **Waive it** — add to waivers with justification
- **Skip for now** — leave unresolved (will block Step 5)

**INFO findings**: Show for awareness. Auto-waive or skip as user prefers.

If any FAIL findings remain unresolved, do NOT proceed to Step 4.

## Step 4: Create `.guard-waivers.json`

Write the waiver file to the repo root with all accepted waivers from Step 3. This also activates the pre-commit hook (`lazy-guard.check-public-repo.py`) for future commits.

Include `global_skip_paths` for vendored/third-party directories if the audit identified any.

```json
{
  "version": 1,
  "waivers": [
    ...collected from Step 3...
  ],
  "global_skip_paths": [
    ...if any...
  ]
}
```

Commit the waiver file.

## Step 5: Go public

**Only if all FAIL findings are resolved and user confirms.**

Ask: "Ready to make this repo public on GitHub?"

If yes:
```bash
gh repo edit --visibility public
```

If no: tell the user the repo is audit-clean and ready — they can run `gh repo edit --visibility public` when ready.

## Step 6: Post-flight

- Confirm the pre-commit hook is active (`.guard-waivers.json` exists = hook fires)
- Remind: run `/lazy-guard.check-public-repo` periodically or after major changes
- Log results

## Logging

Log to `./.logs/claude/lazy-repo.mark-public/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
