---
name: lazy-spec.set-stage
description: "Use when one authored spec doc changes stage — a draft is approved, a plan is rejected, an asset is cancelled. Accepts any document whose `spec_doc_type` is declared with `stages: true`, never a filename or a path. Every `spec.*` skill that moves a per-file `spec_stage` delegates here instead of editing frontmatter, so the `spec/<stage>` mirror tag and the `spec_approved_at` stamp never drift."
execution-discipline-waiver: "Single-purpose primitive — one call of the `set-stage` CLI verb; no multi-phase orchestration where step-skip can hide."
---
# Set Per-file Stage

Primitive skill that updates an authored doc's per-file `spec_stage`. Other `spec.*` skills delegate to this rather than edit frontmatter directly. The work itself is the `set-stage` verb of this plugin's CLI; this skill calls it once and reads its answer.

The authoritative definition of per-file stage semantics lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`. This skill never restates the semantics — point at it for what each stage means.

## Input

1. **File path** — absolute or vault-relative path to an authored doc whose `spec_doc_type` is declared with `stages: true`.
2. **New stage** — exactly one of the closed set `empty | draft | approved | rejected | cancelled | deferred`. The removed values `review` / `done` / `wtr` are refused.
3. **`--restamp`** — valid only with `approved`: rewrites `spec_approved_at` on a document already at `approved`. The coordinators pass it when a document already at `approved` comes out of a review approved again — a re-approval — so its stamp records that approval and the coherence check that follows sees it.
4. **Optional author** — accepted and ignored, so existing callers' argument shape still parses.

## Process

Run the verb once:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" set-stage <file> <stage> [--restamp])
```

It prints one JSON line `{"status", "stage", "approved_at", "attachments", "touched_paths", "reason"}` and exits 0 on `set` / `noop`, 1 on `refused`, 2 on an argument error. It validates the document, writes the stage with its mirror tag and stamp, cascades the stage to the document's markdown attachments, refreshes the container notes' stats, and, on an approved living doc, runs `decide promote`.

- **Success is `status` `set` or `noop`, and nothing else.** Never report a stage as moved without one of those two answers in hand.
- **The verb writes and does not commit.** Fold every path in `touched_paths` into the SAME commit as the caller's own edits — the document, its attachments, the container notes, and the decision registries `decide promote` wrote all travel together.
- **A refusal is reported, never worked around.** Pass `reason` to the caller verbatim; never edit the frontmatter by hand, retry with different arguments, or hand-edit `decisions.md`. A refusal writes nothing and comes back with an empty `touched_paths`, so there is nothing to commit. Every `reason` the verb can return is listed under Failure modes.

## Output

The verb's JSON: the file's new `stage`, the `attachments` the cascade re-stamped, the `approved_at` value written on an approval (`null` otherwise), and the `touched_paths` the caller commits.

## Failure modes

- **`/lazy-spec.set-stage` refuses with: document carries no spec_doc_type** — run `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" doc-type backfill` to type the catalog, or add the key to that one document.
- **`/lazy-spec.set-stage` refuses with: type `<type>` is not declared in this product's scope** — fix the typo, or declare the type under `products[<key>].doc_types` in `.claude/lazy.settings.json`.
- **`/lazy-spec.set-stage` refuses with: type `<type>` carries no spec_stage** — that kind of document has no independently-settable stage; nothing to set.
- **`/lazy-spec.set-stage` refuses with: stage `<value>` is not in the closed set** — pass `draft` + set `review_active: true` for in-review, `approved` for accepted, or the correct closed-set value per intent.
- **`/lazy-spec.set-stage` refuses with: document is an attachment of `<owner>`** — set the stage on the owner document; the cascade re-stamps the attachment.
- **`/lazy-spec.set-stage` refuses with: document carries a decision-candidate at line <N> — fold it through the document's review before approving** — a writer round folds the callout; never a hand deletion.
- **`/lazy-spec.set-stage` refuses with: document is deferred** — set it to `draft` first to bring it back (the coordinators start reacting to the document again the moment it lands), or to `cancelled` to abandon it.
- **`/lazy-spec.set-stage` refuses with: cancelled not allowed on `<file>`** — cancellation belongs on `system-tech`, `code-plan`, or `test-plan`; use those instead.
- **`/lazy-spec.set-stage` refuses with: --restamp is valid only with `approved`** — drop the flag, or pass `approved`.
- **`/lazy-spec.set-stage` refuses with a `decide promote` reason** — the owning asset is cancelled, halted, or released; nothing was written and the document keeps its previous stage, so report the reason and commit nothing for it.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop over files themselves.
- **Only the verb writes a stage** — never edit `spec_stage`, the `spec/<stage>` tag, or `spec_approved_at` by hand.
- **No commit of its own** — `touched_paths` rides in the caller's commit.
- **Never touch the folder-note's gate** — gate transitions, gate side-effects and plan-step progression belong to the gate machinery.
