---
name: lazy-spec.set-stage
description: "Use when one authored spec doc changes stage — a draft is approved, a plan is rejected, an asset is cancelled. Accepts any document whose `spec_doc_type` is declared with `stages: true`, never a filename or a path. Every `spec.*` skill that moves a per-file `spec_stage` delegates here instead of editing frontmatter, so the `spec/<stage>` mirror tag and the folder-note `# History` line never drift."
execution-discipline-waiver: "Single-purpose primitive — wraps the per-file-stages reference; no multi-phase orchestration where step-skip can hide."
---
# Set Per-file Stage

Primitive skill that updates an authored doc's per-file `spec_stage`. Other `spec.*` skills delegate to this rather than edit frontmatter directly.

The authoritative definition of per-file stage semantics lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`. This skill never restates the semantics — point at it for what each stage means. (That reference still describes an older stage set and is rewritten in a later phase; the closed stage set this skill enforces is stated inline below.)

## Input

1. **File path** — absolute or vault-relative path to an authored doc. The doc MUST carry a `spec_doc_type` whose declaration exists in the owning product's scope and carries `stages: true`. Neither the basename nor the path takes part in this: a document named `races.md` carrying `spec_doc_type: design` is a design document. A type declared `stages: false` (the shipped `code-report` / `test-report` / `decisions`, and any project type declaring the same) carries no independently-settable stage and is rejected here.
2. **New stage** — exactly one of the closed set `empty | draft | approved | rejected | cancelled`. Anything else (including the removed `review` / `done` / `wtr` values) is rejected with a clear error. "In review" is now expressed as `spec_stage: draft` + `review_active: true` on the doc; "accepted" is `approved`.
3. **Optional author** — free-text name recorded in the folder-note history line. Defaults to `lazy-spec.set-stage` (the skill's own name).

## Process

### 1. Validate the file

Three checks, in order. None of them reads a filename or a path.

1. **The document declares a type.**

   ```
   Bash(lazycortex-specs doc-type of <file>)
   ```

   An empty `doc_type` in the returned JSON is a refusal: `document carries no spec_doc_type`. Name the file and point the caller at `lazycortex-specs doc-type backfill`, which adds the key to every typed document in the catalog missing it.

2. **The type is declared, and it carries stages.** Resolve the owning product first, then its declaration:

   ```
   Bash(lazycortex-specs resolve-product by-path <file>)
   Bash(lazycortex-specs doc-type resolve <type> --product <key>)
   ```

   A non-zero exit from `doc-type resolve` is a refusal: ``type `<type>` is not declared in this product's scope`` — the value is either a typo or a type nobody declared, and the fix is to correct it or declare it under `products[<key>].doc_types`. A declaration carrying `stages: false` is a refusal too: ``type `<type>` carries no spec_stage``.

2a. **The document is not an attachment.** A doc carrying `spec_owner_doc` is a markdown attachment; its `spec_stage` is a mirror of its owner's, written only by the owner's own stage cascade (step 2b below) and by the coordinator's reconciliation. Refuse: ``document is an attachment of `<owner>` — its stage mirrors the owner's; set the owner's stage instead``.

3. **The requested stage is in the closed set** `empty | draft | approved | rejected | cancelled`. If the value is not in the set, refuse — name the offending value and list the closed set. For the removed values specifically: `review` → use `draft` + `review_active: true`; `done` → use `approved`; `wtr` → use `draft` or `approved` per intent. The set of TYPES is open and validated by declaration; the set of STAGES is closed and validated by this list.

Then check the `cancelled`-allowed rules in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`: `cancelled` is refused on a document whose type is mandatory for its asset's category. Mandatoriness is declared by the category's playbook; until that playbook exists, the standing list applies — refuse `cancelled` on types `design`, `system-design`, `bug`, and `architecture`; types `system-tech`, `code-plan`, and `test-plan` MAY be cancelled (docs-only feature / no dev or test work needed). Moving this rule into the category playbook belongs to the category-playbooks plan, not to this skill.

### 2. Rewrite the `spec_stage` frontmatter key

Replace the `spec_stage:` value in the doc's frontmatter. Preserve all other frontmatter keys in their original order. If `spec_stage:` is absent, insert it at the end of the frontmatter block.

