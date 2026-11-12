---
name: lazy-spec.feature-playbook
description: Type playbook for feature assets — the design-only definition flow, the opt-in vision, use-cases, ui-design and test cases, how and when the tool set is determined, and what closes the two gates a feature carries; implementation belongs to the product's release.
---
# Feature type playbook — definition, then the release

This document is the coordinator's law for any asset whose status folder-note carries `spec_asset_type: feature`. It covers the whole of a feature's own life: its definition documents, the tool set written down for the implementer, and the two gates a feature carries. Everything that turns the approved design into working product — plan, code, data, documentation, tests, deploy — happens in the product's release and belongs to `lazy-spec.release-playbook.md`; this playbook neither hangs those rows nor knows their conditions.

## What this type is

`spec_asset_type: feature` is a design-only asset: its ladder is `spec_design_done`, then `spec_released`, with the `spec_cancelled` overlay. Its status folder-note carries no `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` or `spec_built` key — the keys do not exist on the note, and `flip-gate` refuses to put one there. The result of a feature is a working part of the product, delivered by the release that carries it, not by the feature's own folder.

The primary document is declared by the type record as `start_doc: "design.md:design"` — a feature begins with `design.md`, of doc type `design`. Nothing seeds it at spawn: the scaffold primitive creates only the asset folder and its status folder-note (with its `## Source requests` section), and `design.md`, like every other definition document, is launched later through its own checkbox on that note.

**Place is not a fact about type.** The type record carries `default_path` (the product root, `"."`, as shipped), and that is where a new feature lands at creation when the routing line named no explicit `path=`. But a feature is legal anywhere in the catalog, including nested under another asset's folder: an asset's boundary is a folder-note carrying `spec_role: status`, never the name of a parent directory. The type is read from the status folder-note's frontmatter and from nowhere else; where the folder sits plays no part in resolving it.

## The definition documents

- **`design`** (`design.md`) — always mandatory; the sections are the template's. Written by the designer. This document is never `cancelled` — the stage primitive refuses it, and cancelling an asset is the `spec_cancelled` overlay on the status folder-note, not a cancelled design.
- **`vision`** (`vision.md`) — opt-in, per the type record's `vision: opt-in` contract. The coordinator seeds nothing on the asset's first wake: `Write design` hangs at once, and `Write vision` hangs beside it for a feature large enough to need goals of its own. A small feature's goals live in its `design.md`, against the product's own vision. When a feature's `vision.md` exists, the goals live ONLY there (per `lazy-spec.doc-height-protocol.md`) and the design's review waits for its approval, by the same rule that holds for `use-cases.md` below.
- **`test-plan`** (`test-plan.md`) — opt-in; the feature's test cases, written by the tester once the design is approved. A definition document like the others: it goes through review and approval the way `design.md` does, takes part in no gate of this note, and is read by the release's tester when the release's own test plan is composed. The product's standing test instructions live in the product's root `test-plan.md`, never here.
- **Architecture, plans and reports are the product's and the release's.** A feature carries no `architecture.md`: the product's root `architecture.md` describes the code of the whole product, and the architect revises it against the delta at the start of every release build. `code-plan.md`, `code-report.md` and `test-report.md` are the release's documents. This playbook declares and demands none of them.
- **`decisions`** — the asset's decision registry, kept by `lazy-spec.record-decision`. Created lazily by the first recorded decision; its absence means nothing and blocks nobody.

## Use-cases and ui-design

`use-cases.md` (written by the use-case-writer) and `ui-design.md` (written by the ui-designer) are opt-in, not mandatory: neither is declared above among the definition documents this playbook demands, and neither exists until its launch checkbox is ticked — or the product or the asset declares it mandatory (below). Their absence is a determination like any other opt-in artifact, never a gap: it blocks nothing.

`design.md` launches through its own `Write design` checkbox like the rest, and its hold is a precondition on continuing its review: when `vision.md` or `use-cases.md` exists, the designer is not continued on `design.md`'s review until each existing one reaches `approved` or `cancelled`, and reads them once they are approved. The general rule is one sentence: a document's review proceeds only after every EXISTING upstream sibling in the reading chain (vision → use-cases → design) is `approved`; an absent opt-in document never blocks. The use cases are meant to settle before the behaviour they describe is written down for good, and the screens before the implementer builds to serve them.

