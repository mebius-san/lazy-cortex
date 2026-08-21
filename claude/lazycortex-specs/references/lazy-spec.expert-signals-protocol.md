---
name: lazy-spec.expert-signals-protocol
version: 3
description: The wire this file owns — two `request.json` extra fields naming files the expert reads in place, two `response.json` extra fields, and the closed list of things an expert dispatched against a spec asset is forbidden to do. Every markup shape an expert writes to signal the coordinator (asset proposals, in-doc questions, decision-candidate markers) is owned by the callout and tag registry in `lazycortex-core:lazy-core.markdown-style`, pointed to below by name.
---
# Expert → coordinator signal protocol v3

This is the wire contract for the one-directional channel every expert dispatched against a spec asset (designer, architect, planner, developer, tester — any class, any product) uses to reach `spec.coordinator` without ever acting on the spec system directly. `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md` is the coordinator's own reasoning about what to DO once a signal arrives; `lazy-core.markdown-style.md`'s callout and tag registry owns the concrete markup shape of every signal named below. This file owns only the two `request.json` extra fields, the two `response.json` extra fields, and the hard prohibitions — on a disagreement about a markup FORMAT, the markdown-style doc wins (playbook § 12).

An expert reaches the coordinator through exactly three markup shapes, all authored INSIDE the document the expert is already writing or reporting into — never on a folder-note, never in another asset's document, never via a side channel:

- **`[!asset-proposal]`** — the single mechanism for proposing a new asset (create / link / reopen, mandatory three-way choice for bugs). Shape, fields, and materialization timing: `lazy-core.markdown-style.md` § The `[!asset-proposal]` callout.
- **`[!question]` (expert-authored)** — an expert's own question, landed inside the document it is writing, distinct from the coordinator's own `[!question]` on a folder-note. Shape and the doc-resubmit mechanic: `lazy-core.markdown-style.md` § The `[!question]` callout (expert-authored).
- **`[!decision-candidate]`** — a call the job wasn't told to make, awaiting the operator's explicit accept/reject verdict; a signal, never a decision, and an unanswered one blocks Ready exactly as an unanswered question does. Like every signal, it lands only inside the document the expert is itself writing or reporting into. Shape (mandatory accept/reject checkbox pair): `lazy-core.markdown-style.md` § The `[!decision-candidate]` callout.

## `request.json` extra fields

Two extra fields, both optional, both arrays of repo-relative paths pointing into the working tree:

- `guidelines` — the guideline documents the dispatcher resolved for this job's role, followed by the ones that apply to every role, in that order. Absent when the product declares none.
- `decisions` — the asset's own `decisions.md` first, the owning product's second, each omitted when its file does not exist. The two share a basename, so the order is the only thing that distinguishes them and is therefore fixed, never incidental. An absent registry is normal (they are created lazily) and is never a warning.

**The expert opens these paths in the working tree directly.** They are deliberately not copied into the job dir: a guideline and a decisions registry are living documents that other jobs keep writing to, and the expert must read the file as it stands when it runs rather than a snapshot of it. Nothing under `source/` or `context/` corresponds to them.

## `response.json` extra fields

Two extra fields, both riding alongside the ordinary envelope (`outcome` / `result` / `error`, owned by `lazy-core.expert-runtime-contract.md` — this protocol never redefines or replaces `outcome`; these fields only add detail to an `outcome: error` response):

- `blocked: <subtype> <detail>` — the planner's last-resort outcome when it cannot produce a plan; two subtypes:
  - `blocked: missing decision <what>` — the planner cannot decompose a plan at all because the source doc (`design.md` or `architecture.md`) lacks a decision the plan needs. `<what>` names the missing decision in one short phrase. The coordinator drives the round trip back up the chain from this signal: the designer/architect updates the source doc, the doc is re-reviewed, the planner is redispatched.
  - `blocked: already-covered <summary>` — the planner established, during its mandatory reading of the code, that EVERY goal the source doc states is already implemented. `<summary>` is one short phrase; `error.message` carries the full evidence — for each goal of the spec, the code paths covering it, never a bare claim. No plan document is written, so there is nothing to submit into review. The coordinator verifies the evidence and escalates to the operator per `lazy-spec.coordination-playbook.md` Chapter 11; it never cancels the asset on this signal alone.
- `conflict: true` — set by either half of a change-cascade job pair when its delta could not be applied cleanly to the target document it was folding into. The coordinator halts the change asset (`HaltReason.MERGE_CONFLICT`) on seeing this field, regardless of which half of the pair reported it.

## Attachments policy

This channel permits attachments — files an expert creates beside its target document rather than under `result/`.

- **Where.** Flat in the asset folder, beside the asset's documents. There is no attachments subfolder and no other legal location.
- **Naming.** Unconstrained; pick a name that says what the file is.
- **Frontmatter of a markdown attachment.** Two keys, both written by the creating expert at creation time, neither derived later:
  - `spec_owner_doc: <owner>.md` — the sibling document the attachment belongs to. It decides which job may write to the file, and it keeps the file out of the asset's gates.
  - `spec_doc_type: <type>` — what kind of document the file is. It decides the file's review class and its stage rules.

  These record two different facts and are not one fact under two names. A file may be missing either one independently, and each omission is escalated on its own.
- **A non-markdown attachment carries no frontmatter.** Its ownership is recorded instead by the coordinator, in the `# Attachments` section of the asset's status folder-note.

## Hard prohibitions

An expert dispatched against a spec asset MUST NOT, under any circumstance:

- **Create an asset.** The `[!asset-proposal]` callout above is the only mechanism for proposing one; materialization is exclusively the coordinator's act, after the containing document is accepted.
- **Touch a markdown document of another asset, or any folder-note.** A proposal, a question, or a decision-candidate marker lands only in the document the expert is itself writing or reporting into. The prohibition covers the asset's markdown documents and its status folder-note; it does not reach the expert's own attachments, which the section above authorises.
- **Edit an attachment another document owns.** An attachment belongs to the document it was created beside — a markdown attachment records it as `spec_owner_doc` in its own frontmatter, a non-markdown one through the coordinator's registry on the folder-note. Only the job whose own result document is that owner writes to it; every other role reads it and leaves it alone.
- **Tick a launch checkbox.** Ticking a `- [ ]` / `- [x]` box in an asset's `# Gates` section is exclusively an operator gesture (or, in `lazy-spec.drive`'s no-daemon mode, the operator's own spoken word translated into a tick on their behalf) — never an expert's.
- **Record a decision anywhere but a living doc.** `design.md`, `architecture.md`, and the product's `tech.md` are the only legal home for a decision. A plan is a decomposition of decisions already made elsewhere and a report is a journal — neither is ever a decision's source of truth, so an expert never treats writing to either as recording one.
- **Rewrite `code-report.md` / `test-report.md` in response to review comments.** A main-writer dispatched on one of the two report kinds never edits the report's own prose to answer a reviewer's comment — a comment on a report means the underlying WORK needs redoing, not the journal's words. The coordinator's continuation dispatch (`lazy-spec.coordination-playbook.md` Chapter 6) redoes the work and appends a fresh entry to the same journal; it never rewrites what an earlier entry already said.
