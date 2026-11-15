---
name: lazy-spec.change-cascade-protocol
version: 1
description: Change cascade wire shape — the `spec_targets` / `spec_cascade_done` / `spec_cascade_targets_done` keys on a change asset's status note, the virtual dispatch labels a cascade job rides on, its `target_doc` into another asset's folder, and the halt a reported conflict raises. The order of the cascade's phases is the `change` type playbook's, never this file's.
---
# Change cascade protocol — `spec_targets`

Extracted from `lazy-spec.lifecycle-protocol.md` Part 4, which keeps a stub under that number.

An asset MAY declare `spec_targets` — the existing assets its own change modifies. **This section documents the frontmatter shape and the virtual dispatch labels the cascade rides on, and nothing else. The order of the cascade's phases is a chapter of the `change` type playbook (`lazy-spec.change-playbook.md`), not a rule of this protocol.**

## Frontmatter (on the change asset's status folder-note)

```yaml
spec_targets: ["csv-export", "audit-log"]                      # optional; paths relative to the product's spec_path
spec_cascade_done: false                                       # true once every declared target has been folded
spec_cascade_targets_done: ["csv-export"]                      # tokens already folded, in fold order
```

Tokens are paths relative to the product's `spec_path` (`lazy-spec.lifecycle-protocol.md` Part 2 § Frontmatter), so a nested target is addressed by its full path.

`spec_cascade_done` and `spec_cascade_targets_done` are written by the coordinator through `note-set-key`, the same primitive that writes every other coordinator-owned frontmatter key on this note.

## The virtual dispatch labels

A cascade job is dispatched through the same `dispatch-job` verb the launch-checkbox ladder uses, keyed by labels that are **virtual**: they are never ticked checkboxes and never appear in `# Gates` at all. The expert behind such a label resolves exactly as a launch checkbox's does (from the review class of the document the job writes), and the target token a cascade job concerns rides in the dispatched job's own payload — never in the `active_job` marker, whose shape is the same three keys for every dispatch.

A cascade job carries `target_doc` like every other document-writing dispatch (`lazy-spec.launch-checkbox-protocol.md` § Dispatch), and it is the one case where that path points into ANOTHER asset's folder: the target's own `design.md` or `test-plan.md`, not the change asset's. The writer never touches that document in the working tree — it returns the folded document through its own `result/`, exactly as a launch job does. Because the destination lies outside the dispatching asset's folder, the landing is the coordinator's own move on the job-done wake rather than `gate-tick`'s. `gate-tick` neither refuses nor halts on a `target_doc` inside the folder of an asset the note lists in `spec_targets`: it retires the job's marker, records `last_job` and raises `job-done`, leaving the bundle for the coordinator. A `target_doc` in any other asset's folder, or outside the catalog, is still refused and halts the note. On that wake the coordinator calls the `land-result` verb with an explicit target (`lazy-spec.change-playbook.md` § The cascade), which is the one route allowed to place a document outside one asset folder, bounded by the spec catalog. A landed fold retires the job's bundle; a refused one leaves it for diagnosis.

A cascade job reporting `conflict: true` (per `lazy-spec.expert-signals-protocol.md`) halts the asset (`HaltReason.MERGE_CONFLICT`, `lazy-spec.lifecycle-protocol.md` Part 5) via an ordinary `flip-gate --halt` call — the coordinator invokes the same primitive any other halting caller would, never a bespoke phrase.
