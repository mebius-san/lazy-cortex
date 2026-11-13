---
name: lazy-spec.change-playbook
description: Type playbook for change assets — the feature-shaped design-only definition flow plus the two-phase cascade that folds the delta into every declared target's design and test cases; the change itself ships in the product's release once the cascade has converged.
---
# Change playbook — the `change` asset type

This document is the coordinator's law on any asset whose status folder-note carries `spec_asset_type: change`. It covers the definition flow — the documents, tool determination, the two gates and their launch checkboxes — plus the cascade, which is what makes a change different from every other type. Implementation and verification belong to the product's release (`lazy-spec.release-playbook.md`): a change enters the release delta once its design is approved and its cascade has converged.

## What this type is

`spec_asset_type: change` is a design-only asset like a feature: the ladder is `spec_design_done`, then `spec_released`, with the `spec_cancelled` overlay, and the status folder-note carries no `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` or `spec_built` key. What a change adds is the cascade and its own terminal cascade state, `spec_cascade_done`, which the release delta reads: a change whose cascade has not converged is held back from the delta as `cascade-pending`, because the implementer builds from the targets' folded designs, never from the change's own text.

The primary document is `design.md`, of document type `design`: a change describes the delta it introduces the same way a feature describes what it builds. Nothing seeds it at spawn — spawn lands only the asset folder and its status folder-note (with its `## Source requests` section), and `design.md`, like every other definition document, launches later through its own checkbox on that note.

**Place is not the type.** `default_path` files new changes under its own folder, but a change is legal anywhere in the product's catalog, including nested under another asset. The type is read from the key, never inferred from the folder.

The definition flow of a change is the same as a feature's, PLUS the cascade into its targets. Targets are declared as the `spec_targets` list on the status folder-note; the tokens are paths relative to the product's `spec_path`, and a nested asset is addressed by its full path.

## Definition documents

- `design` (`design.md`) — mandatory. Never `cancelled`: the stage primitive refuses it exactly as it refuses a cancelled `bug.md`.
- `vision` (`vision.md`), `use-cases` (`use-cases.md`), `ui-design` (`ui-design.md`) — opt-in, below.
- `test-plan` (`test-plan.md`) — opt-in; the change's OWN test cases, covering the change's own modifications and never duplicating a target's. A definition document: reviewed and approved like `design.md`, in no gate of this note, read by the release's tester.
- A change carries no `architecture.md` and no plans or reports: the product's root `architecture.md` is brought up to date with the approved designs on the product note, by the `Revise architecture` row, never inside a release build, and `code-plan.md`, `code-report.md`, `test-report.md` are the release's.
- `decisions.md` — the registry of recorded decisions, written only by the `lazy-spec.record-decision` primitive. It carries no stage and takes no part in any gate.

## Use-cases and ui-design

The change's own `vision.md` (designer, per the type record's `vision: opt-in` contract), `use-cases.md` (use-case-writer), and `ui-design.md` (ui-designer) are opt-in: neither is on the mandatory list above, and neither exists until its launch checkbox is ticked — or the product or the change declares it mandatory (below). These describe the CHANGE's own delta, not a cascade target's; folding that delta into a target's own use cases or screens, where the target carries them, is the target's own definition business once the cascade reaches it, not something this chapter tracks.

The change's `design.md` launches through its own `Write design` checkbox like the rest, so its hold is a precondition on continuing its review: when `vision.md` or `use-cases.md` exists, the designer is not continued on the change's `design.md` until each existing one reaches `approved` or `cancelled`, and reads them once approved. The general rule: a document's review proceeds only after every EXISTING upstream sibling in the reading chain (vision → use-cases → design) is `approved`; an absent opt-in document never blocks.

**The windows.** `Write vision` and `Write use-cases` close the moment `spec_design_done` closes. Past that window, a further use-case revision on this delta is a new change, not a reopening of this one. `Write ui-design` and `Write test-plan` stay open while their document does not exist, including while the change is already in an open release's `spec_includes`; `Write test-plan` still waits for `spec_cascade_done` (below). A new or re-approved `test-plan.md` or `ui-design.md` of an included change hangs `Rebuild` on the release note, which pulls it into the next build.

**Late edits.** An edit to `vision.md`, `use-cases.md`, or `ui-design.md` after `design.md` has already reached `approved` gets no auto-cascade — the coordinator drops a `[!attention]` callout into `design.md` and names the edit in `# Status brief`, rather than reopening anything on its own.

