---
name: spec.create-change
description: "Use when requesting a change to an existing product spec — the atomic modification unit, peer to a feature. Built-in wrapper: pins `<category>` to `change` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`."
execution-discipline-waiver: "Thin wrapper — pins the category to `change` and delegates to spec.create-asset via the Skill tool; the multi-phase orchestration where step-skip can hide lives entirely in the delegate."
---
# Create Change

Thin built-in wrapper that pins the asset category to `change` and delegates to `spec.create-asset`. This skill asks no questions and writes no files itself — the universal `spec.create-asset` skill owns the wizard, scaffold, prose, and diagrams. See `${CLAUDE_PLUGIN_ROOT}/skills/spec.create-asset/`.

A "change" is the smallest atomic modification unit and sits peer to a feature. In the intake pipeline (`requests/` → `changes/`), a `request` is raw user input that may be classified into either a `feature` or a `change`.

## Input

Signature: `<product> <slug> [--empty]`. The user gives the product compound-key and the change slug (lowercase-with-hyphens); pass `--empty` straight through when present.

## Process

Invoke `spec.create-asset` via the `Skill` tool (`skill: "lazycortex-specs:spec.create-asset"`) with args `<product> change <slug>`, appending `--empty` when the caller passed it. Report the delegate's outcome verbatim.
