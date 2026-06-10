---
name: spec.source-url
description: Use to build a single forge-correct source URL for a file in a source repo. Takes `(repo_key, path, kind="blob", branch=None)` and returns the URL using the forge's path scheme from the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. All `spec.*` skills and generator agents MUST go through this primitive — never inline `<base>/blob/<branch>/<path>` or other forge-specific path schemes.
execution-discipline-waiver: "Single-purpose primitive — wraps the known-forges table; no multi-phase orchestration where step-skip can hide."
---
# Source URL

Primitive skill that builds one forge-correct source URL. Every emitter in the system (skills + agents) goes through this call; nobody inlines GitHub-style `/blob/<branch>/<path>` anywhere else.

The authoritative known-forges table (URL template per forge, per kind) lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md` → "Known-forges table". This skill never restates those templates — it reads them.

## Input

1. **Repo key** — a key in the `lazy.settings.json[repos]` section (e.g., `backend`).
2. **Path** — repo-root-relative path to the target file or directory (e.g., `tiv/chapter.py`). No leading slash.
3. **Kind** (optional, default `"blob"`) — `"blob"` for a file URL, `"tree"` for a directory URL.
4. **Branch** (optional, default `None`) — branch override for branch-pinned files. When `None`, the repo's default branch (from the `repos` record) is used.

## Process

### 1. Resolve the repo

Call `spec.resolve-repo(repo_key)` (using the run-scoped cache if available). Get back `RepoInfo` with `base_url`, `forge`, and default `branch`.

### 2. Pick the branch

- If the caller passed `branch`, use that string.
- Else use `RepoInfo.branch`.

### 3. Look up the URL template

Read the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md` → "Known-forges table". Find the row matching `RepoInfo.forge`, and pick the template for the requested `kind` column (`File URL` for `blob`, `Tree URL` for `tree`).

Templates are expressed in terms of `<base>`, `<branch>`, and `<path>`. Substitute:

- `<base>` → `RepoInfo.base_url`
- `<branch>` → the branch chosen in step 2
- `<path>` → the caller-supplied path

No URL encoding is performed on `<path>` — callers pass paths whose segments are already safe (standard source files). If the target file has spaces in its path, the caller must encode them.

### 4. Return

The concatenated URL string.

## Output

A single forge-correct URL, e.g., `https://github.com/Two-Generals/tiv-backend/blob/master/tiv/chapter.py` for a GitHub-hosted `backend`.

For a GitLab-hosted repo, the same call would produce `https://gitlab.com/<owner>/<repo>/-/blob/master/tiv/chapter.py`. For Bitbucket, `…/src/master/tiv/chapter.py`. The shape is decided by the known-forges table, not by the caller.

## Usage patterns

- **Default branch, blob**: `spec.source-url("backend", "tiv/chapter.py")` — most common; skills emitting source links in `tech` files.
- **Default branch, tree**: `spec.source-url("backend", "tiv/", kind="tree")` — directory references.
- **Pinned branch**: `spec.source-url("backend", "tiv/chapter.py", branch="feat/foo")` — when a `tech` or feature `tasks` file pins a branch via `source_branches: backend: feat/foo`.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.source-url/YYYY-MM-DD_HH-MM-SS.md` **only** when this skill is invoked as a top-level call (rare — typically used by humans debugging URL construction). When invoked as a primitive from another skill, the calling skill's log covers the work; do not write a separate log per call.

## Key Rules

- **Never inline forge-specific path schemes.** All of `/blob/…`, `/-/blob/…`, `/src/…`, `/src/branch/…`, `/tree/…/item/…` variants live in the known-forges table — this skill is the only consumer.
- **Never guess the forge.** Delegate to `spec.resolve-repo`, which either detects from hostname or reads the explicit `forge:` override.
- **Never strip or mutate the caller's `path`.** Pass it through verbatim (beyond template substitution).
- **Idempotent** — given the same inputs, always returns the same URL.
