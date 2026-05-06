# Expert protocol contract

A protocol file is the formal contract between a **consumer** (skill, agent, or CLI that dispatches jobs) and one or more **expert agents** that execute them. This document is the meta-contract: what every protocol file must declare, and what both sides can rely on at runtime.

---

## 1. What a protocol file is

A protocol file is a plain markdown file at:

```
<plugin>/references/<name>.md
```

It is referenced in `experts.settings.json` as `<plugin>:<name>` (e.g. `lazycortex-review:doc-review`). The runtime resolver (`reference_resolver.resolve(ref, category="protocols", ...)`) maps the `protocols` category to the plugin's `references/` dir, matching the repo-wide convention used by every plugin's protocol/contract docs.

**Scope**: a protocol file defines only the protocol-specific contract — the `kind` enum, `role` vocabulary, field shapes, and side-effect rules for one protocol. Standard job-dir and JSON shapes (§§ 2–3) apply universally and are not repeated per protocol.

**Versioning by filename** (§ 6). Incompatible changes ship as a new file with a new name; the old file stays until all consumers migrate.

---

## 2. Standard job-dir layout

Every job under `.claude/experts/.jobs/<expert-name>/<job-id>/` follows this structure:

```
.claude/experts/.jobs/<expert-name>/<job-id>/
├── request.json     # consumer-written
├── READY            # consumer-written marker; daemon picks up only after this exists
├── source/...       # consumer-written input files; layout is protocol's choice; may be absent
├── context/...      # consumer-written reference files; layout is protocol's choice; may be absent
├── result/...       # expert-written output files; layout is protocol's choice; may be absent
├── response.json    # expert-written
└── DONE             # expert/daemon-written marker; consumer collects only after this exists
```

File-role summary:

| File | Written by | Purpose |
|------|-----------|---------|
| `request.json` | consumer | job parameters + file-list arrays |
| `READY` | consumer | signals job is ready for pickup |
| `source/` | consumer | input files the expert processes |
| `context/` | consumer | reference files the expert may read |
| `result/` | expert | output files the expert writes |
| `response.json` | expert | outcome + optional result file-list |
| `DONE` | expert/daemon | signals job is complete |

Any of the `source` / `context` / `result` subdirs may be absent when no files of that kind exist for the job. The corresponding arrays in JSON may be omitted or empty.

---

## 3. Standard request and response fields

### request.json

```json
{
  "kind": "<protocol-defined-string>",
  "role": "<free-form string — expert's role for this job>",
  "request": "<free-form prose — what the consumer is asking the expert to do>",

  "source": [
    {
      "path": ".claude/experts/.jobs/<expert>/<job-id>/source/<...>",
      "description": "Short prose telling expert what this file is"
    }
  ],

  "context": [
    {
      "path": ".claude/experts/.jobs/<expert>/<job-id>/context/<...>",
      "description": "Short prose"
    }
  ],

  "result": [
    {
      "path": ".claude/experts/.jobs/<expert>/<job-id>/result/<...>",
      "description": "Where expert should write this output file"
    }
  ]

  // protocol-specific extra fields here (e.g. round, section-pointer)
}
```

Standard field semantics:

- **`kind`** — selects the operation type; must match a value from the protocol's `kind` enum.
- **`role`** — free-form, but the protocol enumerates the values its expert prompt handles and how each shifts behaviour. Consumer sets it per-job.
- **`request`** — free-form prose: the actual instruction or question. Not metadata. Protocol may suggest a template.
- **`source` / `context` / `result`** — optional file-list arrays. Each entry: `{path, description}`. `path` is full from the source repo root (where the daemon spawned the expert with `cwd=<source-repo>`). Expert reads / writes via these paths directly with `Read` / `Write`.

### response.json

```json
// Success with output files written
{
  "outcome": "<protocol-defined-enum>",
  "result": [
    {
      "path": ".claude/experts/.jobs/<expert>/<job-id>/result/<...>",
      "description": "Short prose telling consumer what's in the file"
    }
  ]

  // protocol-specific extra fields here
}

// Success with no output (e.g. confirmed / empty / nothing-to-change)
{
  "outcome": "<enum>"
}

// Error
{
  "outcome": "error",
  "error": {
    "category": "logical" | "transient" | "technical",
    "message": "Human-readable description"
  }
}
```

