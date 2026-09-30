---
description: Security constraints that the lazy-guard.* scanners and pre-commit hooks enforce — credential safety, secret blocking everywhere, and public-repo readiness.
always_loaded: safety posture applied to every action
---
# Guard Security

Constraints backing the `lazy-guard.check-public` skill, the `lazy-repo.mark-public` workflow, and the `lazy-guard.secrets` / `lazy-guard.check-public` pre-commit hooks.

## Credentials

**NEVER read, list, copy, or transfer authentication credentials, tokens, or session files** (`~/.claude/`, `~/.config/`, OAuth tokens, API keys in auth stores) between machines. Auth is per-machine — the user handles it interactively.

## Secrets (every repo)

- **Secrets (FAIL)** — private keys, AWS access keys, API key/token/password literals, high-entropy base64 on secret-context lines, connection strings with credentials, bearer tokens. Resolve (encrypt, template-ize, redact) before committing. Never waive a real secret; waivers cover only false positives (e.g. test fixtures with fake keys).
- The `lazy-guard.secrets` pre-commit hook blocks these in **every** repo, public or private — no opt-in file; silenced only via `hooks.disabled` in `lazy.settings.json`.

## Public repos

A repo that is (or will be) public must pass the guard scan before going public, and on every commit once public:

- **PII / infrastructure / local paths (WARN)** — email addresses, service user IDs, Tailscale/public IPs, internal hostnames, hardcoded `/Users/…` or `~/Dropbox/…`-style paths. Resolve or waive with a documented reason. Enforced by the `lazy-guard.check-public` pre-commit hook in repos marked public.

## Waivers

Accepted exceptions live in `.guard-public.json` at the repo root — each entry records the check ID, scope glob, match pattern, reason, date added, and optional expiry. The file also marks the repo as (partially) public: the `lazy-guard.check-public` hook runs only where it exists (`lazy-repo.mark-public` creates it; even an empty `waivers` array enables scanning, deleting the file disables it). The `lazy-guard.secrets` hook ignores the marker — it runs everywhere.

## Public scopes (subtree-public mode)

An optional top-level `public_scopes` array of repo-relative path globs narrows the scan and the `lazy-guard.check-public` hook to matching files; everything else is implicitly private. `lazy-repo.mark-public` with `public_scopes` skips the GitHub-visibility flip.

## Author metadata

Author name/email in tracked manifests (`plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `README`, `CITATION.cff`, etc.) is identity leakage. Never infer an author from `git config`, past commits, or system accounts — the local identity is often the user's real name. Ask the user for the public identity on first use, record it as `public_author` in `.guard-public.json`, and read that block on every later write; `lazy-guard.check-public` B4 flags every other author literal as WARN.