### 2a. Update the status mirror tag

Update the file's `tags:` list in lock-step with the new `spec_stage:` value:

1. If the file has no `tags:` frontmatter key, create one as a YAML list.
2. Strip the existing `spec/<old-stage>` entry (and, defensively, any `spec/*` entry).
3. Append `spec/<new-stage>`.
4. Preserve all other tag entries (topic tags, user-applied tags) untouched.

Example: `spec_stage` going `draft → approved` rewrites both:

```yaml
spec_stage: approved             # was: draft
tags:
  - topic/auth                   # preserved
  - spec/approved                # was: spec/draft
```

The mirror is required, not optional. `lazy-spec.doctor` flags any mismatch as a finding.

### 2b. Cascade the stage to the doc's markdown attachments

The doc's markdown attachments mirror its stage: an attachment carries no lifecycle of its own, so its `spec_stage` is always a copy of the owner's — except while the attachment sits in its own review, when nobody writes the file.

1. Enumerate sibling `.md` files in the doc's directory whose frontmatter `spec_owner_doc` equals the doc's basename.
2. Skip every attachment carrying `review_active: true` — the review cycle owns the file; the coordinator re-stamps it on the wake its finalize raises.
3. For each remaining attachment, rewrite `spec_stage:` to the new stage and update the `spec/<stage>` mirror tag exactly as steps 2 and 2a did for the doc itself. Insert both keys when absent — an attachment created before the cascade existed catches up here.
4. Fold every touched attachment into the SAME commit as the doc; no separate history line per attachment — the owner's line covers the change.

A doc with no attachments makes this a silent no-op.

### 3. Append to the nearest folder-note's `# History`

The folder-note is the file whose basename matches the enclosing folder (e.g., `features/chapter-log/chapter-log.md`). For `design.md` / `tech.md` / `architecture.md` / `code-plan.md` / `test-plan.md` under `<spec_path>/features/<feat>/` or `<spec_path>/changes/<change-name>/`, and for `bug.md` / `code-plan.md` / `test-plan.md` under `<spec_path>/bugs/<bug-name>/`, the folder-note is in the same directory. For system-level authored docs at the product root (`<spec_path>/design.md` / `<spec_path>/tech.md`) or at the content-root (the project-wide pair), there is no status folder-note in scope (the product folder-note is operator-zone) — skip the history step.

When a folder-note is in scope, append one line to its `# History` section:

```
- <YYYY-MM-DD> — lazy-spec.set-stage · <doc>.md spec_stage <old>→<new>
```

`<doc>` is the doc's basename (e.g. `design`). Substitute the resolved author for `lazy-spec.set-stage` when an author was passed. Use UTC date (`date -u +%Y-%m-%d`). Do not touch existing history entries or any frontmatter of the folder-note. If the folder-note has no `# History` section, create one at the end of the body.

### 3a. Recompute the category container note stats

The asset's category container note is the note whose basename matches the category folder that holds the asset (e.g. `features/features.md` for an asset under `features/<slug>/`). When that container note exists, refresh its `<!-- spec:stats:* -->` region so the bucket counts reflect this stage change:

```
Bash(lazycortex-specs render-container-stats <category_note>)
```

Then `git add` the category note into the SAME commit as the doc and folder-note edits. Guard: skip silently when the category container note does not exist (a product-level authored doc with no category container, or a container carrying no stats markers — `render-container-stats` is a no-op there).

### 3b. Promote decisions when the new stage is `approved` on a living doc

When the requested stage is `approved` AND the doc is a **living doc** — its type's declaration carries `stages: true` AND `append_only: false` — run the transfer primitive. Both flags come from the `doc-type resolve` call already made in step 1; no second lookup is needed.

```
Bash(lazycortex-specs decide promote <doc>)
```

Fold its returned `touched_paths` into the SAME commit as the doc, folder-note, and category container note edits — the doc itself may be one of those paths again (the primitive rewrites `[!decision]` blocks into reference links), its sibling `decisions.md`, and, when a transferred block carried a `**Supersedes.**` command, a second `decisions.md` it stamped `superseded-by`.

