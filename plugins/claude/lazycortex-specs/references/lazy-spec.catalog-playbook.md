---
name: lazy-spec.catalog-playbook
description: Level playbook for the catalog root and every product root — the ladder of system documents, the five derived level gates, the launch checkboxes that write them, the product's architecture and standing test plan; the release owner's `Start release` row lives in `lazy-spec.release-owner-playbook.md` and the catalog root's routing lines in `lazy-spec.routing-playbook.md`.
---
# Level playbook — how `spec.catalog-coordinator` decides

This document is the law for any folder-note carrying `spec_role: catalog` (the catalog root's own note, beside the spec content root's system documents) or `spec_role: product` (a product's note, beside that product's). One playbook serves both: a repository is a product of products, and the two levels have the same documents, the same stages, the same review, and the same ladder. Where a rule applies to only one of them, this document says so; everything else is shared.

The level note is the object of coordination. It carries the five level gates, the coordinator's own body sections, and the recorded review state of the system documents beside it. It carries no `spec_asset_type` and no `spec_tools` — the level's type IS its role, and the ladder below is not a per-type declaration.

## The ladder

Seven system documents live loose beside the level note, and nowhere else — five on the gated ladder, two beside it:

- **`vision.md`** (`system-vision`) — mandatory. What this level is, for whom, and what counts as success. On the catalog root it is the vault spec, and the split into products is a consequence of it; on a product root it is that product's own. `lazy-spec.install` seeds the root one, `lazy-spec.product-config` seeds each product's, so this playbook never hangs a `Write vision` row: the document is always already there.
- **`use-cases.md`** (`system-use-cases`) — optional, **product roots only**. What the product's users need of it as a whole, in their own language: its actors and the scenarios that cross its assets, never a system internal — the document each asset's own `use-cases.md` refines, the way an asset design refines the product design. It sits between the vision and the design in the reading chain (§ 3). The catalog root never carries one: no `Write use-cases` row hangs there and its gate reads closed on absence like any optional document. A `use-cases.md` the operator wrote at the content root is the project-level document typed `use-cases`, not a document of this ladder: the catalog root promotes nothing on it and its gate stays closed.
- **`design.md`** (`system-design`) — optional. What the level does and why, at the level's own altitude: never an asset's behaviour, and never a construction document. No build revises it: contradictions between it and the assets' designs are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).
- **`ui-design.md`** (`system-ui-design`) — optional, **product roots only**. The product's shared look: its design system, the screen patterns that recur across assets, the navigation skeleton the assets' screens attach to — the document each asset's own `ui-design.md` refines, the way an asset design refines the product design. The catalog root never carries one: no `Write ui-design` row hangs there and its gate reads closed on absence like any optional document. No level gate takes part in the level note's paint either way: a level note keeps the icon and colour it was given when it was created, and the iconize registry reads none of the five gates (`lazy-spec.config-protocol.md` § Icon and colour).
- **`tech.md`** (`system-tech`) — optional. A narrow document of the technologies the level is built with: stack and platforms, and at a product root only what differs from the content-root document. It is not a mirror of the code and not a description of how the code is arranged; `/lazy-spec.sync-with-code` keeps its stack, versions and platforms in line with the code.
- **`architecture.md`** (`system-architecture`) — optional, **product roots that own releases only** (the outermost product in its chain whose record declares a `source`). The standing document of how the product's code is arranged — module boundaries, dependency direction, the contracts between parts — the one document every release build starts from: the architect revises it against the delta's designs at the start of each build (`lazy-spec.release-playbook.md`, "The build"), and a revision lands here and goes through this level's ordinary review. No asset carries an `architecture.md` of its own. It feeds no level gate.
- **`test-plan.md`** (`system-test-plan`) — optional, **product roots that own releases only**. How the product is tested at all: how its environment is brought up, which regression runs on every release, what counts as a smoke test. The release's tester composes each release's own test plan from it, from the included assets' test cases and from the regression. It feeds no level gate.