**The windows.** A late vision edit follows the same boundary: past `spec_design_done`, a goals revision is a change asset's business. `Write use-cases` closes the moment `spec_design_done` closes — past that point a fresh use case is a change asset's business, not this asset's own definition. `Write ui-design` and `Write test-plan` stay open after the design's approval while their document does not exist, including while the asset is already in an open release's `spec_includes`; test cases and screens may be written and re-approved at any moment. A new or re-approved `test-plan.md` or `ui-design.md` of an included asset hangs `Rebuild` on the release note, and the release's `Rebuild` is how it reaches the next build — no change asset is needed for it.

**Late edits.** An edit landing on `use-cases.md` or `ui-design.md` after `design.md` has already reached `approved` triggers no auto-cascade — the coordinator does not reopen the design on its own. It drops a `[!attention]` callout into `design.md` instead and names the edit in `# Status brief`, so the operator sees the drift and decides whether it is worth folding in.

**Declaring it mandatory.** The `vision` contract comes from the type declaration (`asset_types.<name>.vision`); for `use-cases.md` / `ui-design.md`, a product, the asset's group folder, or this asset may declare either document mandatory in its `# Coordinator rules` section. Once declared, the coordinator runs the same seed-then-start enactment directly, without waiting for a tick — the same rule-driven verb calls every other "automatic" behaviour in this system already uses (`lazy-spec.coordination-playbook.md` Chapter 1, "Automation 'by rule' is still verb calls").

## Determining the tool set

An absent `spec_tools` key on the status folder-note means "tools are not determined" — not "there are no tools". The release implementer reads this key on every included asset: the work of its own tool it does itself, and for every other tool it delegates to that tool's expert (`lazy-spec.release-playbook.md`, "The build"). An asset carried into a release with the key still absent stops the implementer on it, so the determination belongs to this coordinator, on the design's approval.

**When.** Tools are determined on the design's approval, on the same wake that closes `spec_design_done` — the moment the design's statements about the nature of the work are fact.

**From what.** The design's own direct statements about the nature of the work: whether code is edited, whether data files are written, whether documentation is needed, whether an executed check is needed.

**Writing it down.** The coordinator writes the resulting list through `note-set-key` on the asset's status folder-note — through a primitive, like every other frontmatter mutation, never by hand. Every name in the list must be a declared tool (`tool_types.<name>`): a tool in `spec_tools` with no declaration behind it is a finding, not a guess at what was meant.

**Ambiguity is a question, not a bet.** When the design gives no unambiguous answer (the border between `data` and `code`, whether `docs` is needed at all), the coordinator raises a `[!question]` listing the candidates, names in `# Status brief` that the asset is not ready for a release until it is answered, and waits for the operator. Writing an empty key "for now" is forbidden: it hands the implementer an asset while having determined nothing.

## The gates

- **`spec_design_done`** closes once `design.md` has reached stage `approved` (the gate formally accepts `cancelled` too, but the design document itself is never moved into that stage). This gate is derived: the coordinator flips it itself the moment the precondition holds, with no operator signal. Its crossing — on, off, and the `spec_cancelled` flag changing — reaches the level note of the product that owns releases as the `asset-approved` hop, where the product coordinator re-hangs `Start release` and rewrites its brief; the hop launches nothing.
- **`spec_released`** is closed by the release that ships the asset, never by this coordinator: the `Publish` tick on the release note sets it, stamps its moment and adds the version tag `release/<major>-<minor>-<patch>` to the note's tags, so a feature carries the tags of exactly the releases it changed in. Between the design's approval and that publish the asset reads `awaiting-release`, or `in-release` while an open release lists it in `spec_includes`.

**Downward reconciliation.** `spec_design_done` goes stale when `design.md` reappears at a stage other than `approved` — a reopened review, a rejected re-approval; turn it back off with `flip-gate --off` in the same pass. A re-approved `design.md` of an already released feature turns `spec_released` off (`lazy-spec.coordination-playbook.md` Chapter 4), and the feature waits for the next release again with its new design — the released one keeps the tag of the version it shipped in. A `test-plan.md` or `ui-design.md` stays `approved` when its `design.md` is re-approved; contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The checkboxes

