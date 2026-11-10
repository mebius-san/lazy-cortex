---
chapter_type: block
summary: Answer one question against the spec tree without loading whole documents into your context.
last_regen: 2026-11-10
no_diagram: true
source_skills:
  - lazy-spec.lookup
source_sha: f484cc6c959efd78c1906a8bf53547ff8489b212
surface_sha: 03202c292920a943103db80915ce7159532782b87510886a26f4e67650c6c799
---
# Research: bounded lookups over the spec tree

When you or an agent working on your behalf needs to know where something lives in the spec tree, or what depends on it, you don't want to open every `design.md` and `tech.md` in the product to find out. This block answers a single question — a query token plus an optional anchor — by walking a bounded slice of the tree and handing back matching paths with one-line excerpts, never whole documents.

## What's in this block

- **`/lazy-spec.lookup`** — takes a free-form question or token and an optional anchor (a registered product key, a vault-relative path, or a product-relative path of any depth scoped to a product) and returns the matching files with short excerpts. Give it no anchor and it searches the whole vault instead of one product's tree.

## How they work together

There's one skill in this block, but it does its work in three separate passes so the result stays bounded no matter how big the spec tree is:

- **Up** — from an asset anchor, it reads the asset's own status note and pulls the `# Summary` line; from a product anchor (or the product that owns an asset anchor), it reads `design.md` / `tech.md` and keeps only the paragraphs that mention your query token. If nothing turns up, it falls back to a vault-wide grep for the token.
- **Down** — it follows the path-qualified wikilinks in the anchor's authored docs (a materialized `[!asset-proposal]` link, and for a product anchor the product's own `architecture.md`), pulling each target's `# Summary`.
- **Across** — for an asset anchor it checks the sibling assets in the same folder; for a product-only anchor it checks every folder under the product root, at any depth, whose folder-note is a status note. In both cases it keeps only the siblings whose docs actually mention your token. It also greps the whole vault for backlinks to the anchor's own path and the token, and — for a change asset — pulls the summaries of its `spec_targets`.

Every match is deduplicated by path, trimmed to the one line that justified it, and grouped by direction (`Up` / `Down` / `Across`) in the answer. No whole file ever lands in your context just to answer one question.

Beyond resolving your anchor, the skill only ever calls `Read` / `Glob` / `Grep` directly — it never dispatches further subagents — so it works inside contexts that have no budget for that: an expert following its research aspect, a review specialist gathering context before writing, or a subagent doing prep work for another skill. You can also invoke it yourself when you just want to know "where does X live" or "what depends on this asset" without opening the vault by hand.

## Where this fits

Lookups only make sense once a product is registered and has assets to search — see the `install-and-audit` block for registering a product, and the `authoring` block for creating the assets this skill later finds. `lazy-spec.audit` and `lazy-spec.sync-with-code` do their own deeper structural scans; reach for `/lazy-spec.lookup` instead when you want a fast, bounded answer to one question rather than a full audit.

## When it refuses

- **Anchor not found** — the product key is not a registered product, or the vault-relative path does not resolve under the spec tree. Correct the key or path, or register the product with `/lazy-spec.product-config`. When the product key is the problem, the refusal names the key and lists the registered products.
- **Product-relative path without a product** — a path relative to a product root was given with no product key to resolve it against. Pass the product key alongside it, or use the full vault-relative path.
- **Core plugin not installed** — resolving an anchor needs `lazycortex-core`; when it cannot be found, the lookup aborts and says so. Install it, then ask again.

A vault-relative path that no registered product covers is not a refusal: the path still anchors the lookup, and the sibling and backlink passes scope to the vault instead of a product root.

When a lookup finds nothing, it says so plainly, naming the anchor and the query token, instead of returning an empty list.

## See also

- [authoring](authoring.md) — create the assets a lookup can later find.
- [install-and-audit](install-and-audit.md) — register the product a lookup anchors against.
