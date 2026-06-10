---
name: spec.create-feature
description: Built-in wrapper over `spec.create-asset` — pins `<category>` to `feature` and delegates. Use when adding a new feature to a product that already has a spec; all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`.
execution-discipline-waiver: "Thin wrapper — pins the category to `feature` and delegates to spec.create-asset via the Skill tool; the multi-phase orchestration where step-skip can hide lives entirely in the delegate."
---
# Create Feature

Thin built-in wrapper that pins the asset category to `feature` and delegates to `spec.create-asset`. This skill asks no questions and writes no files itself — the universal `spec.create-asset` skill owns the wizard, scaffold, prose, and diagrams. See `${CLAUDE_PLUGIN_ROOT}/skills/spec.create-asset/`.

## Input

Signature: `<product> <slug> [--empty]`. The user gives the product compound-key and the feature slug (lowercase-with-hyphens); pass `--empty` straight through when present.

## Process

Invoke `spec.create-asset` via the `Skill` tool (`skill: "lazycortex-specs:spec.create-asset"`) with args `<product> feature <slug>`, appending `--empty` when the caller passed it. Report the delegate's outcome verbatim.
