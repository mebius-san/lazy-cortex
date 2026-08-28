---
name: lazy-spec.bug-playbook
description: Type playbook for bug assets — the bug-typed primary document written by a tester, no architecture step ever, tool determination from the reproduction, and what the first two gates mean for a defect.
---
# Bug type playbook — from reproduction to launched work

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: bug`. It covers the first half of the flow: what defines the asset, what closes `spec_design_done` and `spec_plan_done`, and which checkboxes hang before work starts. Implementation and verification are declared by the playbooks of the tools listed in `spec_tools` — their labels are not duplicated here.

## What this type is

`spec_asset_type: bug` — the asset describes a defect: observed behaviour diverges from behaviour that is already approved or plainly implied.

- **Primary document** — `bug.md`, `spec_doc_type: bug` (the type declaration names it as `start_doc: "bug.md:bug"`). Nothing seeds it at spawn — spawn lands only the asset folder and its status folder-note (with its `## Source requests` section), and `bug.md` launches later through the `Write bug` checkbox on that note. A tester writes it — the role, not whoever sits at the keyboard: reproduction, expected against actual, environment, the narrow spot. A bug never carries a design document: `design` is a document about what is being built, and a bug speaks about what is already broken.
- **Location is not a fact of the type.** The declaration's `default_path` drops new bugs into the bug subfolder, but a bug is legal anywhere in the catalog: alongside the product's other bugs, or nested inside the folder of the feature it concerns. The asset boundary stays the folder whose folder-note carries `spec_role: status`; a nested bug is its own asset with its own status note, not a part of its parent. Type resolution reads `spec_asset_type`, never a path.
- **Full mode.** A bug walks all five gates: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`.
- **Documents.** Exactly one is mandatory — `bug.md`; `cancelled` is refused on it (the asset is abandoned as a whole through `spec_cancelled`, never through its primary document). Plans and reports belong to tools and are declared by `tool_types`; the `decisions` registry is opt-in and written only by the `lazy-spec.decide` primitive.

## There is no architecture step

The `Write architecture` checkbox never hangs on a bug — not on a code-bearing judgment, not on an expert's request, not on a large defect. The reason is procedural: an architecture document describes the shape of code an asset introduces, and a bug introduces nothing — it returns the system to a shape already approved. When the fix does require changing the approved shape, it is not a bug: the coordinator raises an `[!asset-proposal]` for a `change` (or `feature`) asset and links it to the bug through `spec_depends_on`, while the bug itself stays a description of the defect.

Accordingly, no block with that label ever appears in a bug's `# Gates`, and no branch of `spec_plan_done`'s readiness waits on one.

## Tool determination

Tools are determined from the **approved** `bug.md`, not earlier: before approval the reproduction can still change, and with it the defect's location.

The rule is simple: **whatever the defect lives in is what fixes it.**

- defect in product code → `code`;
- defect in entity data files (a wrong value, a wrong schema, a broken link between records) → `data`;
- defect in user documentation (what is written is not what the system does) → `docs`;
- plus `test` — nearly always: the regression case that would have caught this defect is part of the fix. Omitting `test` is a deliberate exception (the defect is not reproducible in the test environment), never a default.

The coordinator writes the resulting list into the status note's `spec_tools` through `note-set-key`. Until that key is written, implementation does not start: the tool set IS the answer to "who does the work". A tool named in `spec_tools` but not declared in the product's `tool_types` is a finding the coordinator reports in `# Status brief`, not a gap it fills in on its own.

A non-obvious choice is a `[!question]` in the status note listing the candidates with a short case for each. The coordinator invents neither a tool the declarations do not carry, nor a silent verdict in a `data`-versus-`code` split that `bug.md` genuinely leaves open.

## The first two gates

| Gate | What closes it on a bug |
|---|---|
| `spec_design_done` | `bug.md.spec_stage == approved` — the reproduction is accepted by review. |
| `spec_plan_done` | `spec_design_done` already `true`, AND for every tool in `spec_tools` whose declaration names a `plan_doc`, that plan is `approved`/`cancelled` or does not exist at all. |

Tool plans are **opt-in**: an asset that authored none reads ready by absence, and that is a normal state, not a gap. Of the shipped tools only `code` (`code-plan.md`) and `test` (`test-plan.md`) declare a `plan_doc`; `data` and `docs` have no plan and bear on this gate not at all.

The gates are a strict ladder — each requires the one before it. The `lazy-spec.flip-gate` primitive flips whichever gate it is called on, unconditionally (its only refusal is a cancelled asset), so the ORDER is held by the coordinator's reasoning, not by a script.

