---
name: spec.sources-protocol
version: 1
description: Contract for external references a spec doc carries — source attribution, source-code links, and product dependencies, with forward-only frontmatter as source of truth.
---
# Sources protocol — attribution, code links, dependencies

Every external reference a spec doc carries goes through one of three channels. They share a single principle: forward-only links in frontmatter as source of truth, optional body-rendering as a projection.

- **Source attribution** (Part 1) — `spec_source_requests` + `spec_source_docs` → `# Sources` H1 section. Records *which inputs contributed* (requests) and *which docs to read alongside* (source-docs).
- **Source-code links** (Part 2) — `spec.source-url` primitive + `spec_source_branches` frontmatter. Centralized forge-URL building and branch pinning for source-code references inside spec prose.
- **Product dependencies** (Part 3) — `products[<key>].dependencies` config + `spec.resolve-dependency` primitive. Informational metadata about upstream products / repos / external tools.

## Part 1 — Source attribution (`spec_source_*` + `# Sources` section)

How an asset (and each of its authored docs) records which external inputs contributed to it AND which reference documents accompany it. Two `spec_source_*` frontmatter keys are sources of truth; the body's `# Sources` H1 section is a human-readable projection of both.

The pattern is cross-spec — every authored doc (asset-level `design.md`, `plan.md`, `bug.md`, plus product-level `design.md`, `tech.md`) and the asset's status folder-note carry the same attribution shape. Today two source kinds contribute — requests (via `spec.request-attach`) and source-docs (via `spec.create-asset` at scaffold time + `spec.refresh-sources` later); the body shape is designed so additional source kinds (external links, RFCs, tickets) can land alongside them without restructuring.

### Frontmatter — `spec_source_requests`

A list of path-qualified wikilinks pointing at request files in the vault-root `requests/` inbox. Forward-only — the reverse link (request → asset) lives in the request's terminal status callout body, not as a separate field.

Lives on:
- every authored spec doc (`design.md`, `plan.md`, `bug.md`, asset-level `tech.md`) — the per-doc subset of requests that contributed to THIS doc;
- the asset's status folder-note — the union of every request that has ever attached to the asset.

`[]` when the doc / asset was created directly (no request origin).

`spec.doctor` validates the forward link: every wikilink resolves to an existing request file under the vault-root `requests/` inbox. Unresolvable wikilinks are a FAIL finding.

### Frontmatter — `spec_source_docs`

