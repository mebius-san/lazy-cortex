---
name: spec.create-bug
description: Built-in wrapper over `spec.create-asset` — pins `<category>` to `bug` and delegates. Use when filing a bug against a product spec; all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. The bug layout is `bug.md` + `plan.md` (NO `design.md`).
execution-discipline-waiver: "Thin wrapper — pins the category to `bug` and delegates to spec.create-asset via the Skill tool; the multi-phase orchestration where step-skip can hide lives entirely in the delegate."
---
# Create Bug

Thin built-in wrapper that pins the asset category to `bug` and delegates to `spec.create-asset`. This skill asks no questions and writes no files itself — the universal `spec.create-asset` skill owns the wizard, scaffold, prose, and diagrams. See `${CLAUDE_PLUGIN_ROOT}/skills/spec.create-asset/`.

The bug layout is `bug.md` (repro, observed vs expected) + an empty `plan.md` placeholder for the fix plan — NO `design.md`. That layout selection lives in `spec.create-asset`.

## Input

Signature: `<product> <slug> [--empty]`. The user gives the product compound-key and the bug slug (lowercase-with-hyphens); pass `--empty` straight through when present.

## Process

Invoke `spec.create-asset` via the `Skill` tool (`skill: "lazycortex-specs:spec.create-asset"`) with args `<product> bug <slug>`, appending `--empty` when the caller passed it. Report the delegate's outcome verbatim.