`spec_develop_done`, `spec_tests_passing`, and `spec_released` are not this playbook's to close: the first is an AND over the contributions of every non-`test` tool, the second belongs to the `test` tool, the third is an external release signal. What exactly closes them is stated by the tool playbooks.

## The first-half checkboxes

The coordinator reconciles this set on every relevant wake: it hangs the ones whose condition now holds and takes down the ones whose condition stopped holding. `spec_halted: true` overrides everything — a halted asset carries no checkbox at all.

| Checkbox | Appears when |
|---|---|
| `Write bug` | the asset exists and `bug.md` does not exist yet. |
| `Write <tool>-plan` | `spec_design_done` is true, a tool with a declared `plan_doc` is in `spec_tools`, and the plan document does not exist yet. |
| `Publish` | the terminal gate `spec_released` has closed and `spec_draft` is still `true`. |

No `Write` row's tick is a writer job. For `Write bug` the coordinator seeds the document with `lazycortex-specs seed-doc <product> <folder-note-path> --doc bug.md:bug` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then branches on the folder-note's `## Source requests`. With at least one entry there, review opens immediately with `Skill(lazycortex-review:lazy-review.start, "bug.md")`, and the class's main writer works round 1 reading the request(s) `context_from_frontmatter` resolves from the doc's own attribution. With none (a bug filed without a request), the seed is the whole enactment: the operator writes the reproduction into the skeleton and commits, that commit is the coordinator's ordinary operator-edit wake, and on it — seeing a non-empty body on a doc with no active review — the coordinator opens review with `lazy-review.start`, the writer refining the operator's text as round 1.

Block shape in `# Gates`:

```
> [!gate] Write code-plan
> - [ ] Write code-plan
> tick to dispatch: planner writes code-plan.md from bug.md
```

The tick is an operator gesture; on its next wake the coordinator enacts it — the seed-then-start flow above, for `Write bug` and `Write <tool>-plan` alike — and removes the block.

`Write <tool>-plan` rides the same flow with the tool's own document: the coordinator seeds the tool's declared `plan_doc` (`lazycortex-specs seed-doc <product> <folder-note-path> --doc <name>:<type>`, doc name and type from the tool's own declaration) and branches on `## Source requests` exactly as above; the class's main writer works round 1 inside the review loop, where `bug.md` plays exactly the source role that a design document plays on other types.

`Publish` is the one label that never produces a job: the tick clears `spec_draft` through `note-set-key`, and the coordinator removes the block.

Implementation checkboxes (`Start implementation (<tool>)`, `Start testing`) are declared by the tool playbooks — they are not here.

## Duplicates and regressions

A new bug is often not new. A tester who notices this while writing `bug.md` does not decide alone: they record a three-way proposal in the document's body —

1. **create** — the defect stands on its own and the resemblance is superficial;
2. **link** — the defect is separate but follows from a known one; the link is written into `spec_depends_on`;
3. **reopen** — this is the same defect, closed earlier: work continues in the existing asset, whose `spec_tests_passing` and `spec_released` the coordinator turns off through `flip-gate --off`, and no new asset is created.

The coordinator re-checks the proposal itself — reading the named candidate asset in full, not its title — and executes its own conclusion, not the submitted one. A divergence between the tester's reading and its own is never resolved silently: `[!question]`, naming the candidate and both readings. Reopening an asset the operator explicitly closed as "will not be fixed" always goes through a question.

A regression arriving from another asset's cascade is the same mechanism: a red run yields a proposal to open a bug, and the coordinator decides whether that is a new asset or a reopening of an old one.

## Pre-launch rollback

When an incoming request attaches to a not-yet-launched bug and is about to rewrite its reproduction, whatever was already built on the old version has to come down. The drop list for the `attach` line is **the plans of the declared tools** (`code-plan.md`, `test-plan.md` — those that exist). No architecture document appears in that list and none can: a bug never creates one.

Rollback order: cancel the active job, stop review on the plans being dropped, unlink them from the worktree, turn `spec_plan_done` and every gate below it off through `flip-gate --off`, then stamp the request's attribution onto `bug.md` (`spec_source_requests`) and return it to review — the writer reads the request itself through `context_from_frontmatter`; no delta text is written into the document. `spec_design_done` is left untouched — the reproduction is precisely what the request is revising.

An asset whose work has already launched (`spec_develop_done` true, an implementation job active, or a tool report already on disk) never reaches this path: changes to it ride a separate asset, not a rollback.