A list of path-qualified wikilinks pointing at reference documents that any agent processing this document should see as context. Distinct from `spec_source_requests`: requests record *provenance* (where the doc's content came from); source-docs record *companion references* (what the doc relies on or relates to).

Lives on every authored spec doc (`design.md`, `plan.md`, `bug.md`, asset-level `tech.md`, and product-level `design.md` + `tech.md`). Folder-note (status file) does NOT carry `spec_source_docs` — it's a managed status artifact with gates and `# History`, not content with companion references.

Defaults are written by `spec.create-asset` at scaffold time (see `lazy-specs.functional-spec.md` § «Контекст эксперта при ревью» for the per-doc-role default lists). The operator may extend or trim the list manually.

Wikilinks MUST be **path-qualified** (e.g. `[[<spec_path>/<category>/<slug>/design]]`, not bare `[[design]]`) because asset slugs and doc basenames repeat across the vault — bare `[[design]]` is ambiguous.

Consumers (read-only):
- `lazycortex-review` dispatcher resolves each wikilink and ships the resolved file into the expert's `context/` payload (read-only) at dispatch time;
- `lazy-wiki` curator and `spec.doctor` may read `spec_source_docs` for their own cross-referencing.

`spec.doctor` validates: every wikilink resolves to an existing file in the vault. Unresolvable wikilinks are a FAIL finding.

### Body — `# Sources` H1 section

An H1 section at the end of every populated authored doc body. It is a container; sub-sections under it carry the actual entries grouped by source kind.

```markdown
# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
- [[<request-wikilink>|<display>]] — <YYYY-MM-DD>
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
- [[<doc-wikilink>|<display>]]
<!-- auto:spec-docs:end -->
```

Three layers of ownership, each load-bearing:

| Layer | Role |
|---|---|
| H1 heading `# Sources` | Section boundary; visible in the doc outline, sibling of `# History` (the lazy-review historian's audit section). The container itself carries no managed inner content — it just hosts the per-kind sub-sections below. |
| Owner tag `#protected/spec/sources` on the first content line | Cross-plugin signal honoured by `lazy-review.finalize` — the entire section survives finalize byte-for-byte. Specs is the only writer of the section's contents; foreign plugins must not touch it. |
| Per-sub-section HTML markers `<!-- auto:spec-<kind>:start --> / :end -->` | Mechanical rewrite boundary scoped to one sub-section. Each automated source kind gets its own marker pair; the writer for that kind owns ONLY the bytes between its pair. Sub-sections without markers (operator-authored kinds, e.g. a hand-curated `## External links`) are preserved untouched and may freely coexist with auto-managed sub-sections under the same `# Sources` container. |

#### `## Requests` sub-section — projection from frontmatter

The bullet list between `<!-- auto:spec-requests:start --> / :end -->` is a deterministic projection of `spec_source_requests`:

- one bullet per wikilink, in the same order as the frontmatter list;
- bullet format: `- [[<request-wikilink>|<display>]] — <YYYY-MM-DD>` where the date is the day the wikilink first appeared in the frontmatter;
- duplicates dedupe on the wikilink (the date stays from the first appearance).

`spec.request-attach` is the writer. On every attach call:
1. update the doc's frontmatter `spec_source_requests` (append the request wikilink if not already present);
2. re-project the `## Requests` sub-section from the now-current frontmatter list — rewriting only the bytes between the request-kind markers.

Frontmatter is the source of truth; the body sub-section is a projection. A doctor check (planned) verifies the two are in sync.

#### `## Docs` sub-section — projection from frontmatter

The bullet list between `<!-- auto:spec-docs:start --> / :end -->` is a deterministic projection of `spec_source_docs`:

- one bullet per wikilink, in the same order as the frontmatter list;
- bullet format: `- [[<doc-wikilink>|<display>]]` (no date — docs are stable references, not point-in-time events);
- the `<display>` default is shape-aware so the rendered bullet reads sensibly without operator rewrites:
  - product-level docs (`<spec_path>/<role>`) render as `<product> — product <role>` (e.g. `[[<spec_path>/design|<product> — product design]]`);
  - sibling-asset docs (`<spec_path>/<category>/<slug>/<role>`) render as `<slug> — <role>` (e.g. `[[<spec_path>/<category>/<slug>/design|<slug> — design]]`);
  - any other shape falls back to the bare last segment of the wikilink path.
  The operator may rewrite the display to a more meaningful gloss (e.g. `[[<spec_path>/design|<chapter>: product spec]]`) and the writer preserves these operator-edited displays across re-projections by matching on the wikilink path (the bytes left of the `|`);
- duplicates dedupe on the wikilink path.

Writers:
- `spec.create-asset` at scaffold time — writes the default `spec_source_docs` per doc-role (see `lazy-specs.functional-spec.md` § «Контекст эксперта при ревью» for the per-role default lists) AND emits the initial `## Docs` sub-section with the projected bullets.
- `spec.refresh-sources` on demand — re-projects the `## Docs` sub-section from the current `spec_source_docs` frontmatter list, preserving operator-edited displays.

Frontmatter is the source of truth; the body sub-section is a projection. A doctor check (planned) verifies the two are in sync.

#### Future sub-sections — extensibility

Other source kinds may land alongside `## Requests` under the same `# Sources` container. Two shapes are allowed:

- **Auto-managed** — the kind's writer ships its own HTML-marker pair (`<!-- auto:spec-<kind>:start --> / :end -->`) and its own frontmatter source of truth, mirroring the `## Requests` shape one-for-one.
- **Operator-authored** — the kind carries no markers and no frontmatter; the operator edits the sub-section's prose directly. Specs's writers never rewrite an unmarked sub-section.

Both shapes coexist freely under one `# Sources` container — the protected tag on the H1 covers the section as a whole, the per-sub-section markers define which bytes belong to which writer.

### Attribution lifecycle

- **First populating attach** — the writer creates the `# Sources` container + `## Requests` sub-section with the first bullet.
- **Subsequent attaches** — the writer updates frontmatter and re-projects the `## Requests` bullet list. The container, the protected tag, and any other sub-sections are left untouched.
- **Re-running on the same (request → doc) pair** — no-op (wikilink dedupe in the frontmatter list).
- **Doc finalize / asset gate transitions** — `# Sources` persists. The section is part of the asset's permanent audit trail, parallel to `# History`.

### Attribution doctor checks

`spec.doctor` enforces the contracts above:

- `spec_source_requests` wikilinks resolve to existing request files (forward-link integrity);
- `spec_source_docs` wikilinks resolve to existing files in the vault (forward-link integrity);
- when the `## Requests` sub-section exists, its bullet list matches the doc's `spec_source_requests` order and content (projection consistency);
- when the `## Docs` sub-section exists, its bullet list matches the doc's `spec_source_docs` order and content (projection consistency);
- the H1 `# Sources` section carries the `#protected/spec/sources` owner tag on its first content line (ownership integrity).

### Attribution writers

| Writer | Owns |
|---|---|
| `spec.request-attach` | frontmatter `spec_source_requests` on the touched docs + the asset's folder-note; the `## Requests` sub-section between its marker pair. |
| `spec.create-asset` | frontmatter `spec_source_docs` on every authored doc it scaffolds; the initial `## Docs` sub-section between its marker pair. |
| `spec.refresh-sources` | re-projection of the `## Docs` sub-section from the current `spec_source_docs` frontmatter list. |
| Future per-kind writers | their respective frontmatter key + the matching `## <Kind>` sub-section between their own marker pair. |
| Operator | manual edits to `spec_source_docs` frontmatter (extension / trimming the list); the `<display>` text in `## Docs` bullets (preserved across re-projections); unmarked sub-sections inside `# Sources` (manual entries the operator chooses to track outside any automated projection); prose appended below the `# Sources` container; everything outside the section. |

No other writer touches the `# Sources` container or its `#protected/spec/sources` tag.

## Part 2 — Source-code links and branch pinning

Source code is referenced by forge URL (GitHub / GitLab / Bitbucket / Gitea / Forgejo / Sourcehut). The vault never contains source-code symlinks.

**Format**: source URLs are ALWAYS produced by the `spec.source-url` primitive. Skills and agents MUST NOT inline forge-specific path schemes (`/blob/…`, `/-/blob/…`, `/src/…`, `/src/branch/…`, `/tree/…/item/…`) anywhere. The known-forges table below is the ONE place in the system that knows how forge URLs differ.

**Display-text conventions** (`[display](url)` in prose) are unchanged — skills choose the display text per their own conventions; only URL construction is centralized.

**Rules**:
- Always use full absolute forge URLs — never relative paths into source
- Never include line-number fragments (`#L42`); file path + symbol name is enough (see global rule "No line numbers in generated registries or docs")
- The `<path>` is relative to the repo root, not relative to the product's `source.paths`
- Skills **read** source from `<repo-config>.local_path/<path>` during generation; only the written links go through the forge

**Where source URLs belong** — see [file-roles](./spec.layout-protocol.md). Source URLs are permitted in `tech` files (product-level `tech.md`), `plan` files, and the `## Related code / logs` section of a `bug` file. They are FORBIDDEN in any `design` file. Behavior/design docs describe WHAT; source references belong with the code-level architecture.

### Known-forges table

`spec.resolve-repo` maps a git remote hostname to a forge key; `spec.source-url` maps `(forge key, kind)` to a URL template. `<base>` in each template is `https://<host>/<owner>/<repo>` (no trailing slash, no `.git` suffix). A repo record whose `local_path` is `"."` (same-repo product) resolves to `git rev-parse --show-toplevel` in the current checkout before the remote is read — the forge/`<base>` derivation is otherwise identical (see [config-protocol](./spec.config-protocol.md) Part 1 § Repo records).

| Forge key | Hostname match | File URL (`kind=blob`) | Tree URL (`kind=tree`) |
|---|---|---|---|
| `github` | `github.com` | `<base>/blob/<branch>/<path>` | `<base>/tree/<branch>/<path>` |
| `gitlab` | `gitlab.com` | `<base>/-/blob/<branch>/<path>` | `<base>/-/tree/<branch>/<path>` |
| `bitbucket` | `bitbucket.org` | `<base>/src/<branch>/<path>` | `<base>/src/<branch>/<path>` |
| `gitea` | — (explicit `forge:` only) | `<base>/src/branch/<branch>/<path>` | `<base>/src/branch/<branch>/<path>` |
| `forgejo` | `codeberg.org` | `<base>/src/branch/<branch>/<path>` | `<base>/src/branch/<branch>/<path>` |
| `sourcehut` | `git.sr.ht` | `<base>/tree/<branch>/item/<path>` | `<base>/tree/<branch>` |

- Hosts not listed above require an explicit `forge: <key>` in the repo config. `spec.resolve-repo` aborts with a configuration error otherwise.
- Self-hosted instances (e.g., `gitlab.company.internal`, a private Gitea) use the `forge:` override; pick the key whose path scheme matches the instance.
- The table covers the common forges. When adding a new forge, update this table and the `spec.resolve-repo` abort message together — those are the only two places that enumerate forge keys.

### Branch Pinning

Spec files that reference source code may pin those references to a non-default branch via the `spec_source_branches` frontmatter key — a dict keyed by repo-config key (e.g., `backend`, `shared`):

```yaml
---
tags:
  - <tag-path>
spec_source_branches:
  <repo-key>: <branch-name>
---
```

- **Absent or empty**: source links in this file use each repo's default `branch` (from the repo config).
- **Key present**: source links for that repo use the named branch — `spec.source-url(<repo-key>, <path>, <kind>, branch=<branch-name>)`.
- Dict shape — one spec can pin different branches per repo.

**Which files may carry pins**: only files whose role permits source URLs and may pin — `plan` files and the product-level `tech.md`. A `spec_source_branches` key on any other file is a bug; `spec.finalize-branch` and `spec.doctor` treat it as a violation.

**When to pin**: content-generating skills auto-pin a file they are creating IF (a) the source repo is currently checked out on a non-default branch AND (b) the generated file body will contain at least one forge URL for that repo. Files with no source URLs get no pin.

**When NOT to touch pins**: skills reconciling existing specs never silently overwrite a pin whose branch is still open — pinned URLs keep pointing at the open branch until the branch actually merges or is deleted.

### Pin Reconciliation

Shared primitive invoked by `spec.sync-with-code`, `spec.create-from-code` (regeneration path), `spec.doctor` (dry-run), and `spec.finalize-branch`.

**Inputs**: a spec file with a `spec_source_branches` dict.

**Per entry `<repo-key>: <branch>`:**

1. Resolve the repo via `spec.resolve-repo(<repo-key>)` → `{local_path, branch (= default), forge, base_url, …}`. Pick a remote name (prefer `origin`; else the first remote returned by `git -C <local_path> remote`).
2. Run `git -C <local_path> fetch --prune <remote>`. **Mandatory auto-fetch** — if it fails (network/auth), abort the whole skill run with a clear error. Never operate on stale data.
3. Determine branch status:
   - **Merged** — `git -C <local_path> merge-base --is-ancestor refs/remotes/<remote>/<pinned-branch> refs/remotes/<remote>/<default-branch>` (or local ref if the remote-tracking ref is absent). Action: rewrite + unpin.
   - **Open** — branch exists on remote (or locally) but is not an ancestor. Action: leave pin and URLs untouched.
   - **Deleted** — branch does not exist anywhere (remote or local). Action: rewrite + unpin (deleted is treated as merged).
4. Rewrite: in the file body, find every URL that starts with `<base_url>` (the resolved `base_url` for this repo — never touch URLs for other hosts or other repos) and whose branch segment equals `<pinned-branch>`. Rebuild each such URL by calling `spec.source-url(<repo-key>, <path>, <kind>, branch=<default-branch>)` and substituting the result. Detecting the branch segment is forge-aware and delegated to the primitive — skills MUST NOT do literal substring replacement on `/blob/<branch>/` or similar.
5. Unpin: remove the `<repo-key>` entry from `spec_source_branches`. If the dict becomes empty, remove the `spec_source_branches:` key entirely.

**Guarantees**:
- Idempotent — a second run finds no matching pins.
- Never rewrites an unmerged pin, even when a skill is explicitly asked about that branch.
- Deleted = merged (agreed project policy).
- Squash-merges aren't detected by ancestor check; they're picked up once the branch is deleted, or can be forced via `spec.finalize-branch --force-merged`.

## Part 3 — Dependencies & prerequisites

A product MAY declare upstream dependencies in its `dependencies` array under `products[<key>]` in `lazy.settings.json` (resolved via the `lazycortex-specs resolve-product` primitive — see [config-protocol](./spec.config-protocol.md)):

```json
"dependencies": [
  { "product": "server-tester-chapter" },
  { "repo": "backend" },
  { "external": { "name": "<external-tool-name>", "spec_url": "https://…", "dev_url": "https://github.com/…" } }
]
```

- `product` — internal, by product compound-key (resolved via `resolve-product`).
- `repo` — internal, by repo key (resolved via the `lazy.settings.json[repos]` section).
- `external` — `name`, `spec_url` (user-facing doc / external spec), `dev_url` (source repository).

Each dep entry resolves to `{kind, spec_link, dev_link, local_spec_path?}` via the shared primitive `spec.resolve-dependency`:

- `product` entries: `kind: internal-product`, `spec_link` = path-qualified wikilink to the dep's `<spec_path>/design`, `dev_link` = `base_url` from `spec.resolve-repo(<dep product's source.repo>)`, `local_spec_path` = the dep's `spec_path`.
- `repo` entries: `kind: internal-repo`, `spec_link` = wikilink to whichever product owns that repo as `source.repo` (or a documentation page; skill chooses the first product that lists the repo), `dev_link` = `base_url` from `spec.resolve-repo(<repo key>)`, `local_spec_path` = that product's `spec_path` if resolvable.
- `external` entries: `kind: external`, `spec_link` = `spec_url` (plain URL), `dev_link` = `dev_url`, `local_spec_path` = unset.

### Informational only

Nothing automatically checks or enforces dependency capability — the `dependencies` array is informational metadata consumed by `spec.resolve-dependency` when other skills (`spec.product-config`, import classification) need to classify or link deps. No gate reads it.
