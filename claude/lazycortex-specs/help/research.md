---
chapter_type: block
summary: Answer one question against the spec tree without loading whole documents into your context.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-spec.lookup
source_sha: c6319fd5862972d0cafec847f18eab54aea4d385
---
# Research: bounded lookups over the spec tree

When you or an agent working on your behalf needs to know where something lives in the spec tree, or what depends on it, you don't want to open every `design.md` and `tech.md` in the product to find out. This block answers a single question — a query token plus an optional anchor — by walking a bounded slice of the tree and handing back matching paths with one-line excerpts, never whole documents.

## What's in this block

- **`/lazy-spec.lookup`** — takes a free-form question or token and an optional anchor (a registered product key, a vault-relative path, or a `<category>/<slug>` pair scoped to a product) and returns the matching files with short excerpts. Give it no anchor and it searches the whole vault instead of one product's tree.

## How they work together

There's one skill in this block, but it does its work in three separate passes so the result stays bounded no matter how big the spec tree is:

- **Up** — from an asset anchor, it reads the asset's own status note and pulls the `# Summary` line; from a product anchor, it reads `design.md` / `tech.md` and keeps only the paragraphs that mention your query token. If neither anchor form applies, it falls back to a vault-wide grep for the token.
- **Down** — it follows the asset's declared `spec_depends_on` children and any path-qualified wikilinks in its authored docs, pulling each target's `# Summary`.
- **Across** — it checks sibling assets in the same category folder, greps the whole vault for backlinks to the anchor's own path, and — for a change asset — pulls the summaries of its `spec_targets`.

Every match is deduplicated by path, trimmed to the one line that justified it, and grouped by direction (`Up` / `Down` / `Across`) in the answer. No whole file ever lands in your context just to answer one question.

Because the skill only ever calls `Read` / `Glob` / `Grep` directly — it never dispatches further subagents — it works inside contexts that have no budget for that: an expert following its research aspect, a review specialist gathering context before writing, or a subagent doing prep work for another skill. You can also invoke it yourself when you just want to know "where does X live" or "what depends on this asset" without opening the vault by hand.

## Where this fits

Lookups only make sense once a product is registered and has assets to search — see the `install-and-audit` block for registering a product, and the `authoring` block for creating the assets this skill later finds. `lazy-spec.doctor` and `lazy-spec.sync-with-code` do their own deeper structural scans; reach for `/lazy-spec.lookup` instead when you want a fast, bounded answer to one question rather than a full audit.

## See also

- [authoring](authoring.md) — create the assets a lookup can later find.
- [install-and-audit](install-and-audit.md) — register the product a lookup anchors against.
