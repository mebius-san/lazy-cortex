---
name: lazy-spec.catalog-playbook
description: Level playbook for the catalog root and every product root — the ladder of system documents, the four derived level gates, the launch checkboxes that write them, the candidate requests a re-approval raises, and the routing decisions the catalog root owns.
---
# Level playbook — how `spec.catalog-coordinator` decides

This document is the law for any folder-note carrying `spec_role: catalog` (the catalog root's own note, beside the spec content root's system documents) or `spec_role: product` (a product's note, beside that product's). One playbook serves both: a repository is a product of products, and the two levels have the same documents, the same stages, the same review, and the same ladder. Where a rule applies to only one of them, this document says so; everything else is shared.

The level note is the object of coordination. It carries the four level gates, the coordinator's own body sections, and the recorded review state of the system documents beside it. It carries no `spec_asset_type` and no `spec_tools` — the level's type IS its role, and the ladder below is not a per-type declaration.

## The ladder

Four system documents live loose beside the level note, and nowhere else:

- **`vision.md`** (`system-vision`) — mandatory. What this level is, for whom, and what counts as success. On the catalog root it is the vault spec, and the split into products is a consequence of it; on a product root it is that product's own. `lazy-spec.install` seeds the root one, `lazy-spec.product-config` seeds each product's, so this playbook never hangs a `Write vision` row: the document is always already there.
- **`design.md`** (`system-design`) — optional. What the level does and why, at the level's own altitude: never an asset's behaviour, and never a construction document.
- **`ui-design.md`** (`system-ui-design`) — optional, and **the slot is inert until the type is declared**. Until a `system-ui-design` doc type exists in the resolved doc-type registry, no `Write ui-design` row hangs and the gate is simply not one of the level's declared gates. Nothing about this is a gap to report — an undeclared type is a configuration fact. No level gate takes part in the level note's paint either way: a level note keeps the icon and colour it was given when it was created, and the iconize registry reads none of the four gates (`lazy-spec.config-protocol.md` § Icon and colour).
- **`tech.md`** (`system-tech`) — optional. A narrow document of technical requirements and infrastructure decisions: stack, platforms, constraints, infrastructure decisions, boundaries. It is not a mirror of the code, it is not generated from the code, and it changes only through its own review.

**There is no sync-with-code in this ladder.** No step of this playbook reads the source tree to reconcile a system document against it, and no coordinator wake proposes such a reconciliation. A level document is written by hand or by a system-level expert, through review, full stop.

## 1. Stage promotion runs before any gate is evaluated

On every wake, before evaluating a single gate or checkbox: each system document whose `review_result` reads `approved` or `approved-with-concerns` while its `spec_stage` still reads `draft` gets `Skill(lazycortex-specs:lazy-spec.set-stage, "<doc> approved")`. The history line lands in this level note.

This ordering is not a preference. Gates below are derived from stage, so a gate evaluated before the promotion reads the stale value and stays shut on a document the review already accepted — the exact way a level document sits approved-but-unstaged forever when nothing promotes it.

A document whose review reopened and now reads `draft` again is promoted back down the same way, through the same primitive.

**A parked document is skipped.** A system document at `spec_stage: deferred` is passed over by this walk even when its `review_result` reads approved — parking outranks the verdict, and the promotion happens on the wake after `lazy-spec.set-stage <doc> draft` brings it back. A commit touching it still wakes you as an ordinary operator edit, so the level note gets put in order around it; what it never raises is a doc-transition off its own verdict. You never edit the parked document itself.

## 2. The gates are derived, all four of them

| Gate | Closes when |
|---|---|
| `spec_vision_done` | `vision.md` exists and its stage is `approved` |
| `spec_design_done` | `design.md` is ABSENT, or exists at stage `approved` |
| `spec_ui_design_done` | the `system-ui-design` type is declared AND `ui-design.md` is ABSENT, or exists at stage `approved` |
| `spec_tech_done` | `tech.md` is ABSENT, or exists at stage `approved` |

**A parked document holds its gate open.** `deferred` is neither absent nor approved, so a `design.md` / `ui-design.md` / `tech.md` sitting parked leaves its gate false exactly as a draft does — the level owes the document, the operator has simply set it aside. A parked `vision.md` leaves `spec_vision_done` false the same way.

**Only `vision.md` is owed.** The other three documents are optional, and an optional document a level never wrote is not an open obligation — it is a level that does not need one. So an absent `design.md` / `ui-design.md` / `tech.md` closes its gate exactly as an approved one does, and only the middle state — the document exists and its stage is anything other than `approved` — holds the gate open. A level with nothing but an approved vision therefore reads all four gates closed, which is the honest reading of it: nothing is owed. `vision.md` is the one exception, mandatory at both levels, so its absence never closes anything.

Every one of them is derived: the coordinator flips it itself with `flip-gate --auto` the instant the condition holds, and there is no operator signal for any of them. `spec_design_done` shares its name with the asset-level gate of the same name; they are different objects on different notes, and nothing that reads asset gates ever reads a level note.