`outcome=error` is a reserved value across all protocols. Protocols may not define a `kind` or `outcome` value named `error`.

---

## 4. Protocol-specific definition

Each protocol file **must** declare all of the following sections:

### 4.1 `kind` enum

List every operation type the protocol supports. One-line description per value.

Example shape:
```
- `review` — initial review pass; expert edits source files in-place
- `final_review_doc` — final pass; expert writes a review document only
- `repair` — targeted repair of issues identified in a prior review
```

### 4.2 `role` vocabulary

Enumerate the `role` strings the expert prompt knows to handle. For each value, describe how it shifts the expert's behaviour. Protocol must not leave `role` as an undocumented free-form field.

Example shape:
```
- `active_writer` — expert may edit source files directly
- `final_check` — expert writes only to result/, no source edits
```

### 4.3 `request` conventions

Describe what the prose `request` field should look like for each `kind`. Protocol may provide a template string. If the format is unconstrained, say so explicitly.

Example:
```
For kind=review: a 1–2 sentence directive naming the document being reviewed
and what to focus on. E.g. "Review walkthroughs/foo.md for accuracy and tone."
```

### 4.4 Per-kind subdir contents

For each `kind`, specify:
- what goes in `source/` (required files, naming conventions)
- what goes in `context/` (optional supporting files)
- what the expert writes to `result/` (output files, naming conventions)

### 4.5 Extra `request.json` fields

List any fields beyond the standard four (`kind`, `role`, `request`, and the three file-list arrays). For each: name, type, required/optional, semantics.

If none: state "No extra fields."

### 4.6 `outcome` enum

List every `outcome` value the protocol defines (excluding the reserved `error`). One-line description per value.

Example:
```
- `edited` — expert modified one or more source files
- `confirmed` — expert reviewed and found nothing to change
- `empty` — nothing to review (source was empty or absent)
- `finalized` — final-review document written
```

### 4.7 Extra `response.json` fields

List any fields beyond `outcome` and `result` array. For each: name, which `outcome` values it appears with, semantics.

If none: state "No extra fields."

### 4.8 Side-effects rules

State explicitly:
- what the expert **may** write outside `result/` (e.g. editing `source/` files in-place for `kind=review`)
- what the expert **must not** write (e.g. must not modify files outside `.claude/experts/.jobs/<job-id>/`)

### 4.9 Error categories used

Declare which of the three standard categories this protocol uses:

| Category | Meaning |
|----------|---------|
| `logical` | unknown expert; unresolvable protocol/agent reference |
| `transient` | process exit; I/O failure; temporary unavailability |
| `technical` | schema violation; missing required file |

Protocols may subset to fewer categories. They may not introduce new category names.

---

## 5. Versioning

Protocols are versioned **by filename**. There is no version field, no version syntax in reference strings.

- **Backward-compatible changes** (add optional field, add new `kind`, clarify prose): edit the existing file.
- **Incompatible changes** (rename a `kind`, remove a field, change `outcome` semantics): create a new file with a new name (e.g. `doc-review-v2.md`). The old file stays. Consumers migrate by updating `experts.settings.json` to reference the new name.

No version number is embedded in the reference string (`lazycortex-review:doc-review`). Consumers that need the old contract keep referencing the old filename.

---

## 6. Validation expectations

`lazy-core.audit` (expert-runtime phase) checks:

- Protocol file is valid markdown and parses without error.
- All required sections (§§ 4.1–4.9) are present.
- Every `kind` value listed in § 4.1 has a corresponding entry in § 4.4.
- Every expert agent in `experts.settings.json` that references this protocol has a resolvable agent file.
- Protocol filename matches the reference key in `experts.settings.json`.

Failures surface as `FAIL` findings; missing-but-optional content (e.g. § 4.5 "No extra fields" omitted) surfaces as `WARN`.

---

## 7. Worked example

See `lazycortex-review/references/doc-review.md` (forward reference — created by the dev-stage review redesign, not this document). That file is the canonical implementation of a full protocol against this contract.