A product's `releases/` folder sits beside these documents and outside the container tallies: a release is the product's unit of implementation, never one of its unfinished assets.

## 1. Stage promotion runs before any gate is evaluated

On every wake, before evaluating a single gate or checkbox: each system document whose `review_result` reads `approved` or `approved-with-concerns` while its `spec_stage` still reads `draft` is promoted by one `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> promote-approved <level_note>` call, its `touched_paths` folded into the wake commit. No history line lands.

This ordering is not a preference. Gates below are derived from stage, so a gate evaluated before the promotion reads the stale value and stays shut on a document the review already accepted — the exact way a level document sits approved-but-unstaged forever when nothing promotes it.

A document already `approved` whose review reopens keeps its stage: nothing moves a level document back down, and its re-approval is restamped by the same call, its basename passed as `--transitioned <basename>` (§ 6).

**A parked document is skipped.** A system document at `spec_stage: deferred` is passed over by this walk even when its `review_result` reads approved — parking outranks the verdict, and the promotion happens on the wake after `lazy-spec.set-stage <doc> draft` brings it back. A commit touching it still wakes you as an ordinary operator edit, so the level note gets put in order around it; what it never raises is a doc-transition off its own verdict. You never edit the parked document itself.

## 2. The gates are derived, all five of them

| Gate | Closes when |
|---|---|
| `spec_vision_done` | `vision.md` exists and its stage is `approved` |
| `spec_use_cases_done` | `use-cases.md` is ABSENT, or exists at stage `approved` |
| `spec_design_done` | `design.md` is ABSENT, or exists at stage `approved` |
| `spec_ui_design_done` | `ui-design.md` is ABSENT, or exists at stage `approved` |
| `spec_tech_done` | `tech.md` is ABSENT, or exists at stage `approved` |

**A parked document holds its gate open.** `deferred` is neither absent nor approved, so a `use-cases.md` / `design.md` / `ui-design.md` / `tech.md` sitting parked leaves its gate false exactly as a draft does — the level owes the document, the operator has simply set it aside. A parked `vision.md` leaves `spec_vision_done` false the same way.

**Only `vision.md` is owed.** The other four gated documents are optional, and an optional document a level never wrote is not an open obligation — it is a level that does not need one. So an absent `use-cases.md` / `design.md` / `ui-design.md` / `tech.md` closes its gate exactly as an approved one does, and only the middle state — the document exists and its stage is anything other than `approved` — holds the gate open. A level with nothing but an approved vision therefore reads all five gates closed, which is the honest reading of it: nothing is owed. `vision.md` is the one exception, mandatory at both levels, so its absence never closes anything.

Every one of them is derived: the coordinator flips it itself with `flip-gate --auto` the instant the condition holds, and there is no operator signal for any of them. `architecture.md` and `test-plan.md` have no gate: their stage is promoted by § 1 and their `Review` rows hang by § 3, and nothing in the ladder waits on them. `spec_design_done` shares its name with the asset-level gate of the same name; they are different objects on different notes, and nothing that reads asset gates ever reads a level note.

**Downward reconciliation.** A gate already closed goes stale the moment its document appears at a stage other than `approved` — a freshly seeded document, a parked one. Turn it back off with `flip-gate --off --auto` and re-run the upward checks against the fresh state in the same pass, so a dependent checkbox disappears that same cycle rather than a tick later. Seeding one of the four optional documents therefore OPENS its gate, and the gate closes again when the review approves it — the gate tracks the document's own state, never the fact that work once started.

**Halt.** `spec_halted: true` takes every checkbox row down and silences every enactment, but never the five gate booleans themselves and never a `# Coordinator commands` block.

## 3. The launch checkboxes