Checkboxes live in the status folder-note's `# Gates` section, as rows of `[!gate]` callouts (`lazy-spec.coordination-playbook.md` Chapter 5). The coordinator reconciles the set on every relevant invocation — hangs a row the moment its precondition starts holding, removes an un-ticked one the moment it stops holding — and never ticks one itself: ticking is the operator's gesture. `spec_halted: true` takes every one of them down.

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | asset exists AND `design.md` doesn't exist | seed `design.md:design`, then the seed-then-start flow below |
| `Write vision` | asset exists AND `design.md` is not `approved` AND `vision.md` doesn't exist | seed `vision.md:vision`, then the seed-then-start flow below |
| `Write use-cases` | asset exists AND `design.md` is not `approved` AND `use-cases.md` doesn't exist | seed `use-cases.md:use-cases`, then the seed-then-start flow below |
| `Write ui-design` | `spec_design_done` closed AND `ui-design.md` doesn't exist | seed `ui-design.md:ui-design`, then the seed-then-start flow below |
| `Write test-plan` | `spec_design_done` closed AND `test-plan.md` doesn't exist | seed `test-plan.md:test-plan`, then the seed-then-start flow below |

No `Publish` row hangs on a feature: publication is the release's tick, and it closes the feature's `spec_released` on the way. No implementation row and no plan row hangs here either — those labels are the release playbook's.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row of this table: a tick is never a writer job. The coordinator seeds the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc <name>:<type>` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then opens its review immediately with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, whether or not the folder-note carries any `## Source requests` entry. The class's main writer works round 1 from whatever exists: the request(s) `context_from_frontmatter` resolves from the doc's own attribution, when there are any, and the documents its research aspect obliges it to read every time — the asset's own approved siblings and the system documents of the product chain. With neither a request nor an approved document above it, the writer starts from the asset's folder-note and raises what it cannot ground as in-document `[!question]` callouts. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

**A parked document hangs no `Write` row.** Every row of this table reads "the document doesn't exist", and a document at `spec_stage: deferred` exists — so its row stays down and nothing seeds a replacement beside it, ever. The row that hangs for it instead is the review-launch `Review <doc>` block, whose deferred-document case (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md` Chapter 5) unparks and resubmits the document in one commit when the operator ticks it.

## After approval — the release

An approved feature does nothing further on its own. It stands in the delta of the product that owns releases, and the operator's `Start release` on that product's note, or `Rebuild` on an open release, carries it into a build (`lazy-spec.release-playbook.md`). What the implementer reads from this folder is the approved `design.md`, the `ui-design.md` and `use-cases.md` when they exist, `spec_tools` and `decisions.md`; what the release's tester reads is `test-plan.md`. The order of work inside the release is the implementer's.

When the delta needs an asset that does not exist yet, the architect proposes it with an `[!asset-proposal] create` callout in the product's `architecture.md`, at the start of a build, and the coordinator materializes it through the scaffold verb once the revised `architecture.md` is approved (`lazy-spec.asset-creation-playbook.md`). The new asset goes through its own ladder and ships in a later release; the feature that prompted it is released by the release that carries the feature itself.

## Attach before a release

While a feature is in no release's `spec_includes`, a request can be attached to it without opening a change asset. The attach drops the documents that describe an already-abandoned way of doing the work and nothing else: no gate is flipped, and the design re-enters review through a fresh writer round (`lazy-spec.attach-drop-playbook.md`).

The drop list for an `attach` line's `drop=` field is `test-plan.md`, when it exists — the test cases written against the design the request is about to revise. `design.md` is never in the drop list: attach means precisely that the request is being routed to that design. A feature with no test cases yet has nothing to drop, and `drop=` is then either empty or not written at all, which means "drop nothing".

Whether a request attaches to an asset a release already carries in `spec_includes`, or to a released one, or becomes a separate change, is the operator's tick at routing; an attach there takes this same path, and the release's own `Rebuild` is how the re-approved design reaches the build.
