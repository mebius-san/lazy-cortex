---
name: spec.set-stage
description: Use to change the per-file `spec_stage` of an authored spec doc (design/tech/plan/bug). Accepts a stage from the closed set `empty | draft | approved | rejected | cancelled`, rewrites `spec_stage` in frontmatter, mirrors the `spec/<stage>` tag, and appends a transition line to the nearest folder-note's `# History`. Every per-file stage change in the system goes through this primitive.
execution-discipline-waiver: "Single-purpose primitive — wraps the per-file-stages reference; no multi-phase orchestration where step-skip can hide."
---
# Set Per-file Stage

Primitive skill that updates an authored doc's per-file `spec_stage`. Other `spec.*` skills delegate to this rather than edit frontmatter directly.

The authoritative definition of per-file stage semantics lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`. This skill never restates the semantics — point at it for what each stage means. (That reference still describes an older stage set and is rewritten in a later phase; the closed stage set this skill enforces is stated inline below.)

## Input

1. **File path** — absolute or vault-relative path to an authored doc. The doc's `spec_role` MUST be one of `design`, `tech`, feature/change-level `plan`, or `bug`. Other roles are rejected (non-authored docs do not carry per-file stage).
2. **New stage** — exactly one of the closed set `empty | draft | approved | rejected | cancelled`. Anything else (including the removed `review` / `done` / `wtr` values) is rejected with a clear error. "In review" is now expressed as `spec_stage: draft` + `review_active: true` on the doc; "accepted" is `approved`.
3. **Optional author** — free-text name recorded in the folder-note history line. Defaults to `spec.set-stage` (the skill's own name).

## Process

### 1. Validate the file

- Read the file's frontmatter. Verify `spec_role` is an authored-doc role (`design`, `tech`, `plan`, or `bug`). If not, refuse with a clear message naming the file and its `spec_role`.
- Verify the file's path matches its role: feature/change-level `plan.md` means the file lives under `<spec_path>/features/<feat>/` or `<spec_path>/changes/<change-name>/`, NOT at the product root. `bug.md` (role `bug`) must live under `<spec_path>/bugs/<bug-name>/`; bug-level `plan.md` must live there too.
- Validate the requested stage against the closed set `empty | draft | approved | rejected | cancelled`. If the value is not in the set, refuse — name the offending value and list the closed set. For the removed values specifically: `review` → use `draft` + `review_active: true`; `done` → use `approved`; `wtr` → use `draft` or `approved` per intent.
- Check the `cancelled`-allowed rules in `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`: refuse `cancelled` on `design.md` (feature/change mandatory doc) AND on `bug.md` (bug mandatory doc). `tech.md` and `plan.md` MAY be cancelled (docs-only feature / no-code bug fix).

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

The mirror is required, not optional. `spec.doctor` flags any mismatch as a finding.

### 3. Append to the nearest folder-note's `# History`

The folder-note is the file whose basename matches the enclosing folder (e.g., `features/chapter-log/chapter-log.md`). For `design.md` / `tech.md` / `plan.md` under `<spec_path>/features/<feat>/` or `<spec_path>/changes/<change-name>/`, and for `bug.md` / `plan.md` under `<spec_path>/bugs/<bug-name>/`, the folder-note is in the same directory. For product-level authored docs at the product root (`<spec_path>/design.md` / `<spec_path>/tech.md`), there is no status folder-note in scope (the product folder-note is operator-zone) — skip the history step.

When a folder-note is in scope, append one line to its `# History` section:

```
- <YYYY-MM-DD> — spec.set-stage · <doc>.md spec_stage <old>→<new>
```

`<doc>` is the doc's basename (e.g. `design`). Substitute the resolved author for `spec.set-stage` when an author was passed. Use UTC date (`date -u +%Y-%m-%d`). Do not touch existing history entries or any frontmatter of the folder-note. If the folder-note has no `# History` section, create one at the end of the body.

### 3a. Recompute the category container note stats

The asset's category container note is the note whose basename matches the category folder that holds the asset (e.g. `features/features.md` for an asset under `features/<slug>/`). When that container note exists, refresh its `<!-- spec:stats:* -->` region so the bucket counts reflect this stage change:

```
Bash(lazycortex-specs render-container-stats <category_note>)
```

Then `git add` the category note into the SAME commit as the doc and folder-note edits. Guard: skip silently when the category container note does not exist (a product-level authored doc with no category container, or a container carrying no stats markers — `render-container-stats` is a no-op there).

### 4. Do NOT advance the folder-note's gate

This primitive only edits the doc's own per-file `spec_stage`. It does NOT evaluate folder-level gate transitions, gate side-effects, or plan-step progression. Those are the responsibility of the gate machinery.

## Output

- The file's new `spec_stage`.
- The folder-note path + the appended history line (or `no folder-note in scope` when at product level).

## Failure modes

- **`/spec.set-stage` refuses with: file `spec_role` is not an authored-doc role** — the target file's `spec_role` is not `design` / `tech` / `plan` / `bug` → run on an authored doc instead.
- **`/spec.set-stage` refuses with: stage `<value>` is not in the closed set** — passed a value outside `empty | draft | approved | rejected | cancelled` (e.g. the removed `review` / `done` / `wtr`) → pass `draft` + set `review_active: true` for in-review, `approved` for accepted, or the correct closed-set value per intent.
- **`/spec.set-stage` refuses with: cancelled not allowed on `<file>`** — attempted `cancelled` on `design.md` or `bug.md` (mandatory docs) → cancellation belongs on `tech.md` (docs-only feature) or `plan.md` (no-code bug fix); use those instead.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.set-stage/YYYY-MM-DD_HH-MM-SS.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`), a short `## Actions` bullet list, and a `## Result` line.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop over files themselves.
- **Closed stage set** — `empty | draft | approved | rejected | cancelled` only. Reject anything else, including the removed `review` / `done` / `wtr`.
- **Refuse silently-wrong transitions** — `cancelled` on `design.md` OR on `bug.md` returns an error, not a warning.
- **`spec_stage:` and `spec/<stage>` tag are coupled** — every stage write also rewrites the tag in the same edit. Never write one without the other.
- **Never touch the folder-note's gate** — this primitive only edits the doc's own `spec_stage`.
- **Idempotent stage, recorded run** — calling with the same file + stage leaves frontmatter unchanged but still appends a history line (the line records that the skill ran; the stage itself is idempotent).
