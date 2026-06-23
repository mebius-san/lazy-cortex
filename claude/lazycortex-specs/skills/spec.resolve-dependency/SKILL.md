---
name: spec.resolve-dependency
description: Use to resolve a product dependency entry to concrete links (spec wikilink, dev GitHub URL) and optional local spec path. Reads a product's `dependencies` from `lazy.settings.json[products]` and returns a structured record. Called by callers that need to classify or link a dep entry (e.g., `spec.product-config` import classification).
execution-discipline-waiver: "Single-purpose primitive — resolves one dep entry against the dependencies reference; no multi-phase orchestration where step-skip can hide."
---
# Resolve Dependency

Primitive skill that turns a `dependencies` entry from a product's `products[<key>].dependencies` array in `lazy.settings.json` into an actionable record: `{kind, spec_link, dev_link, local_spec_path?}`.

The authoritative definition of the `dependencies` schema and resolution rules lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. This skill never restates them.

## Input

One dep entry in its YAML shape, one of:

```yaml
# Internal product
- product: <product-key>

# Internal repo
- repo: <repo-key>

# External
- external:
    name: <display name>
    spec_url: <https://…>
    dev_url:  <https://…>
```

## Process

### 1. Classify the entry

- `product:` key present → internal-product.
- `repo:` key present → internal-repo.
- `external:` key present → external.
- None of the above → refuse with a clear error naming the malformed entry.

### 2. Resolve internal-product

1. Resolve the product record for `<product-key>` from `lazy.settings.json[products]` — run `lazycortex-specs resolve-product by-key <product-key>`, or read the whole section via `lazycortex-core settings-get products` and select the entry.
2. Refuse if missing — suggest registering the product under `products[<product-key>]` with `spec.product-config`.
3. Read `spec_path` and `source.repo` from the product record.
4. Resolve `source.repo` via the `spec.resolve-repo` primitive to get `{base_url, …}`.
5. Emit: ``` kind: internal-product spec_link: [[<spec_path>/design|<product-key> design]] dev_link:  <base_url> local_spec_path: <spec_path> ```

### 3. Resolve internal-repo

1. Confirm `<repo-key>` is a key in the `repos` settings section (`lazycortex-core settings-get repos`). Refuse if absent.
2. Resolve via `spec.resolve-repo(<repo-key>)` to get `{base_url, …}`.
3. Find which product (if any) declares this repo as its `source.repo` by scanning `lazy.settings.json[products]`. If multiple, pick the first product in alphabetic-by-key order; record the fact that there are multiple.
4. Emit: ``` kind: internal-repo spec_link: [[<picked product spec_path>/design|<repo-key> (<picked product>)]] dev_link:  <base_url> local_spec_path: <picked product spec_path, or unset if no product uses this repo> ```

### 4. Resolve external

1. Read `name`, `spec_url`, `dev_url`. Require all three non-empty.
2. Emit: ``` kind: external spec_link: [<name>](<spec_url>)       # plain markdown link, not wikilink dev_link:  <dev_url> local_spec_path: <unset> ```

## Output

A single record with the four fields above. Skills consume the record and decide follow-up — this primitive never writes files, never asks the user, and never performs capability checks. Capability questions, if any, are the caller's responsibility.

## Failure modes

- **`/spec.resolve-dependency` refuses: malformed dep entry** — the entry lacks a `product:`, `repo:`, or `external:` key → fix the malformed entry in the product's `products[<key>].dependencies` array; each entry must match exactly one of the three documented shapes.
- **`/spec.resolve-dependency` refuses: product not found** — a `product:` entry's key does not match any product registered under `lazy.settings.json[products]` → register the missing product with `spec.product-config` or correct the key spelling.
- **`/spec.resolve-dependency` refuses: repo not found** — a `repo:` entry's key is not registered in `lazy.settings.json[repos]` → register the repo via `/spec.product-config` or correct the key spelling.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.resolve-dependency/YYYY-MM-DD_HH-MM-SS.md` with input, resolution output, and a `## Result` line.

## Key Rules

- **Pure function** — given the same dep entry and the same cfg files, always produces the same record. No side effects.
- **Never follow links** — the skill does not fetch `dev_url`, does not clone repos, does not inspect external specs. Those are caller concerns.
- **One entry, one call** — callers loop over the `dependencies:` list themselves.
- **Fail fast on malformed entries** — an entry lacking `product:`, `repo:`, or `external:` is a bug; refuse with a descriptive error.
