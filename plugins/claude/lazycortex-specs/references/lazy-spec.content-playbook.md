---
name: lazy-spec.content-playbook
description: Type playbook for content assets — a design document describing one data-defined content entity of a product (an opt-in vision may precede it), tools preset to data at creation, no architecture and no planning step, the data written inside the product release that ships the asset.
---
# Content type playbook — one content entity, zero planning

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: content`. It covers the whole flow of the asset, which is design-only: what defines the asset, what closes `spec_design_done`, which checkboxes hang on the note, and how the entity's data reaches a product release. The data entry and its verification happen inside the release build and are declared by `lazy-spec.release-playbook.md`.

## What this type is

`spec_asset_type: content` — the asset describes **one** data-defined content entity of a product: a product catalog entry, a pricing rule table, a document template, a configuration preset. Not a set, not a subsystem, not a mechanism — a single unit of content that is then entered into the project's data files against its schemas.

- **Start document** — `design.md`, `spec_doc_type: content-design`, and it is the document of definition; its sections are the template's. It defines the entity by decisions, not by values: what the entity is, why it is shaped this way, and, decision by decision, what its data must express, stated in words, each decision naming the schema fields it settles. The values themselves live only in the data files, and the design never copies a value, a number, or a generated text out of them — a design that mirrors its data is a second source of truth that the first edit of the data splits off. An opt-in `vision.md` may precede it through `Write vision`, and nothing else is authored on this type: a unit of content has no separate "how it is built" layer — the build is dictated by the project's schemas, not by the asset.
- **The schema is declared once, on the type.** The product names how to reach the schema its records are written against — a document, a schema file, a utility's output — in `asset_types.content.guidelines` (`lazy-spec.config-protocol.md`), and every expert dispatched on a content asset carries those paths whatever its role: the designer writing `design.md` reads the schema to know which fields each decision settles, the data writer reads the same files to validate the design and later to write the data. A product that declares none leaves the designer guessing at the schema's fields and the data writer with nothing to write against — the `data` job stops and says so rather than inferring the format from existing data.
- **`cancelled` is refused on `design.md`** — the asset is abandoned as a whole through `spec_cancelled`.
- **Location is not a fact of the type.** The declaration's `default_path` places new content assets at the product root by default, but the asset is legal anywhere: inside the folder of a feature that introduces a family of entities, or next to its siblings. Type resolution reads `spec_asset_type`, never a path; the asset boundary stays the folder whose folder-note carries `spec_role: status`.
- **Tools are known from creation.** The type declaration names `default_tools: ["data"]`, and the scaffold writes that list into `spec_tools` when the asset is created. The tool determination that happens after design approval on other types has already happened here: a unit of content is made by entering data. The release implementer reads `spec_tools` from the note and delegates the entry to the data writer — a child agent with the `data` tool's expert, handed the approved design and the tool's guidelines. The `test` tool is added by the same rules as any other — a coordinator decision, when the entity warrants an executed check, never automatically.
- **Buying an extra tool is possible.** When the approved design plainly demands something more — say a user-facing description of the entity, i.e. the `docs` tool — the coordinator does not extend the list silently: it raises a `[!question]` listing the candidates with a case for each, and only extends `spec_tools` through `note-set-key` once the operator answers. A tool named in `spec_tools` but not declared in the product's `tool_types` is a finding for `# Status brief`, not a gap to fill in.

## The gates

| Gate | What closes it on a content asset |
|---|---|
| `spec_design_done` | `design.md.spec_stage == approved` — the entity's design is accepted by review. |
| `spec_released` | the release that carries the asset in its `spec_includes` is published: the operator's `Publish` tick on the release note sets `spec_released: true` and `spec_released_at`, and adds the version tag `release/<major>-<minor>-<patch>` to the note. A re-approved `design.md` turns it off again (`lazy-spec.coordination-playbook.md` Chapter 4), and the asset waits for the next release (`spec_state: awaiting-release`; `in-release` once an open release's `spec_includes` carries it). |

