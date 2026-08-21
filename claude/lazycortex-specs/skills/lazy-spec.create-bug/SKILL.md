---
name: lazy-spec.create-bug
description: "Use when filing a bug against a product spec. Built-in wrapper: pins the asset type to `bug` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. Which document the asset starts from is declared by the type declaration (`asset_types.bug.start_doc`) and read by the delegate, never by this wrapper."
execution-discipline-waiver: "Thin wrapper — pins the category to `bug` and delegates to lazy-spec.create-asset via the Skill tool; the multi-phase orchestration where step-skip can hide lives entirely in the delegate."
---
# Create Bug

Thin built-in wrapper that pins the asset type to `bug` and delegates to `lazy-spec.create-asset`. This skill asks no questions and writes no files itself — the universal `lazy-spec.create-asset` skill owns the wizard, scaffold, prose, and diagrams. See `${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.create-asset/`.

The document a `bug` asset starts from is declared by the type declaration (`asset_types.bug.start_doc` — shipped as `bug.md:bug`, repro plus observed vs expected), and the delegate reads it from there. Plans and reports are the property of the asset's tools, declared by `tool_types` and authored later — the scaffold seeds neither, and this wrapper decides neither.

## Input

Signature: `<product> <slug> [--empty]`. The user gives the product compound-key and the bug slug (lowercase-with-hyphens); pass `--empty` straight through when present.

## Process

Invoke `lazy-spec.create-asset` via the `Skill` tool (`skill: "lazycortex-specs:lazy-spec.create-asset"`) with args `<product> bug <slug>`, appending `--empty` when the caller passed it. Report the delegate's outcome verbatim.