Checkboxes live in the level note's `# Gates` section as `[!gate]` blocks. Reconcile the set on every relevant wake — hang a block the moment its precondition starts holding, remove an un-ticked one the moment it stops holding — and never tick one: ticking is the operator's gesture. The block shape is the asset coordinator's (`lazy-spec.coordination-playbook.md` Chapter 5): head line, the `- [ ] <label>` line right under it, then a blank quoted line (`>`) before any hint or attribution — a hint glued to the checkbox is its continuation and disappears in Obsidian's reading view.

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write use-cases` | `spec_vision_done` closed AND the level is a product root AND `use-cases.md` doesn't exist | seed `use-cases.md:system-use-cases`, then seed-then-start below |
| `Write design` | `spec_vision_done` closed AND `design.md` doesn't exist | seed `design.md:system-design`, then seed-then-start below |
| `Write ui-design` | `spec_vision_done` closed AND the level is a product root AND `ui-design.md` doesn't exist | seed `ui-design.md:system-ui-design`, then seed-then-start below |
| `Write tech` | `spec_vision_done` closed AND `tech.md` doesn't exist | seed `tech.md:system-tech`, then seed-then-start below |
| `Write architecture` | `spec_vision_done` closed AND the level is a product root that owns releases AND `architecture.md` doesn't exist | seed `architecture.md:system-architecture`, then seed-then-start below |
| `Write test-plan` | `spec_vision_done` closed AND the level is a product root that owns releases AND `test-plan.md` doesn't exist | seed `test-plan.md:system-test-plan`, then seed-then-start below |

**A product that owns releases also follows `lazy-spec.release-owner-playbook.md`** — which product owns them, the `Start release` row it alone hangs beside this table, the release start, and the first-step revision of its `architecture.md`.

All six `Write` rows hang together on a product root that owns releases, the moment `spec_vision_done` closes — four on a product root that owns none; the catalog root hangs `Write design` and `Write tech` only. **Which document the operator starts first is their choice, not this playbook's** — nothing here says design before tech, and no row waits on another row's document. Two ordering constraints hold in the ladder, and neither takes a row down: the vision gates every `Write` row, and on a product root the use cases hold the design's review.

**The use cases hold the design's review.** The reading chain at this level is vision → use-cases → design, exactly as on a feature asset (`lazy-spec.feature-playbook.md`, "Use-cases and ui-design"): when a product's `use-cases.md` exists, `design.md`'s review is not continued until `use-cases.md` reaches `approved` or `cancelled`, and the design's writer reads it once it is approved (a cancelled `use-cases.md` releases the hold with nothing to read). An absent `use-cases.md` blocks nothing. The hold never takes `Write design` down and never stops the seed: a tick on that row while `use-cases.md` is still unsettled seeds `design.md` as usual, and the `lazy-review.start` of seed-then-start waits for the wake on which `use-cases.md` reaches `approved` or `cancelled`.

**A closed gate does not take its own row down.** An absent optional document reads done at § 2 and still hangs its `Write` row here, and the two say different things: the gate says the level owes nothing, the row says the operator may start the document whenever they choose. Only the document's own existence removes the row. Do not reconcile one against the other — a row hanging beside its own closed gate is the ordinary state of every level that has not written its optional documents yet.

**Every existing level document hangs a `Review` row while it is outside review.** Each of the level's seven documents — `vision.md`, `use-cases.md`, `design.md`, `ui-design.md`, `tech.md`, `architecture.md`, `test-plan.md` — that exists, whose type declares `review: true` and not `append_only: true`, and which does not carry `review_active: true`, hangs one `Review <doc>` row, in any stage except `cancelled`: `empty`, `draft`, `approved`, `rejected` and `deferred` alike. It is the asset coordinator's review-launch rule unchanged (`lazy-spec.coordination-playbook.md` Chapter 5), and so is its mechanism: `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> review-rows <level-note-path>` writes the rows on every wake before you reconcile the rows of the table above and again right after you enact a tick; apart from the row you have just enacted, you hang and remove none of them by hand. A tick is enacted exactly as that chapter says, its `empty` and `deferred` cases and its still-empty template included. The `Review` rows are the one family of this ladder whose tick is not the seed-then-start flow, because the document already exists — and they sit beside the `Write` rows without overlapping them, since a `Write` row hangs only for a document that does not exist.

The same verb lays the whole `# Gates` section out, your `Write` rows included: under `## Next step` (`## Следующий шаг`) every row that moves the level forward, under `## Re-review` (`## Повторное ревью`) the `Review` rows of already approved documents, each group in writing order — the ladder's, with the two documents beside it slotted in before `tech` (vision, use-cases, design, ui-design, architecture, test-plan, tech), and last, under `## Conflicts` (`## Конфликты`), the coherence check's conflict callouts, carried byte for byte. You never write a sub-heading yourself, and every edit of `# Gates` ends with `review-rows`: hang, take down or reword a row of the table above by hand, then run the verb once more.