**Downward reconciliation.** A gate already closed goes stale the moment its document appears at a stage other than `approved` — a freshly seeded document, a reopened review, a rejected re-approval. Turn it back off with `flip-gate --off --auto` and re-run the upward checks against the fresh state in the same pass, so a dependent checkbox disappears that same cycle rather than a tick later. Seeding one of the three optional documents therefore OPENS its gate, and the gate closes again when the review approves it — the gate tracks the document's own state, never the fact that work once started.

**Halt.** `spec_halted: true` takes every checkbox row down and silences every enactment, but never the four gate booleans themselves and never a `# Coordinator commands` block.

## 3. The launch checkboxes

Checkboxes live in the level note's `# Gates` section as `[!gate]` blocks. Reconcile the set on every relevant wake — hang a block the moment its precondition starts holding, remove an un-ticked one the moment it stops holding — and never tick one: ticking is the operator's gesture. The block shape is the asset coordinator's (`lazy-spec.coordination-playbook.md` Chapter 5): head line, the `- [ ] <label>` line right under it, then a blank quoted line (`>`) before any hint or attribution — a hint glued to the checkbox is its continuation and disappears in Obsidian's reading view.

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | `spec_vision_done` closed AND `design.md` doesn't exist | seed `design.md:system-design`, then seed-then-start below |
| `Write ui-design` | `spec_vision_done` closed AND the `system-ui-design` type is declared AND `ui-design.md` doesn't exist | seed `ui-design.md:system-ui-design`, then seed-then-start below |
| `Write tech` | `spec_vision_done` closed AND `tech.md` doesn't exist | seed `tech.md:system-tech`, then seed-then-start below |
| `Revise design` | a released asset's documents diverge from `design.md` (§ 5) | `lazy-review.submit` on `design.md`, the divergence carried in the submit's context |

All three `Write` rows hang together, the moment `spec_vision_done` closes. **Their order is the operator's choice, not this playbook's** — nothing here says design before tech, and no row waits on another row's document. The vision is the only ordering constraint in the ladder.

**A closed gate does not take its own row down.** An absent optional document reads done at § 2 and still hangs its `Write` row here, and the two say different things: the gate says the level owes nothing, the row says the operator may start the document whenever they choose. Only the document's own existence removes the row. Do not reconcile one against the other — a row hanging beside its own closed gate is the ordinary state of every level that has not written its optional documents yet.

**A parked document hangs a `Review` row, never a `Write` one.** Every `Write` row above reads "the document doesn't exist", and a document at `spec_stage: deferred` exists — so no `Write` row hangs for it and nothing seeds a replacement in its place, ever. What hangs instead is one `Review <doc>` row, on the same per-file condition the asset coordinator's review-launch blocks use (`lazy-spec.coordination-playbook.md` Chapter 5): the document's type declares `review` and it is not currently carrying `review_active: true`. Ticking it unparks and resubmits in one commit — `Skill(lazycortex-specs:lazy-spec.set-stage, "<doc> draft")`, then `Skill(lazycortex-review:lazy-review.submit, "<doc>")` — and the row is replaced by a history line like any other enacted tick. This is the one row of this ladder whose tick is not the seed-then-start flow, because the document is already written.

**Two ways a row does not hang at all.** The operator may declare in the level note's `# Coordinator rules` that this level needs no such document — "no tech document at this level", "no ui-design here" — and the row is then not hung, ever. Independently, a `tech.md` that exists at stage `cancelled` means the same thing after the fact: the row does not come back, and `spec_tech_done` — which a cancelled document leaves neither absent nor approved — stays out of the level's declared gates rather than reading open forever. `system-tech` is the one type of this ladder that `lazy-spec.set-stage` permits to be cancelled; `system-vision` and `system-design` are never cancelled.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/`, or `claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row: a tick is never a writer job. Seed the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <level-note-path> --doc <name>:<type>` — or `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc --root <level-note-path> --doc <name>:<type>` on the catalog root, which belongs to no product — from the type's template chain at stage `empty`. Then open its review at the writer round with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, so the class's main writer works round 1. Where the level note carries no source requests and the operator would rather write the skeleton themselves, the seed alone is the whole enactment: their commit is the ordinary operator-edit wake, and on it — a non-empty body on a document with no active review — the review opens with the same `start` call, the writer refining their text as round 1. Replace the ticked row with a history line either way.

No row of this ladder dispatches an expert job. `dispatch-job` and `cancel-job` are not in this coordinator's verb set, and a row that seems to need one has been misread.

## 4. Where the level's documents come from and what they may not do

A level document is written by its review class's own writers. The coordinator seeds it, opens its review, promotes its stage, and flips the gate it feeds — it never writes into the body of any of the four, and the sibling-doc carve-out the asset coordinator has for carrying a question or a decision candidate across documents does not exist at this level.

## 5. The event from below — a released asset (`asset-released`)

Only on a product level. When an asset of this product crosses `spec_released` into true, that asset's own wake dispatches one hop upward onto this note.

Read the released asset's `design.md` and, when it has one, its `architecture.md`, and compare what they say the product now does against what the product's own `design.md` says. No divergence: rewrite `# Status brief` and stop — a release that changed nothing at the product's altitude is the ordinary case. A divergence: hang the `Revise design` row and name the divergence plainly in `# Status brief`, so the operator sees what changed before deciding. A tick on that row opens `design.md`'s review with `Skill(lazycortex-review:lazy-review.submit, "<design.md>")`, carrying the divergence into the review's context — the document is already written, so it needs a review round, not a writer round.

