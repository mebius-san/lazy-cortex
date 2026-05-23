---
description: Meta-spec for protocol files — what every `<plugin>/references/<name>-protocol.md` instance must declare so consumers and experts share a stable runtime contract.
---
# Expert protocol contract

A protocol file is the formal contract between a **consumer** (skill, agent, or CLI that dispatches jobs) and one or more **expert agents** that execute them. This document is the meta-contract: what every protocol file must declare, and what both sides can rely on at runtime.

---

## 1. What a protocol file is

A protocol file is a plain markdown file at:

```
<plugin>/references/<name>.md
```

It is referenced from a **routine entry** in `lazy.settings.json` (the routine declares which protocol(s) its dispatched jobs follow) as `<plugin>:<name>` — single via `protocol: <ref>` or list via `protocols: [<ref>, ...]`. The runtime resolver (`reference_resolver.resolve(ref, category="protocols", ...)`) maps the `protocols` category to the plugin's `references/` dir, matching the repo-wide convention used by every plugin's protocol/contract docs. Expert entries in `lazy.settings.json[experts]` do NOT carry a `protocol` field — protocols are routine-side, not expert-side; the dispatcher reads them from routine cfg and writes them to each job's `config.json`. Aspects are a sibling category (see `lazy-core.expert-aspects-contract.md`): a protocol defines the request/response contract for jobs (routine-side); an aspect shapes how the expert acts (expert-side). The two layers compose — the pump lists protocols and aspects in parallel in the user-message prompt.

**Scope**: a protocol file defines only the protocol-specific contract — the `kind` enum, `role` vocabulary, field shapes, and side-effect rules for one protocol. Standard job-dir and JSON shapes (§§ 2–3) apply universally and are not repeated per protocol.

**Out of scope — protocol files MUST NOT include**:

- The consumer's `lazy.settings.json` shape — `routines:`, `experts:`, `review.classes:`, or any other settings-tree fragment. How a consumer wires routines, registers experts, or groups class-level expert lists is consumer configuration; it belongs in the functional spec for the consumer plugin and in the configure-wizard skill, not in the wire protocol.
- Tutorial JSON snippets that show "how to declare this expert" or "where to put this in settings". A protocol describes what the dispatcher sends to the expert and what the expert sends back — nothing about how a project is configured to dispatch in the first place.
- Lifecycle prose tied to a specific consumer's state machine that goes beyond what the expert observes per request (`role` value, `source/`, `context/`, `result/`, fields documented in this contract). Cross-job state transitions are the consumer's concern.

The protocol contract is the wire between dispatcher and expert. Anything that lives on either end of that wire (consumer config, state machine internals, agent persona) is out of scope. When in doubt: if an expert running this protocol does not need the information to handle one request, it does not belong in the protocol file.

**Versioning by filename** (§ 6). Incompatible changes ship as a new file with a new name; the old file stays until all consumers migrate.

---

## 2. Standard job-dir layout

Every job under `.experts/.jobs/<expert-name>/<job-id>/` follows this structure:

```
.experts/.jobs/<expert-name>/<job-id>/
├── request.json     # consumer-written (dispatcher) — job parameters + file-list arrays
├── config.json      # consumer-written (dispatcher) — agent ref + resolved protocols + git_author
├── READY            # consumer-written marker — pump picks up only after this exists
├── source/...       # consumer-written input files; layout is protocol's choice; may be absent
├── context/...      # consumer-written reference files; layout is protocol's choice; may be absent
├── result/...       # expert-written output files; layout is protocol's choice; may be absent
├── PID              # pump-written while expert subprocess is running
├── response.json    # expert-written
├── DONE             # pump-written marker after expert exits — consumer collects only after this exists
├── DEAD             # pump-written marker if pump killed the process as stuck (alternative terminal state)
└── dead.json        # pump-written audit log of the kill — paired with DEAD
```

File-role summary:

| File | Written by | Purpose |
|------|-----------|---------|
| `request.json` | dispatcher | job parameters + file-list arrays |
| `config.json` | dispatcher | agent path-ref, resolved protocols list, git_author (consumed by pump at spawn time — REQUIRED, pump aborts with `logical` error if absent) |
| `READY` | dispatcher | signals job is ready for pickup |
| `source/` | dispatcher | input files the expert processes |
| `context/` | dispatcher | reference files the expert may read |
| `result/` | expert | output files the expert writes |
| `PID` | pump | process-id while expert is running; cleared on exit |
| `response.json` | expert | outcome + optional result file-list |
| `DONE` | pump | terminal marker — expert exited cleanly (success or `outcome=error`) |
| `DEAD` | pump | terminal marker — pump killed the expert as stuck |
| `dead.json` | pump | audit log of the kill (timestamps, signals) — paired with DEAD |

Any of the `source` / `context` / `result` subdirs may be absent when no files of that kind exist for the job. The corresponding arrays in JSON may be omitted or empty. When a subdir IS present but the matching `request.json` array is empty/absent, the expert receives the directory path in its prompt but no per-file descriptions — protocols should populate the array whenever the dir contains files.