**Declaring it mandatory.** The `vision` contract comes from the type declaration (`asset_types.<name>.vision`); for `use-cases.md` / `ui-design.md`, a product, the change's group folder, or this change may declare either document mandatory in its `# Coordinator rules` section, in which case the coordinator runs the same seed-then-start enactment directly, without a tick — the same rule-driven verb calls behind every other "runs automatically" clause (`lazy-spec.coordination-playbook.md` Chapter 1, "Automation 'by rule' is still verb calls").

## Tool determination

**When.** Tools are determined on design approval, on the same wake that closes `spec_design_done`. Until then the note carries no `spec_tools`, and that state means "not determined" — the release implementer stops on an included asset whose tool set is still open, so the determination is this coordinator's to make before the asset reaches a release.

**From what.** The direct statements of the design document about what is actually being made — code, data, documentation, tests.

**Written how.** The coordinator writes the list through `note-set-key`. An unobvious choice is never guessed — the coordinator raises a `[!question]` listing the candidates, names in `# Status brief` that the change is not ready for a release, and waits for the operator's tick.

A tool that lands in `spec_tools` with no declaration in `tool_types` is a finding, not a guess: the coordinator raises the question rather than inventing behaviour for a playbook that does not exist.

## The gates

- **`spec_design_done`** — closes once `design.md` reaches `spec_stage ∈ {approved, cancelled}`. A derived gate: its precondition is fully computable from sibling doc state, so the coordinator flips it itself the same cycle the precondition starts holding. Its crossing reaches the release owner's level note as the `asset-approved` hop, which only re-hangs rows and rewrites the product's brief.
- **`spec_released`** — closed by the release that ships the change: the `Publish` tick on the release note sets it, stamps its moment and adds the version tag to the note. Between approval and that publish the change reads `awaiting-release` (or `cascade-pending` in the delta listing while the cascade runs), and `in-release` while an open release lists it.

**Downward reconciliation.** `spec_design_done` goes back to `false` (`flip-gate --off`, auto) when `design.md` reappears at a stage other than `approved`; the downward flip commits atomically and the coordinator immediately re-runs its upward checks against the fresh state. A re-approved `design.md` of an already released change turns `spec_released` off (`lazy-spec.coordination-playbook.md` Chapter 4), and the change — and its cascade — run again. A `test-plan.md` or `ui-design.md` stays `approved` when its `design.md` is re-approved; contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The launch checkboxes

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | asset exists AND `design.md` doesn't exist | seed `design.md:design`, then the seed-then-start flow below |
| `Write vision` | asset exists AND `design.md` is not `approved` AND `vision.md` doesn't exist | seed `vision.md:vision`, then the seed-then-start flow below |
| `Write use-cases` | asset exists AND `design.md` is not `approved` AND `use-cases.md` doesn't exist | seed `use-cases.md:use-cases`, then the seed-then-start flow below |
| `Write ui-design` | `spec_design_done` true AND `ui-design.md` doesn't exist | seed `ui-design.md:ui-design`, then the seed-then-start flow below |
| `Write test-plan` | `spec_cascade_done` true AND `test-plan.md` doesn't exist | seed `test-plan.md:test-plan`, then the seed-then-start flow below |

No `Publish`, no `Start …`, no `Write code-plan` and no `Write architecture` row hangs on a change: those labels are the release playbook's.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row of this table: a tick is never a writer job. The coordinator seeds the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc <name>:<type>` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then opens its review immediately with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, whether or not the folder-note carries any `## Source requests` entry. The class's main writer works round 1 from whatever exists: the request(s) `context_from_frontmatter` resolves from the doc's own attribution, when there are any, and the documents its research aspect obliges it to read every time — the asset's own approved siblings and the system documents of the product chain. With neither a request nor an approved document above it, the writer starts from the asset's folder-note and raises what it cannot ground as in-document `[!question]` callouts. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

