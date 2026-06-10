---
name: spec.resolve-repo
description: Use to resolve a repo key (e.g., `backend`, `shared`) to its runtime metadata by reading the cross-plugin `lazy.settings.json[repos]` section and inspecting the local checkout's git remote. Returns `{local_path, branch, remote_url, host, owner, repo, forge, base_url}`. The forge type is derived from the remote's hostname via the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`; an explicit `forge:` override in the repo record is honored for self-hosted instances.
execution-discipline-waiver: "Single-purpose primitive — resolves one repo key against repo-config + known-forges; no multi-phase orchestration where step-skip can hide."
---
# Resolve Repo

Primitive skill that turns a repo key into everything needed to build source URLs for that repo. Callers never inspect git remotes themselves; they call this skill once per repo per run and cache the result.

The authoritative definitions (the `repos` settings section shape, known-forges table) live in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` and `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. This skill never restates those tables — it reads them.

## Input

1. **Repo key** — a string matching a key under the cross-plugin `lazy.settings.json[repos]` section (e.g., `backend`, `shared`).

## Process

### 1. Load the repo record

Read the cross-plugin `repos` section:

```bash
lazycortex-core settings-get repos
```

The command prints the `repos` object — each key is a repo key, each value a record. Select the record under `<repo>` and read:

- `local_path` (required) — absolute path to the local checkout.
- `branch` (required) — default branch to link against.
- `forge` (optional) — explicit forge key override; only used when the hostname is not in the known-forges table.

If `<repo>` is not a key in the `repos` section, abort with a message telling the user to register the repo via `/spec.product-config` (the wizard that writes `lazy.settings.json[repos][<repo>]`).

If the record is present but `local_path` or `branch` is missing, abort with a message naming the incomplete record (`local_path` + `branch` are required, `forge` optional).

### 2. Get the remote URL

Run `git -C <local_path> remote get-url origin`.

- If that fails (no `origin`), run `git -C <local_path> remote` and take the first listed remote. Then `git -C <local_path> remote get-url <that-remote>`.
- If there are no remotes at all, abort with a clear error: "no git remotes configured at `<local_path>` — `spec.*` skills need at least one remote to build source URLs".

### 3. Normalize the URL

Convert SSH form to HTTPS:

- `git@host:owner/repo(.git)?` → `https://host/owner/repo`
- `ssh://git@host[:port]/owner/repo(.git)?` → `https://host/owner/repo`
- `https://host/owner/repo(.git)?` → `https://host/owner/repo` (strip trailing `.git`)

Strip any trailing `.git` suffix. Strip any trailing `/`. The result is a clean `https://<host>/<owner>/<repo>` URL.

### 4. Parse host, owner, repo

Split the normalized URL:

- `host` = the hostname segment (e.g., `github.com`, `gitlab.company.example`).
- `owner` = the first path segment after the host.
- `repo` = the second path segment.

Nested groups (GitLab subgroups) are not supported in this first pass — `owner/repo` is assumed to be two segments. If the path has more than two segments, abort with a descriptive error.

### 5. Detect forge

- If the repo record sets an explicit `forge:`, use it as the forge key (validate it against the known-forges table; unknown key → abort).
- Else, look up `host` in the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md` → "Known-forges table" (hostname-match column).
- If the host is not in the table and no explicit `forge:` was set, abort with: "unknown forge for host `<host>` on repo `<key>`. Add `forge: <key>` to `lazy.settings.json[repos][<key>]` — supported keys: `github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`."

### 6. Build base_url

`base_url = https://<host>/<owner>/<repo>` (never a trailing slash, never `.git`).

### 7. Return

```text
{
  local_path: <string>,
  branch:     <string>,
  remote_url: <normalized https URL>,
  host:       <string>,
  owner:      <string>,
  repo:       <string>,
  forge:      <forge key>,
  base_url:   <string>,
}
```

## Caching

Within a single skill run, cache results by repo key. Skills that resolve the same repo many times (e.g., `ref.gen-api` emitting hundreds of source URLs for Backend) MUST NOT re-shell-out per URL. The cache has run-scope only — it is not persisted to disk.

## Output

The `RepoInfo` record above. Callers pass the repo key and path to `spec.source-url` to get a forge-correct URL.

## Failure modes

- **`/spec.resolve-repo` aborts: repo key not registered** — `<key>` is not a key in `lazy.settings.json[repos]` → register the repo via `/spec.product-config`, then re-run.
- **`/spec.resolve-repo` aborts: missing `local_path` or `branch`** — the `repos[<key>]` record is incomplete → add `local_path:` and `branch:` to the record (optionally `forge:`) via `/spec.product-config` and re-run.
- **`/spec.resolve-repo` aborts: "no git remotes configured"** — `git remote` returned nothing for the checkout at `<local_path>` → add at least one remote (`git remote add origin <url>`) and re-run.
- **`/spec.resolve-repo` aborts: nested GitLab subgroup path** — the remote URL path has more than two segments (`owner/group/repo`) → nested subgroups are not yet supported; use an explicit `forge:` override and a two-segment owner/repo or wait for subgroup support.
- **`/spec.resolve-repo` aborts: unknown forge** — the remote's hostname is not in the known-forges table and no `forge:` key is set in the record → add `forge: <key>` (one of `github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`) to `lazy.settings.json[repos][<key>]`.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.resolve-repo/YYYY-MM-DD_HH-MM-SS.md`. Note in Actions: which repo key was resolved, the remote URL, and the detected forge.

## Key Rules

- **Never hardcode GitHub assumptions.** The remote URL is the single source of truth.
- **Never infer a default branch from git.** The config's `branch` is authoritative — it reflects what the spec system links to, which may differ from the repo's HEAD.
- **Never write to the `repos` section from this skill.** Only read.
- **Abort fast on ambiguity** — an unknown forge with no explicit override is a configuration error, not something to silently guess.
- **Idempotent** — repeated calls with the same key return the same record; nothing on disk changes.
