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

`.guard-waivers.json` supports an optional top-level `public_scopes` array of path globs. When present, the scan and the pre-commit hook only consider files matching one of the globs — everything else in the repo is implicitly private and ignored by the guard.

This lets an otherwise-private repo publish only a subtree (e.g., `Claude/**`) to an external mirror without having to flip the whole repo public. When `public_scopes` is set:

- `lazy-guard.check-public` reports findings only for files inside the scope
- The pre-commit hook blocks/warns only on staged lines inside the scope
- `lazy-repo.mark-public` does NOT flip GitHub visibility — the repo stays private; only the scoped subtree is treated as public

Globs support `**` (any depth) and `*` (single path segment). Paths are evaluated relative to the repo root.

In this dev repo, `public_scopes` is `["Claude/**", "README.public.md", ".gitignore"]` because only those paths ship to the public mirror via the `pub.publish` skill.
