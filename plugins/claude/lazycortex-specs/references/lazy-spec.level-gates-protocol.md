---
name: lazy-spec.level-gates-protocol
version: 1
description: Level gates on the catalog root and product root notes — the five derived booleans `spec_vision_done` / `spec_use_cases_done` / `spec_design_done` / `spec_ui_design_done` / `spec_tech_done`, each closed by exactly one loose document, with no ladder among them and `spec_halted` as the only overlay, and how `lazy-spec.flip-gate` validates the gate-to-note pairing.
---
# Level gates protocol — catalog root and product root

Extracted from `lazy-spec.lifecycle-protocol.md` Part 2b, which keeps a stub under that number: the asset gates stay there, this file carries the gates of a level note.

A LEVEL note — the catalog root's (`spec_role: catalog`) or a product root's (`spec_role: product`), see [status-note](./lazy-spec.status-note-protocol.md) Part 4b — carries its own five level booleans instead of the five asset gates of `lazy-spec.lifecycle-protocol.md` Part 2:

```yaml
spec_vision_done: false
spec_use_cases_done: false
spec_design_done: false
spec_ui_design_done: false
spec_tech_done: false
spec_halted: false
```

- **All five are derived, and each from exactly one document** loose beside the note: `spec_vision_done` from `vision.md`, `spec_use_cases_done` from `use-cases.md`, `spec_design_done` from `design.md`, `spec_ui_design_done` from `ui-design.md`, `spec_tech_done` from `tech.md`. There is no human-signal gate at this level and no operator gesture that closes one — `spec.catalog-coordinator` flips every one of them with `flip-gate --auto`.
- **An absent optional document closes its gate.** `use-cases.md`, `design.md`, `ui-design.md` and `tech.md` are optional, so `spec_use_cases_done` / `spec_design_done` / `spec_ui_design_done` / `spec_tech_done` each close when their document is ABSENT or exists at stage `approved`, and open only in the middle state — the document exists at some other stage. `vision.md` is the one mandatory document of the ladder, so `spec_vision_done` alone requires an approved document and never closes on absence.
- **There is no ladder among them.** Unlike the asset gates' strict S0..S6 order, the five level gates are independent booleans: `vision` gates the launch CHECKBOXES that write the other four documents, never their gate values, and any of `use-cases` / `design` / `ui-design` / `tech` may close before another or never close at all. The one ordering on a product root — `use-cases.md` holding the review of `design.md` — is a hold on a review, never on a gate value. A doctor precedence check does not apply here.
- **A gate may be undeclared.** An operator may declare in a level note's `# Coordinator rules` that this level needs no `use-cases`, no `design`, no `ui-design` or no `tech` document at all (a `tech.md` or `use-cases.md` at stage `cancelled` says the same after the fact), and `use-cases.md` / `ui-design.md` are product-root documents only — the catalog root never owes either, so `spec_use_cases_done` / `spec_ui_design_done` there read closed on absence like any optional document. An undeclared gate is not a gap and never a finding — the level playbook owns which of the five this level actually has.
- **`spec_halted` is the level's only overlay.** There is no `spec_cancelled` and no `spec_released` on a level note: a level is not abandoned and not shipped.

`lazy-spec.flip-gate` validates both halves of the pairing on every call: a gate name outside `{the five asset gates} ∪ {the five level gates}` is refused, and so is an asset gate on a level note or a level gate on a status note. What each gate closes on is the level playbook's (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 2), exactly as the asset gates' readiness is the type playbook's.