**A parked document hangs no `Write` row.** Every row of this table reads "the document doesn't exist", and a document at `spec_stage: deferred` exists — so its row stays down and nothing seeds a replacement beside it, ever. The row that hangs for it instead is the review-launch `Review <doc>` block, whose deferred-document case (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md` Chapter 5) unparks and resubmits the document in one commit when the operator ticks it.

**The one difference from a feature on this table, and it is hard:** the change's OWN `Write test-plan` does NOT hang until the phase-II cascade has converged. Every target's test cases must reflect the delta before the change writes its own — otherwise the change's own cases are written against a contract that is about to change.

Ticking is the operator's gesture and only theirs; the coordinator never ticks a checkbox under any circumstance. Every ticked `Write` row is enacted through seed-then-start above, never a job bundle. `dispatch-job` mechanics belong to the cascade folds below and to the release's `Build` and `Test` jobs, where dispatch stays deduplicated by key — the status note's path relative to `spec_path` plus the label.

`spec_halted: true` overrides this table unconditionally: no checkbox hangs, and any un-ticked one comes down. A ticked one (`- [x]`) stays — the operator's tick has already happened.

## The cascade — two phases, strictly ordered

This chapter is the coordinator's prose for the parts that are specific to a change: folding its delta into the assets it targets. The change's own implementation and the regression that follows it are the release's: the implementer builds the targets' folded designs, and the release's tests cover the whole product, so no per-target regression phase exists any more.

**How a fold lands.** Every phase below dispatches a writer to fold the change's delta into a document belonging to ANOTHER asset, and no such writer ever edits that document in the working tree. The fold job carries the target document's repo-relative path as `target_doc` in its dispatch payload (`lazy-spec.lifecycle-protocol.md` Part 3 § Dispatch) and returns the whole folded document through its own `result/`, first entry, attachments after it. On the job's `job-done` wake the coordinator lands it itself — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> land-result <job_dir> <asset_dir> --target <target asset>/<doc>` — because the destination lies outside the dispatching asset's folder and `lazy-spec.gate-tick`'s own landing only places a document inside it. The verb commits the document and its attachments under its own bot identity; only then does the coordinator open the target document's review.

**(I) Design convergence + counter-check.** Once the change's OWN `design.md` is approved, the coordinator dispatches a designer job per declared target in `spec_targets` (one at a time, not in parallel) to fold the change's delta into that target's `design.md`; the folded document lands by the route above, and the target's `design.md` re-enters review. Once that review closes approved, the coordinator dispatches a counter-check job: the change's OWN writer, with the now-updated target delta in context, verifies the change's own spec still matches what actually landed and revises if not. This repeats to a fixed point — a change touching several targets runs this convergence loop per target, and any target's re-approval after a cascade fold triggers the same counter-check pattern generically: a re-approved doc downstream always earns its paired writer a verification pass. A target's re-approved `design.md` turns that target's `spec_released` off when it was released (`lazy-spec.coordination-playbook.md` Chapter 4), so the target stands in the delta beside the change. Each target folded to completion joins the `spec_cascade_targets_done` list on the change's status folder-note.

**(II) Test cases, only after convergence.** Once every declared target's design fold has converged, the tester folds the same delta into each target's `test-plan.md` where the target carries one — the target's test cases must reflect what the target now does — returned and landed by the same route as a design fold. Once every `spec_targets` entry is accounted for in `spec_cascade_targets_done`, `spec_cascade_done` flips to `true` — the change's terminal cascade state, which lets it into the release delta — and only then does `Write test-plan` hang for the CHANGE's own test cases.

A target's `code-plan.md` and reports no longer exist to be dropped: the release's plans are written against the folded designs at the next build.

## Conflicting changes on one feature

The "one active feature — one active change" lock does not exist: a new change may cancel or modify an older one in flight. When a second change targets a feature already being cascaded into, the coordinator decides — wait for the in-flight one to finish, cancel the older one (via `cancel-job` plus the ordinary asset-cancellation path), or fold the new one in as a modification of the same fold. Whenever the right call is not obvious from the rules layers in scope, the coordinator surfaces a `[!question]` to the operator rather than guessing.

## Merge drift

A cascade fold that cannot apply cleanly, or a target that vanishes mid-flight, is handled by the ordinary halt mechanism: the coordinator calls `flip-gate --halt` with `HaltReason.MERGE_CONFLICT` or `HaltReason.PLAN_DROP_PARTIAL`, exactly as any other halting caller would. It does not invent new halt phrasing.

Halt silences the automation — checkboxes, cascade dispatch, rule-driven dispatch — but never the gate booleans themselves, and never `# Coordinator commands`: an operator gesture runs on a halted asset too, and that is precisely how the operator directs recovery.

## Attach before a release

When a change is in no release's `spec_includes` and routing decides to attach a new request onto it, the attach line carries a `drop=` list: the change's own `test-plan.md`, when it exists. `design.md` is never dropped, and a change has no plans of its own to drop.

The attach drop itself is an atomic primitive (`lazy-spec.attach-drop-playbook.md`): it deletes only the named documents, flips no gate, and refuses on its own when the asset is cancelled or halted, no matter who calls it. The coordinator composes the `drop=` list; the primitive still enforces its own safety. Whether a request attaches to an asset a release already carries in `spec_includes`, or to a released one, or becomes a separate change, is the operator's tick at routing; an attach there takes this same path, and the release's own `Rebuild` is how the re-approved design reaches the build.