The gates are a strict ladder — `spec_released` requires `spec_design_done`. The `lazy-spec.flip-gate` primitive flips whichever gate it is called on, unconditionally (it refuses every flip on a cancelled asset but the un-cancel `spec_cancelled --off`, and it refuses to turn `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` or `spec_built` on, because those keys exist on a release note only), so the ORDER is held by the coordinator's reasoning, not by a script.

The data is written inside the product's release build by the data writer the release implementer delegates to, and `spec_released` closes when that release is published; nothing on the asset note records the build itself.

**Downward reconciliation.** A gate already true goes stale when its governing document reappears un-accepted. The coordinator flips the gate back with `flip-gate --off` and re-runs its upward checks in the same pass. A re-approved document never lowers the stage of a document that depends on it (`lazy-spec.coordination-playbook.md` Chapter 4); contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The checkboxes

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | asset exists AND `design.md` doesn't exist | seed `design.md:content-design`, then the seed-then-start flow below |
| `Write vision` | asset exists AND `design.md` is not `approved` AND `vision.md` doesn't exist | seed `vision.md:vision`, then the seed-then-start flow below |

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row of this table: a tick is never a writer job. The coordinator seeds the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc <name>:<type>` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then opens its review immediately with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, whether or not the folder-note carries any `## Source requests` entry. The class's main writer works round 1 from whatever exists: the request(s) `context_from_frontmatter` resolves from the doc's own attribution, when there are any, and the documents its research aspect obliges it to read every time — the asset's own approved siblings and the system documents of the product chain. With neither a request nor an approved document above it, the writer starts from the asset's folder-note and raises what it cannot ground as in-document `[!question]` callouts. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

Neither `Write architecture` nor a plan checkbox ever hangs on this type: there is no architecture step for a unit of content by definition of the type, and plans belong to the release, not to the asset. Block shape in `# Gates` is the common one:

```
> [!gate] Write design
> - [ ] Write design
> tick to dispatch: designer writes design.md
```

No `Start data entry` or `Start testing` row hangs anywhere: the data is written and tested inside a release build. The rows of the release note (`Write code-plan`, `Write test-plan`, `Rebuild`, `Publish`) are declared by `lazy-spec.release-playbook.md` — they are not here.

## Data conformance to the design

The approved design is the source of truth for what the data must express; the data is the only place its values live. The data conforms when it expresses every decision the design states — the concrete values are the data writer's choice. A divergence between them is always resolved in one direction: **by work, never by rewriting the design after the fact**.

- The data fails a decision of the approved design (a value that does not express it, a wrong link, a missing field) — that is a defect in the work: the release's `code-report.md` goes back for rework through the release's acceptance cycle, same job, same expert (a release has no separate `data-report.md`).
- The data writer disagrees with a decision of the design itself (no value expressing it keeps the balance, the link is impossible under the schema) — that is an objection to the design, and it travels back into the design through review: the expert records the disagreement in the release's `code-report.md`, the coordinator returns `design.md` to review rather than settling the argument itself. Data written "the way it should be" against an approved design is the same finding even when the writer is substantively right.
- An approved design that turns out to be unimplementable is not grounds for a `[!question]` asking whether a deviation is allowed: the question goes into the design's review, where the document has its history and its reviewers.

This is a standing judgment, not a one-off: every "data versus design" conflict is walked through this fork before the coordinator writes a line into `# Status brief`.

## Attach before a release

There is nothing to drop. When an incoming request attaches to a content asset no release has picked up yet, the `attach` line carries no `drop=` field: the asset has no architecture document and no plans — only `design.md`, which is exactly what the request revises.

The attach reduces to stamping the request's attribution onto `design.md` and returning the document to review through a fresh writer round; no gate is flipped (`lazy-spec.attach-drop-playbook.md`). Whether a request attaches to an asset a release already carries in `spec_includes`, or to a released one, or becomes a separate change, is the operator's tick at routing; an attach there takes this same path, and the release's own `Rebuild` is how the re-approved design reaches the build.
