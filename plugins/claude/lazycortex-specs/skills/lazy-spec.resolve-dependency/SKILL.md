---
name: lazy-spec.resolve-dependency
description: "Dispatched by /lazy-spec.product-config to classify or link one `dependencies[]` entry; not for direct use."
execution-discipline-waiver: "Single-purpose primitive — resolves one dep entry against the dependencies reference; no multi-phase orchestration where step-skip can hide."
---
# Resolve Dependency

Primitive skill that turns a `dependencies` entry from a product's `products[<key>].dependencies` array in `lazy.settings.json` into an actionable record: `{kind, spec_link, dev_link?, local_spec_path?}`.

The authoritative definition of the `dependencies` schema and resolution rules lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`. This skill never restates them.

## Input

One dep entry in its YAML shape, one of two:

```yaml
# Internal product
- product: <product-key>

# External
- external:
    name: <display name>
    spec_url: <https://…>
    dev_url:  <https://…>
```

## Process

### 1. Classify the entry

- `product:` key present → internal-product.
- `external:` key present → external.
- None of the above → refuse with a clear error naming the malformed entry.

### 2. Resolve internal-product

**Resolve `<core-cli>` once, before the first call.** It is the core plugin's `bin/lazycortex-core` file; `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" core-cli)` prints its absolute path — this plugin's own resolver tries the daemon's `$LAZYCORTEX_PLUGIN_DIRS`, then the dev-vault sibling `plugins/claude/lazycortex-core/`, then the install `~/.claude/plugins/installed_plugins.json` records; exit 1 with an `error:` line means core is not installed — abort and say so. Hold the absolute path and run every verb as `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb> …)` — never as a bare command: the file carries no exec bit and no plugin `bin/` is on `PATH`.

1. Resolve the product record for `<product-key>` from `lazy.settings.json[products]` — run `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" resolve-product by-key <product-key>`, or read the whole section via `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get products` and select the entry.
2. Refuse if missing — suggest registering the product under `products[<product-key>]` with `lazy-spec.product-config`.
3. Read `spec_path` and the record's own `source.paths` from the product record; a design-only product has no `source`.
4. Emit: ``` kind: internal-product spec_link: [[<spec_path>/design|<product-key> design]] local_spec_path: <spec_path> code_paths: `<path>`, `<path>` ``` — `code_paths` lists each `source.paths` entry as a backticked path, never as a link, because a link to a folder makes Obsidian create a note there; it is unset for a design-only product. There is no `dev_link`: the dep's code is in this repository, and the `spec_link` carries the navigation.

### 3. Resolve external

1. Read `name`, `spec_url`, `dev_url`. Require all three non-empty.
2. Emit: ``` kind: external spec_link: [<name>](<spec_url>)       # plain markdown link, not wikilink dev_link:  <dev_url> local_spec_path: <unset> ```

## Output

A single record with the fields above (`code_paths` only for an internal product with a `source`, `dev_link` only for an external entry). Skills consume the record and decide follow-up — this primitive never writes files, never asks the user, and never performs capability checks. Capability questions, if any, are the caller's responsibility.

## Failure modes

- **`/lazy-spec.resolve-dependency` refuses: malformed dep entry** — the entry carries neither a `product:` nor an `external:` key → fix the entry in the product's `products[<key>].dependencies` array; each entry must match exactly one of the two documented shapes, and a dependency on code of this repository is a `product:` entry naming the product that owns it.
- **`/lazy-spec.resolve-dependency` refuses: product not found** — a `product:` entry's key does not match any product registered under `lazy.settings.json[products]` → register the missing product with `lazy-spec.product-config` or correct the key spelling.

## Key Rules

- **Pure function** — given the same dep entry and the same cfg files, always produces the same record. No side effects.
- **Never follow links** — the skill does not fetch `dev_url`, does not inspect external specs. Those are caller concerns.
- **One entry, one call** — callers loop over the `dependencies:` list themselves.
- **Fail fast on malformed entries** — an entry lacking `product:` or `external:` is a bug; refuse with a descriptive error.
