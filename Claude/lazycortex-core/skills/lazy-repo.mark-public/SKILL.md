---
name: lazy-repo.mark-public
description: "Use when preparing a local/private repo — or a subtree inside one — to become public. Runs the full lazy-guard.check-public audit, walks through fixes and waivers, creates .guard-waivers.json to enable the pre-commit hook, and optionally flips the repo to public on GitHub. Accepts an optional scope argument to mark a subtree public (e.g., `claude/**`) without touching GitHub visibility."
argument-hint: "[scope-glob ...]  # optional; e.g. 'claude/** README.public.md .gitignore' for subtree-public mode"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git ls-files*), Bash(git remote*), Bash(gh repo*), Bash(gh api*), Bash(mkdir -p *), Bash(date *)
---
# Make a Repo (or Subtree) Public

End-to-end workflow for taking a private/local repo public — or for marking a subtree inside a repo as the "public surface" while the repo itself stays private. Runs the security audit, resolves all findings, creates the waiver file (which activates the pre-commit hook), and in whole-repo mode optionally changes GitHub visibility.

## Step 1: Preflight

1. Confirm with the user which repo (default: current working directory)
2. Check it's a git repo: `git remote -v`
3. Check current GitHub visibility: `gh repo view --json visibility -q .visibility`
4. If already public AND no scope args were given, ask if the user wants to re-audit instead (invoke `/lazy-guard.check-public`)

## Step 1b: Determine scope

Two modes, decided by the argument list:

- **Whole-repo mode** (no args): the entire repo is going public. Proceed with the existing flow; Step 5 may flip GitHub visibility.
- **Subtree-public mode** (one or more glob args, e.g. `claude/** README.public.md .gitignore`): only the listed paths are treated as the public surface. The repo stays private on GitHub; Step 5 is skipped.

Record the chosen scope for use in Steps 2 and 4. Confirm the interpretation back to the user in one line before continuing (e.g., "Scoped mode — auditing `claude/**` only; repo visibility will NOT change").

## Step 2: Run full audit

Invoke the `/lazy-guard.check-public` skill. Follow its full Phase 1-4 (Prepare, Scan, Analyze, Report). Do NOT proceed to Phase 5 (Fix) yet — present the full report first.

**Passing the scope**: if Step 1b selected subtree-public mode, the easiest way to scope the audit is:

1. If `.guard-waivers.json` already exists, read it, add/overwrite `public_scopes` with the Step 1b globs, re-write the file.
2. If it doesn't exist, create a minimal scaffold:
   ```json
   { "version": 1, "public_scopes": [ ... ], "waivers": [] }
   ```

This way the check-public skill and the hook immediately see the scope. The file will be completed with accepted waivers in Step 4.

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

Write the waiver file to the repo root with all accepted waivers from Step 3. This also activates the pre-commit hook (`lazy-guard.check-public.py`) for future commits.

Include `public_scopes` if Step 1b selected subtree-public mode. Include `global_skip_paths` for vendored/third-party directories if the audit identified any.

```json
{
  "version": 1,
  "public_scopes": [ ...from Step 1b, omit in whole-repo mode... ],
  "waivers": [
    ...collected from Step 3...
  ],
  "global_skip_paths": [
    ...if any...
  ]
}
```

Commit the waiver file.

## Step 5: Go public on GitHub (whole-repo mode only)

**Skip this step entirely in subtree-public mode** — the repo stays private; only the scoped subtree is treated as the public surface via whatever publish flow copies it elsewhere. Print: "Scoped mode — repo stays private on GitHub. The guard now protects `<scopes>` on every commit."

**In whole-repo mode**, and only if all FAIL findings are resolved and user confirms:

Ask: "Ready to make this repo public on GitHub?"

If yes:
```bash
gh repo edit --visibility public
```

If no: tell the user the repo is audit-clean and ready — they can run `gh repo edit --visibility public` when ready.

## Step 6: Post-flight

- Confirm the pre-commit hook is active (`.guard-waivers.json` exists = hook fires)
- In subtree-public mode: remind the user the hook now scans only files under the declared `public_scopes` on every commit
- Remind: run `/lazy-guard.check-public` periodically or after major changes
- Log results

## Logging

Log to `./.logs/claude/lazy-repo.mark-public/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