One event, one action. This wake never edits an asset, never flips an asset's gate, and never wakes another coordinator.

## 6. Re-approval from above — candidate requests

A `DOC_TRANSITION` landing on `vision.md` or `design.md` that already carried an `approved` value before this one is a re-approval: the level changed its mind about something it had already settled. Compare the new text against what sits below:

- **On a product level** — against the product's unfinished assets: an asset is unfinished while `spec_released` is false and `spec_cancelled` is false. A finished asset is history; nothing reopens it from above.
- **On the catalog root** — against each product's own `vision.md` and `design.md`.

Each divergence becomes ONE candidate request:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <specs-cli> request-draft --source <the re-approved document> --title <one line naming the divergence> --body <a file holding the candidate's prose>)
```

The verb writes `<content-root>/requests/<slug>.md` at `request_status: draft` and commits it. Attribution to the document that raised the candidate goes in the request's own `spec_source_docs`, as a wikilink to the `--source` document — a request citing where it came from is exactly the cross-link that key still carries. From there the ordinary intake pipeline owns it: `lazy-spec.request-open` opens its review, the interpreter refines it, the operator accepts or rejects it, and the catalog root routes it. **You never touch a candidate you dropped** — not to amend it, not to withdraw it, not to check on it.

**No coordinator below is woken.** A re-approval at a level never fans out into asset wakes or product wakes: a candidate request is the whole of what flows downward, and it flows through the operator's own accept/reject, never around them. Name in `# Status brief` how many candidates this wake dropped and what they concern.

## 7. Status brief

Rewrite `# Status brief` on every wake — two to four sentences of plain product-language narration: what state this level is in, why it is stalled if it is, what happens next. State, never a synopsis of a document, never wake mechanics, never engine vocabulary. Keep the HTML-comment explainer line under the section's protected tag in place and write below it.

## 8. Questions and commands

Questions and one-shot commands follow the same shapes every coordinator in this plugin uses: a `[!question]` callout with `- [ ]` options is the only channel to the operator, and it must end with `> — spec.catalog-coordinator` as its own last quoted line — the ANSWER wake keys off that exact attribution. A non-empty `# Coordinator commands` section is unfolded into a numbered mini-plan in that same section, marked `✓` / `→` / `·` while it runs, and moved whole into `# History` when it finishes. A command runs even on a halted level.

When a decision does not follow unambiguously from this playbook and the rule layers below, raise a question and stop on this level. Never guess a product into existence, and never draft a candidate request from a divergence you are not sure is one.

## 9. Rule layers

From the most general to the closest, on WORKFLOW the closest wins; on PROCEDURE and INVARIANTS (the verb set, the pen surfaces, the trigger list, halt, the reconciliation discipline) this playbook wins:

1. This playbook.
2. The vault-wide operator doc at `spec.coordination_rules`.
3. Product guidelines, role `coordinator` — on a product level only.
4. The catalog root note's `# Coordinator rules`.
5. The product note's own `# Coordinator rules` — on a product level, the closest layer.

The asset coordinator reads a product note's `# Coordinator rules` as one of its own layers too. That section serves both readers; nothing in it is scoped to one of them by default.

## 10. Routing — the catalog root only

The catalog root note, and never a product note, is where a request's routing decision is made: this is the one level from which every product and both level ladders are visible at once. The wake is the terminal group of a request's own review cycle, after the operator's `[!question]` confirmation, and the whole decision follows `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.routing-playbook.md` — the `spawn` / `attach` / `reference` grammar, the duplicate-behavior pass, the loud-`reference` rule, the launched-asset rule.

This wake carries the request as its source, so no level note arrives in the job's own files: the catalog root note is derived as `<content-root>/<basename of content-root>.md`, where the content root is the `spec.vault_root` setting (default `specs`) — the note the decision is recorded against.

Two lines belong to this level beyond what that playbook carries:

- **`attach <level-doc-path>`** — attributing a request to a system document of a product or of the root. Apply stamps `spec_source_requests` onto the document itself and reopens its review; a level note carries no `## Source requests` section, so there is no intermediate stamp on the note.
- **`spawn-product key=<key> path=<spec_path> [experts=<role>:<name>[,...]] :: <description>`** — registering a new product. **There is no precondition.** A request may spawn a product at any time, whatever state the root's own ladder is in — a vault spec that is still being written does not block a product the operator has already accepted a request for. The `::` description is required on this line, one or two sentences naming what the product is.

The new product's role experts are settled during the request's own review, through a `[!question]` callout listing the candidates, so the line apply reads already carries a decided set. Apply registers the product, scaffolds its folder and its level note, seeds its `vision.md` and opens its review; from that point the product is an ordinary level and this playbook drives it.
