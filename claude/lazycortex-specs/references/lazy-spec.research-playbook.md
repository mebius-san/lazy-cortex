---
name: lazy-spec.research-playbook
description: Type playbook for research assets — a research design (the question) written by the designer and validated by the researcher, then the `research` tool's report (the answer) accepted by review; the approved report is the deliverable and a citable, immutable document.
---
# Research type playbook — an asset whose deliverable is the answer itself

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: research`. The type has the same two halves as any other: a definition half that ends at an approved research design, and a work half with exactly one tool, `research`, whose accepted report is the asset's result.

## What this type is

`spec_asset_type: research` — the asset poses a question and ends at the answer to it. The deliverable is **the answer itself**: the routes walked, the findings with their sources, the options compared, the conclusion and its justification, recorded so that later work can cite them.

- **Start document** — `design.md`, `spec_doc_type: research-design`, role `design`. It is the research design: the one question (with its hypothesis as the second sentence, when the operator already expects an answer), the goals and the decision that depends on the answer, the scope, what is already known, and the approach the researcher is expected to take. Written by the designer from the originating request under the `research-design` review class; the researcher validates it in the `Researcher review` section — is the question one, are the boundaries set, is the known part sourced. The operator approves.
- **Result document** — `research.md`, `spec_doc_type: research-report`, role `research`. Written by the researcher as the `research` tool's job from the approved design, under the `research-report` review class with no validators. Its sections are the method, the findings, the options, the conclusion with an explicit verdict on the hypothesis, and the sources. It is the only authored document where external URLs are allowed (in `## Sources` and beside the finding that cites them), and it is content, never a journal: it enters the wiki once approved and is never listed among the wiki's excluded journals.
- **`vision.md` is opt-in.** The type declares `vision: opt-in`; a vision precedes the research design only when the operator ticks `Write vision`, and its goals then live there rather than in the design's Overview.
- **`cancelled` is refused on `design.md`** — research that stopped being needed is abandoned as a whole through `spec_cancelled`.
- **Location is not a fact of the type.** The declaration's `default_path` drops new research into its own subfolder, but the asset is legal anywhere, nesting inside the folder of the feature whose question it settles included. Type resolution reads `spec_asset_type`, never a path; the asset boundary stays the folder whose folder-note carries `spec_role: status`.
- **Tools are known from creation.** The type declaration names `default_tools: ["research"]`, and the scaffold writes that list into `spec_tools` when the asset is created. Buying a second tool — say `docs`, to publish the conclusions outward — goes through a `[!question]` listing the candidates, never silently; `spec_tools` is extended through `note-set-key` once the operator answers.
- **Legacy layout.** An asset whose folder carries `design.md` typed `design` and no `spec_tools` predates this form. It is migrated by hand — retype the document to `research-design` and set `spec_tools: ["research"]` on the status note; no shipped vault carries such an asset.

## Gates

| Gate | What closes it on a research asset |
|---|---|
| `spec_design_done` | `design.md.spec_stage == approved` — the research design is accepted by review. |
| `spec_plan_done` | `spec_design_done` already `true` — the `research` tool declares no plan; the gate closes by absence on the same wake. |
| `spec_develop_done` | the `research` tool's report `research.md` is accepted by review (`approved`, approved-with-concerns counts) — see the tool playbook. |
| `spec_tests_passing` | ready by absence: the `test` tool is not in the set. |
| `spec_released` | an external "the conclusions were handed on" signal, reaching the coordinator as an operator word — a ticked `[!question]` option or a `# Coordinator commands` entry. Never a checkbox completing: `Publish` hangs only after this gate has already closed. |

The gates remain a strict ladder — each requires the one before it — and the `lazy-spec.flip-gate` primitive flips whichever it is called on, unconditionally (its only refusal is a cancelled asset). The order is held by the coordinator's reasoning.

`spec_released` is the one gate the coordinator does not derive from document state: it waits on an external signal that the conclusions reached whoever needed them. An asset whose report is approved but which nobody has picked up stands honestly at `S4`.

**Downward reconciliation.** A gate already true goes stale when its governing document reappears un-accepted, and a dependent document whose source was re-approved after it goes stale — back to `draft` where it carries a stage — and its gate turned off — the source-staleness rule of `lazy-spec.coordination-playbook.md`, whose table names the source of every document of this type. The coordinator flips the gate back with `flip-gate --off` and re-runs its upward checks in the same pass.

## The launch checkboxes of the definition half

| Checkbox | Appears when | On tick |
|---|---|---|
| `Write design` | asset exists AND `design.md` doesn't exist | seed `design.md:research-design`, then the seed-then-start flow below |
| `Write vision` | asset exists AND `design.md` is not `approved` AND `vision.md` doesn't exist | seed `vision.md:vision`, then the seed-then-start flow below |
| `Publish` | `spec_released` true AND `spec_draft` still true | no job — the tick clears `spec_draft` through `note-set-key` and the coordinator removes the checkbox |

**Seed-then-start.** The single mechanic for every `Write` row of this table: a tick is never a writer job. The coordinator seeds the one document with `lazycortex-specs seed-doc <product> <folder-note-path> --doc <name>:<type>` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then branches on the folder-note's `## Source requests`. With at least one entry there, review opens immediately with `Skill(lazycortex-review:lazy-review.start, "<doc>")`, and the class's main writer works round 1 reading the request(s) from its job context. With none, the coordinator waits for the operator's own commit into the skeleton and opens review on that wake.

No architecture checkbox and no plan checkbox ever hang on this type: research introduces no shape of code, and the `research` tool declares no plan. The implementation checkbox `Start implementation (research)` is declared by the tool playbook, not here. Block shape in `# Gates` is the common one:

```
> [!gate] Publish
> - [ ] Publish
> tick to clear spec_draft
```

`Publish` is the one label that never produces a job. There is no automatic clearing — an approved report does not mean the operator is ready to hand it on.

## Work that grows out of research

Research almost always spawns work — but never inside itself. New work is opened as a **new asset**: an expert or the coordinator raises an `[!asset-proposal]` citing the approved report, the coordinator materialises an asset of the appropriate type and links it to the research through `spec_depends_on`.

Mutating the research asset instead is forbidden: appending tools beyond the one bought through a `[!question]`, hanging an implementation checkbox of another tool on it, rewriting the approved report into a specification of a future feature — each destroys the thing the asset existed for. An approved research report is immutable as a citation: the very assets that grew out of it will point at it, and it must read the way it read at the moment of approval.

Research whose conclusion turns out to be wrong is not rewritten after the fact — a new one is opened, citing the previous through `spec_depends_on`.