The primitive owns its own refusal: it detects `[!decision]` blocks itself, refuses on `spec_cancelled` / `spec_halted` / `spec_released` on the owning asset, and no-ops (empty `touched_paths`) when the doc carries no blocks. A refusal here is reported to the caller exactly as any other primitive refusal in this skill — it is NEVER bypassed, retried with different arguments, or worked around by hand-editing `decisions.md`. This step does not run for any other target stage, and does not run on `code-plan` / `test-plan` (not living docs — no source blocks to transfer).

Promote sources are exactly the living docs the predicate selects — a type carrying `stages: false` or `append_only: true` never feeds the registry directly. Such a document may still carry `[!decision-candidate]` markers; they stay candidates until its declaration says otherwise.

### 4. Do NOT advance the folder-note's gate

This primitive only edits the doc's own per-file `spec_stage`. It does NOT evaluate folder-level gate transitions, gate side-effects, or plan-step progression. Those are the responsibility of the gate machinery.

## Output

- The file's new `spec_stage`.
- The attachments the cascade re-stamped (or nothing when the doc has none).
- The folder-note path + the appended history line (or `no folder-note in scope` when at product level).
- On an `approved` transition of a living doc: the `touched_paths` returned by `decide promote`, or nothing when it no-opped (no `[!decision]` blocks) or refused (asset flag / not a living doc).

## Failure modes

- **`/lazy-spec.set-stage` refuses with: document carries no `spec_doc_type`** — the target file has no type key, so no declaration can be resolved → run `lazycortex-specs doc-type backfill` to type the catalog, or add the key to that one document.
- **`/lazy-spec.set-stage` refuses with: type `<type>` is not declared in this product's scope** — the value resolves to no declaration, shipped or project-level → fix the typo, or declare the type under `products[<key>].doc_types` in `.claude/lazy.settings.json`.
- **`/lazy-spec.set-stage` refuses with: type `<type>` carries no `spec_stage`** — the declaration exists but carries `stages: false` → that kind of document has no independently-settable stage; nothing to set.
- **`/lazy-spec.set-stage` refuses with: stage `<value>` is not in the closed set** — passed a value outside `empty | draft | approved | rejected | cancelled` (e.g. the removed `review` / `done` / `wtr`) → pass `draft` + set `review_active: true` for in-review, `approved` for accepted, or the correct closed-set value per intent.
- **`/lazy-spec.set-stage` refuses with: document is an attachment of `<owner>`** — the target carries `spec_owner_doc`, so its stage is a mirror → set the stage on the owner document; the cascade re-stamps the attachment in the same commit.
- **`/lazy-spec.set-stage` refuses with: cancelled not allowed on `<file>`** — attempted `cancelled` on a type mandatory for the asset's category (`design`, `bug`, `architecture`) → cancellation belongs on `system-tech`, `code-plan`, or `test-plan`; use those instead.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.set-stage/YYYY-MM-DD_HH-MM-SS.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`), a short `## Actions` bullet list, and a `## Result` line.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop over files themselves.
- **Open type set, closed stage set** — a type is valid because a declaration for it exists (shipped or project-level), never because its name is in a list here. A stage is valid only against `empty | draft | approved | rejected | cancelled`. Reject anything else, including the removed `review` / `done` / `wtr`.
- **Path and basename never validate** — a document's type comes from its `spec_doc_type` key alone; where the file sits and what it is called are not inputs to any check in this skill.
- **Refuse silently-wrong transitions** — `cancelled` on a category-mandatory type returns an error, not a warning.
- **`spec_stage:` and `spec/<stage>` tag are coupled** — every stage write also rewrites the tag in the same edit. Never write one without the other.
- **An attachment's stage is a mirror** — a doc carrying `spec_owner_doc` is refused as a target, and every stage write on an owner cascades to its markdown attachments in the same commit, skipping only attachments in their own review.
- **Never touch the folder-note's gate** — this primitive only edits the doc's own `spec_stage`.
- **Promote on approve, never bypass a refusal** — landing `approved` on a living doc (`stages: true` AND `append_only: false`) always calls `decide promote`; its refusal (asset cancelled/halted/released) is reported, never worked around.
- **Idempotent stage, recorded run** — calling with the same file + stage leaves frontmatter unchanged but still appends a history line (the line records that the skill ran; the stage itself is idempotent).