**Two ways a row does not hang at all.** The operator may declare in the level note's `# Coordinator rules` that this level needs no such document — "no tech document at this level", "no ui-design here", "no use-cases here", "no architecture document" for a product without code — and the row is then not hung, ever. Independently, a `tech.md` that exists at stage `cancelled` means the same thing after the fact: the row does not come back, and `spec_tech_done` — which a cancelled document leaves neither absent nor approved — stays out of the level's declared gates rather than reading open forever. A `use-cases.md` at stage `cancelled` reads the same way for `Write use-cases` and `spec_use_cases_done`. The `set-stage` verb refuses `cancelled` on `system-design`; `system-vision` is never cancelled either, by this playbook's rule rather than the verb's.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row: a tick is never a writer job. Seed the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <level-note-path> --doc <name>:<type>` — or `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc --root <level-note-path> --doc <name>:<type>` on the catalog root, which belongs to no product — from the type's template chain at stage `empty`. Then open its review at the writer round with `Skill(lazycortex-review:lazy-review.start, "<doc>")` at once, whether or not the level note carries source requests, so the class's main writer works round 1 from the requests when there are any and from the approved level documents above it — the level's `vision.md`, and the content root's and enclosing products' system documents its research aspect reads every time. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

No row of this ladder dispatches an expert job. `dispatch-job` and `cancel-job` are not in this coordinator's verb set, and a row that seems to need one has been misread.

## 4. Where the level's documents come from and what they may not do

A level document is written by its review class's own writers. The coordinator seeds it, opens its review, promotes its stage, and flips the gate it feeds — it never writes into the body of any of them, and the sibling-doc carve-out the asset coordinator has for carrying a question or a decision candidate across documents does not exist at this level.

## 5. The event from below — an approved asset (`asset-approved`)

Only on a product level. Two events reach this note from below: an approved asset (`asset-approved`) and a published release (`release-published`).

**An approved asset.** When an asset's `spec_design_done` or `spec_cancelled` changes value — its start document approved or reopened, the asset cancelled or restored — anywhere under the product that owns releases, its own wake dispatches one `asset-approved` hop onto this note with `payload["asset"]` naming the asset's folder relative to this product. This wake creates nothing and launches nothing: recompute the delta, hang or take down `Start release`, and rewrite `# Status brief` — the asset now waits for a release, or a release is open and the asset waits for its `Rebuild`, which that release's own coordinator hangs. The approval of a design is never the start of a build; the operator's tick is. The one thing this wake may do beyond the rows is cancel an open release whose delta has emptied — every included asset cancelled or carried away — through `spec_cancelled` on the release note, so the next release takes its version.

**A published release.** When the `Publish` tick of a release of this product lands, `release-publish` dispatches one `release-published` hop onto this note after its own commit, best-effort; a failed production deploy dispatches nothing. Recompute the delta, hang or take down `Start release`, and rewrite `# Status brief`: no release is open any more, so assets approved while the release was open now wait for the next one, and the brief no longer names a pending `Publish`. This wake creates nothing and launches nothing either.

One event, one action. The wake edits no asset, flips no asset's gate, and wakes no other coordinator.

