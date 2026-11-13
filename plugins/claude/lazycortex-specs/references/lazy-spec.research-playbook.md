---
name: lazy-spec.research-playbook
description: Type playbook for research assets — a research design (the question) written by the designer and validated by the researcher, then the researcher's report (the answer) written through the `Start research` row and accepted by review; the approved report is the deliverable, a citable, immutable document, and its approval closes `spec_released` itself — no release, no version tag.
---
# Research type playbook — an asset whose deliverable is the answer itself

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: research`. The type is the one with no implementation at all: a definition half that ends at an approved research design, and a report, `research.md`, written by the researcher inside the review loop, whose approval is both the asset's result and its release.

## What this type is

`spec_asset_type: research` — the asset poses a question and ends at the answer to it. The deliverable is **the answer itself**, recorded so that later work can cite it.

- **Start document** — `design.md`, `spec_doc_type: research-design`, role `design`. It is the research design: what is asked and how it is to be answered; its sections are the template's (`spec.research/design.md`). Written by the designer from the originating request under the `research-design` review class; the researcher validates it in the `Researcher review` section — can each question be answered as posed. The operator approves.
- **Result document** — `research.md`, `spec_doc_type: research-report`, role `research`. Written by the researcher from the approved design, inside the review loop that the `Start research` row opens, under the `research-report` review class with no validators. Its sections are the template's (`spec.docs/research.md`). It is the only authored document where external URLs are allowed (per `lazy-spec.file-roles-protocol.md`), and it is content, never a journal: it enters the wiki once approved and is never listed among the wiki's excluded journals.
- **No `vision.md`.** The type declares `vision: none`, like `bug`: the questions and the decision that depends on the answers live in the research design itself, and a vision would restate them.
- **`cancelled` is refused on `design.md`** — research that stopped being needed is abandoned as a whole through `spec_cancelled`.
- **Location is not a fact of the type.** The declaration's `default_path` places new research at the product root by default, but the asset is legal anywhere, nesting inside the folder of the feature whose question it settles included. Type resolution reads `spec_asset_type`, never a path; the asset boundary stays the folder whose folder-note carries `spec_role: status`.
- **Tools are known from creation.** The type declaration names `default_tools: ["research"]`, and the scaffold writes that list into `spec_tools` when the asset is created. The `research` tool is the researcher who writes the report through the `Start research` writer-launch row below — not an implementation job, and never a release: a research asset is excluded from every release delta. Buying a second tool — say `docs`, to publish the conclusions outward — goes through a `[!question]` listing the candidates, never silently; `spec_tools` is extended through `note-set-key` once the operator answers.
- **Legacy layout.** An asset whose folder carries `design.md` typed `design` and no `spec_tools` predates this form. It is migrated by hand — retype the document to `research-design` and set `spec_tools: ["research"]` on the status note; no shipped vault carries such an asset.

## Gates

| Gate | What closes it on a research asset |
|---|---|
| `spec_design_done` | `design.md.spec_stage == approved` — the research design is accepted by review. |
| `spec_released` | `research.md.spec_stage == approved` — the report is accepted by review (approved-with-concerns counts). No release ships a research asset, no version tag is added, and the asset is excluded from every release delta. |

The gates remain a strict ladder — `spec_released` requires `spec_design_done` — and the `lazy-spec.flip-gate` primitive flips whichever it is called on, unconditionally (it refuses every flip on a cancelled asset but the un-cancel `spec_cancelled --off`, and it refuses to turn `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` or `spec_built` on, because those keys exist on a release note only). The order is held by the coordinator's reasoning.

`spec_released` is the one terminal gate the asset's own coordinator derives from document state: on every other type the publishing release writes it; here the approved report is the deliverable, and the asset is done the moment review accepts it. A re-approved `design.md` leaves the gate and the approved `research.md` as they are: a changed question is answered by a new research asset.

**Downward reconciliation.** A gate already true goes stale when its governing document reappears un-accepted. The coordinator flips the gate back with `flip-gate --off` and re-runs its upward checks in the same pass. A re-approved document never lowers the stage of a document that depends on it (`lazy-spec.coordination-playbook.md` Chapter 4); contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The checkboxes

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | asset exists AND `design.md` doesn't exist | seed `design.md:research-design`, then the seed-then-start flow below |
| `Start research` | `spec_design_done` true AND `research.md` doesn't exist | seed `research.md:research-report`, then the seed-then-start flow below |

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Seed-then-start.** The single mechanic for every `Write` row of this table: a tick is never a writer job. The coordinator seeds the one document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc <name>:<type>` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then opens its review immediately with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, whether or not the folder-note carries any `## Source requests` entry. The class's main writer works round 1 from whatever exists: the request(s) `context_from_frontmatter` resolves from the doc's own attribution, when there are any, and the documents its research aspect obliges it to read every time — the asset's own approved siblings and the system documents of the product chain. With neither a request nor an approved document above it, the writer starts from the asset's folder-note and raises what it cannot ground as in-document `[!question]` callouts. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

No architecture checkbox and no plan checkbox ever hang on this type: research introduces no shape of code, and nothing is planned or built. `Start research` is a writer-launch row exactly like `Write design`, declared here and nowhere else: its tick seeds the report and opens its review, and the researcher writes `research.md` inside the loop with the approved design as its source. No `Publish` row hangs either — the approval of the report closes `spec_released` on the same wake. Callout shape in `# Gates` is the common one (`lazy-spec.coordination-playbook.md` Chapter 5); the footer is the fixed `Start` line, which `review-rows` writes in the note's language and nobody composes by hand (shown here as an English note carries it):

```
> [!gate] Start
> - [ ] Start research
>
> tick to start the work the row names
```

## Work that grows out of research

Research almost always spawns work — but never inside itself. New work is opened as a **new asset**: an expert or the coordinator raises an `[!asset-proposal]` citing the approved report, the coordinator materialises an asset of the appropriate type, and the new asset's documents cite the report by a wikilink.

Mutating the research asset instead is forbidden: appending tools beyond the one bought through a `[!question]`, hanging an implementation checkbox of another tool on it, rewriting the approved report into a specification of a future feature — each destroys the thing the asset existed for. An approved research report is immutable as a citation: the very assets that grew out of it will point at it, and it must read the way it read at the moment of approval.

Research whose conclusion turns out to be wrong is not rewritten after the fact — a new one is opened, citing the previous report by a wikilink.
