---
description: Security constraints that the lazy-guard.* scanners and pre-commit hook enforce — credential safety and public-repo readiness.
---

# Guard Security

Constraints below back the `lazy-guard.check-public` skill, the `lazy-repo.mark-public` workflow, and the `lazy-guard.check-public` pre-commit hook.

## Credentials

**NEVER read, list, copy, or transfer authentication credentials, tokens, or session files** (`~/.claude/`, `~/.config/`, OAuth tokens, API keys in auth stores) between machines. Auth is per-machine — the user handles it interactively.

## Public repos

A repo that is (or will be) public must pass the guard scan before going public, and on every commit once public:

- **Secrets (FAIL)** — private keys, AWS access keys, API key/token/password literals, high-entropy base64 on secret-context lines, connection strings with credentials, bearer tokens. Resolve (encrypt, template-ize, redact) before publishing. Never waive.
- **PII / infrastructure / local paths (WARN)** — email addresses, service user IDs, Tailscale/public IPs, internal hostnames, hardcoded `/Users/…` or `~/Dropbox/…`-style paths. Resolve or waive with a documented reason.

## Waivers

Accepted exceptions live in `.guard-waivers.json` at the repo root. Each entry records the check ID, scope glob, match pattern, reason, date added, and optional expiry.

**`.guard-waivers.json` also serves as the opt-in signal for the pre-commit hook** — the hook only runs in repos that have this file. Create it (even with an empty `waivers` array) to enable pre-commit scanning; delete it to disable.

## Public scopes (subtree-public mode)

`.guard-waivers.json` supports an optional top-level `public_scopes` array of path globs. When set, the scan and pre-commit hook consider only files matching one of the globs; everything else is implicitly private. Use this to publish a subtree (e.g., `Claude/**`) from an otherwise-private repo — `lazy-repo.mark-public` with `public_scopes` skips the GitHub-visibility flip. Globs support `**` (any depth) and `*` (single segment), relative to the repo root.

## Author metadata

Author name/email in tracked manifests (`plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `README`, `CITATION.cff`, etc.) is identity leakage.

- **Never infer an author** from `git config`, past commits, or system accounts — the local identity is often the user's real name, not what they want published.
- **Ask the user** for the correct public identity on first use, then record it as `public_author` in `.guard-waivers.json` and read that block on every subsequent write. Re-ask if the block is absent.
- **Enforcement**: `lazy-guard.check-public` B4 flags every author literal as WARN and auto-waives only those matching `public_author`.

## Meta-rule

All constraints. New security rules → this file; scanner heuristics and fix procedures → `lazy-guard.check-public/SKILL.md`, `lazy-repo.mark-public/SKILL.md`, and the pre-commit hook.