## 6. Re-approval reaches nothing below

A re-approved `vision.md` or `design.md` of this level changes no asset, wakes no nested product and drafts nothing: every document below keeps its stage and every gate below stays as it is. Contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

**The coherence check runs here too.** The rule of that chapter holds at this level unchanged: on a `DOC_TRANSITION` whose `review_result` turned approved on a system document — first approval or re-approval, a re-approval already restamped by `promote-approved --transitioned` (§ 1) — run `coherence-dispatch <doc>` once; a ticked `Resolve here` on the level note runs `coherence-resolve <note> <doc>`, takes down that one essence and sends that one document back to its writer, then through its review; a ticked `Not a conflict` runs `coherence-dismiss <note> <doc>`; either tick takes down only that essence and its mirrors. The level note carries the `## Conflicts` group of `# Gates` like any status note, and it holds no level gate shut and no row down.

## 7. Summary and status brief

`# Summary` carries this level's one-line description — what this product, or this whole catalog, IS, in a single plain sentence written between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers. It is the only thing a reader sees without opening the note, so a level whose description is still empty reads as nameless in every listing. You own it: write it on the first wake that finds it empty, and rewrite it later only when the level's subject has genuinely changed — `vision.md` is the document it comes from. A description states identity, never state, so a wake that only moved a gate leaves it exactly as it stands. Never write into the `<!-- spec:stats:* -->` markers beside it — the counts there belong to the stats CLI alone.

Rewrite `# Status brief` on every wake — two to four sentences of plain product-language narration: what state this level is in, why it is stalled if it is, what happens next. State, never a synopsis of a document, never wake mechanics, never engine vocabulary. A level whose `vision.md` is still empty says so: the operator writes the vision and then ticks `Review vision.md`. Keep the HTML-comment explainer line under each section's protected tag in place and write below it.

On a product that owns releases the brief also shows the current release: its version, its rung and its last build, the `staging` address when there is one, what waits for the operator (`Start release` with the delta's members, or the release's `Publish` / `Rebuild`), and what waits outside the release — the approvals that would come in on `Rebuild`, the assets held back from the delta and why.

## 8. Questions and commands

Questions and one-shot commands follow the same shapes every coordinator in this plugin uses: a `[!question]` callout with `- [ ]` options is the only channel to the operator, and it must end with `> — spec.catalog-coordinator` as its own last quoted line — the ANSWER wake keys off that exact attribution. A non-empty `# Coordinator commands` section is unfolded into a numbered mini-plan in that same section, marked `✓` / `→` / `·` while it runs, and cleared when it finishes — one `note-history` line on the level note says what the command did. A command runs even on a halted level.

When a decision does not follow unambiguously from this playbook and the rule layers below, raise a question and stop on this level. Never guess a product into existence.

## 9. Rule layers

From the most general to the closest, on WORKFLOW the closest wins; on PROCEDURE and INVARIANTS (the verb set, the pen surfaces, the trigger list, halt, the reconciliation discipline) this playbook wins:

1. This playbook.
2. The vault-wide operator doc at `spec.coordination_rules`.
3. Product guidelines, role `coordinator` — on a product level only.
4. The catalog root note's `# Coordinator rules`.
5. Every ancestor product note's `# Coordinator rules`, outermost first — a nested product reads each enclosing product's section before its own.
6. The product note's own `# Coordinator rules` — on a product level, the closest layer.

The asset coordinator reads a product note's `# Coordinator rules` as one of its own layers too. That section serves both readers; nothing in it is scoped to one of them by default.

## 10. Routing — the catalog root only

Moved to `lazy-spec.routing-playbook.md`, "Catalog-root lines": the catalog root note, and never a product note, is where a request's routing decision is made, and that playbook carries the whole decision — how the catalog root note is derived on a Routing wake, the `attach <level-doc-path>` and `spawn-product` lines this level adds, and what apply enacts for a new product.