**Two terminal states**: a collected job exposes EITHER `DONE` (whether `outcome=error` or any protocol-defined success outcome) OR `DEAD` (pump killed it). `lazy-expert.list-jobs` and `lazy-expert.collect-job` distinguish them.

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
      "path": ".experts/.jobs/<expert>/<job-id>/source/<...>",
      "description": "Short prose telling expert what this file is"
    }
  ],

  "context": [
    {
      "path": ".experts/.jobs/<expert>/<job-id>/context/<...>",
      "description": "Short prose"
    }
  ],

  "result": [
    {
      "path": ".experts/.jobs/<expert>/<job-id>/result/<...>",
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
- **`source` / `context` / `result`** — optional file-list arrays. Each entry: `{path, description}`. `path` is full from the source repo root (where the daemon spawned the expert with `cwd=<source-repo>`). Expert reads / writes via these paths directly with `Read` / `Write`. When the corresponding directory exists on disk but its array is absent in `request.json`, the expert sees only the directory path in its prompt (no per-file descriptions) — protocols should populate the array whenever the dir contains files.

### response.json

```json
// Success with output files written
{
  "outcome": "<protocol-defined-enum>",
  "result": [
    {
      "path": ".experts/.jobs/<expert>/<job-id>/result/<...>",
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

**Validation:** the pump does not validate `response.json` against a schema. A syntactically malformed `response.json` is treated as `{}` and the job is still marked `DONE` — `lazy-expert.collect-job` will then return `status=done` with an empty response and no error signal. Protocol-defined `result` array enforcement (e.g. "outcome=edited requires result[]") is the consumer's responsibility, not the pump's.

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
- `main` — main-writer in a doc-review chain; may edit any non-owned section
- `<section>` — section-writer (e.g. `routing`); may edit only its owned `# <Section>` heading
- `final` — final-writer; never edits content, only raises `#review/concern` callouts
- `auto` — historian-style mechanical role; reads source only, writes one summary sentence
- `repair` — doc_doctor-style structural-repair role; rewrites broken doc, no content review
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
- what the expert **must not** write (e.g. must not modify files outside `.experts/.jobs/<job-id>/`)

### 4.9 Error categories used

Declare which of the three standard categories this protocol uses:

| Category | Meaning |
|----------|---------|
| `logical` | unknown expert; unresolvable protocol/agent reference |
| `transient` | process exit; I/O failure; temporary unavailability |
| `technical` | schema violation; missing required file |

Protocols may subset to fewer categories. They may not introduce new category names.

---

## 5. Commit responsibility

Whoever changes a file is responsible for committing that file. No actor — agent, daemon, dispatcher, pump, hook, anything — ever commits the whole tree or stages with wildcards (`git add .` / `git add -A` / `git commit -a` are forbidden). Each commit covers exactly the paths its author intentionally changed and nothing else.

Concrete consequences:

- **Agents** commit what they changed inside the **source project tree** (the document they were dispatched to revise, files they explicitly wrote per the protocol's side-effect rules). Agents NEVER commit anything under their own job dir (`.experts/.jobs/<expert>/<job-id>/` — request.json, response.json, result/, source/, context/, …). Job-dir is private scratch; it must be gitignored AND must never be `git add`-ed.
- **Dispatcher / daemon** commits only what dispatcher/daemon itself wrote (mechanical banner-tick edits, scaffolding inserts, finalize strips, history-entry appends). Never any path that an upstream actor edited.
- **Operator** commits operator's own work, on the operator's schedule.

If after all actors finish the working tree is still dirty, somebody violated this contract. The dirty paths plus `git blame` / `git log --diff-filter=M --follow` identify who. The contract makes that identification deterministic — there is exactly one author per change, with the author named.

The system MUST be correct regardless of whether an individual actor honoured this rule on any given run. The contract defines responsibility; behaviour-under-violation defines diagnostics, not correctness. A dispatcher that loses an agent's response because the agent also committed it is a dispatcher bug — the contract is not a runtime invariant the dispatcher may assume.

---

## 6. Versioning

Protocols are versioned **by filename**. There is no version field, no version syntax in reference strings.

- **Backward-compatible changes** (add optional field, add new `kind`, clarify prose): edit the existing file.
- **Incompatible changes** (rename a `kind`, remove a field, change `outcome` semantics): create a new file with a new name (e.g. `lazy-review.doc-review-v2-protocol.md`). The old file stays. Consumers migrate by updating routine cfg entries in `lazy.settings.json` to reference the new name.

No version number is embedded in the reference string. Consumers that need the old contract keep referencing the old filename.

---

## 7. Validation expectations

`lazy-core.audit` (expert-runtime phase) checks:

- Protocol file is valid markdown and parses without error.
- All required sections (§§ 4.1–4.9) are present.
- Every `kind` value listed in § 4.1 has a corresponding entry in § 4.4.
- Every routine in `lazy.settings.json` that references this protocol resolves it to an existing file via `reference_resolver`.
- Protocol filename matches the reference key used by routines.

Failures surface as `FAIL` findings; missing-but-optional content (e.g. § 4.5 "No extra fields" omitted) surfaces as `WARN`.

---

## 8. Worked example

See `lazycortex-review/references/lazy-review.doc-review-protocol.md` (forward reference — created by the dev-stage review redesign, not this document). That file is the canonical implementation of a full protocol against this contract.
