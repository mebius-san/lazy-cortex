---
name: spec.request-spawn
description: Spawn a new feature/change/bug entity from a request, then delegate to spec.request-attach to populate it from the request body. Calls the deterministic `lazycortex-specs scaffold-asset` primitive for the empty-scaffold step, then invokes `spec.request-attach` on the freshly-created folder-note.
execution-discipline-waiver: "nested-from-agent — invoked by spec.request-apply; outer agent owns step discipline (per lazy-core.skill-writing § 1.5)"
allowed-tools: Read, Bash(lazycortex-specs scaffold-asset *), Skill
---
# Spawn a new entity from a request

Create a new entity (feature, change, or bug) from a request, then populate it from the request body via `spec.request-attach`. Two-step operation:

1. Scaffold an empty entity via the `lazycortex-specs scaffold-asset` CLI primitive (deterministic Python; no LLM judgment, no nested skill chain).
2. Invoke `spec.request-attach` on the freshly-created folder-note.

The class taxonomy + per-class spawn-allowed targets live in `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md` → "Class taxonomy". This skill never restates them.

## Input

- **`--file <request_path>`** — absolute or vault-relative path to the request file
- **`--kind <kind>`** — one of `feature` | `change` | `bug` (the asset kind)
- **`--product <product>`** — product compound-key (e.g. `dashboards`)
- **`--slug <slug>`** — entity slug (kebab-case). The caller derives this from the request title.

## Process

### 1. Resolve target path

Read `.claude/lazy.settings.json` (the repo root is `git rev-parse --show-toplevel` of the current working directory). Look up `products[<product>]`. If the key is absent or null, the product is not registered → abort, suggesting `/spec.product-config`. Otherwise capture `spec_path`.

Compute target folder path:

- `feature` ⇒ `<spec_path>/features/<slug>/`
- `change` ⇒ `<spec_path>/changes/<slug>/`
- `bug` ⇒ `<spec_path>/bugs/<slug>/`

If the target folder already exists, the scaffold primitive in Step 2 will abort with a `logical` error naming the collision; the caller (`spec.request-apply`) is responsible for collision-free slug selection.

### 2. Scaffold empty entity

Invoke the deterministic scaffold primitive via `Bash`:

```
Bash(lazycortex-specs scaffold-asset <product> <kind> <slug>)
```

The primitive (`claude/lazycortex-specs/bin/scaffold_asset.py`) does:

- Reads `products[<product>]` from `.claude/lazy.settings.json` (no LLM lookup).
- Resolves the template directory via the three-layer override chain (per-product → project-wide → plugin baseline).
- Substitutes template tokens (`{{product}}`, `{{slug}}`, `{{subsystem}}`, `{{product_tag}}`, `iconize_icon`, `iconize_color`).
- Writes the folder-note + per-category authored docs (`design.md` + `plan.md` for feature/change, `bug.md` + `plan.md` for bug).
- Appends history lines to the folder-note (scaffold + per-doc stage transitions).
- Prints a JSON outcome dict on success; exits non-zero with a JSON `error` field on logical failure (target folder exists, unknown product, unknown category, missing template).

On non-zero exit: propagate the primitive's stderr/JSON to the caller; do NOT retry or improvise the scaffold inline.

After this step, the folder exists with:

- `<slug>.md` — the folder-note (filename matches the parent folder per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`; `spec_role: status`, gates all `false`, history seeded).
- `design.md`, `plan.md` (feature/change) or `bug.md`, `plan.md` (bug) — authored docs at the template-default per-file stages (`design.md`/`bug.md` → `draft`, `plan.md` → `empty`).

### 3. Delegate to spec.request-attach

Invoke `Skill: lazycortex-specs:spec.request-attach` with `<request_path> <new-folder-note-path>`. That skill:

- Distributes the request body across the new entity's authored docs per the body-distribution rules.
- Adds the request's wikilink to the new folder-note's `spec_source_requests` frontmatter + projects the body `## Requests` sub-section under `# Sources`.
- Opens a fresh review cycle on every populated doc via `lazy-review.start`.

Per-doc stages flip from `empty` to `draft` only for the docs that received body content. The reverse link (request → spawned entity) is carried later by `spec.request-apply` in the terminal status callout body, not as a separate body section.

## Output

Path to the newly-created folder-note (so the caller can collect it for the apply pass's status-callout wikilink list when spawning multiple targets in the same pass).

## Idempotence

NOT idempotent — re-running with the same `<product> <slug>` exits non-zero from the scaffold primitive because the target folder already exists. The caller is responsible for not invoking spawn twice on the same target.

## Failure modes

- **Target folder already exists** — propagated from the scaffold primitive's logical error. Caller must pick a unique slug.
- **Product not registered** — propagated from the scaffold primitive. Caller passed an unknown `<product>` key.
- **Kind not in {feature, change, bug}** — propagated from the scaffold primitive. Other classes (`task`, `plan`, `feedback`, `spec`) are caller's concern.
- **Missing template** — propagated. Operator must restore the plugin or seed the local override.
- **`spec.request-attach` fails** — propagate the Skill's error with context. Scaffold is already on disk; the apply caller's commit will sweep it up.

## Run logging

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.request-spawn/YYYY-MM-DD_HH-MM-SS.md` listing inputs, the scaffold primitive's JSON output, and the spec.request-attach delegation outcome.
