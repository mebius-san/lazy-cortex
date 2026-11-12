---
name: lazy-spec.bug-playbook
description: Type playbook for bug assets — the bug-typed primary document written by a tester, no architecture document ever, tool determination from the reproduction, and the two design-only gates of a defect whose fix ships in a product release.
---
# Bug type playbook — from reproduction to an approved defect

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: bug`. It covers the whole flow of the asset, which is design-only: what defines the asset, what closes `spec_design_done`, which checkboxes hang on the note, and how the fix reaches a product release. The build and its verification happen inside the release and are declared by `lazy-spec.release-playbook.md` — their labels are not duplicated here.

## What this type is

`spec_asset_type: bug` — the asset describes a defect: observed behaviour diverges from behaviour that is already approved or plainly implied.

- **Primary document** — `bug.md`, `spec_doc_type: bug` (the type declaration names it as `start_doc: "bug.md:bug"`). Nothing seeds it at spawn — spawn lands only the asset folder and its status folder-note (with its `## Source requests` section), and `bug.md` launches later through the `Write bug` checkbox on that note. A tester writes it — the role, not whoever sits at the keyboard; the sections are the template's. A bug never carries a design document: `design` is a document about what is being built, and a bug speaks about what is already broken.
- **Location is not a fact of the type.** The declaration's `default_path` drops new bugs into the bug subfolder, but a bug is legal anywhere in the catalog: alongside the product's other bugs, or nested inside the folder of the feature it concerns. The asset boundary stays the folder whose folder-note carries `spec_role: status`; a nested bug is its own asset with its own status note, not a part of its parent. Type resolution reads `spec_asset_type`, never a path.
- **Design-only.** The bug's own ladder ends at the approval of `bug.md`: that approval closes `spec_design_done`, and the fix ships in a product release — the release that carries the bug in its `spec_includes` closes `spec_released` when it is published. The status note carries three gates, `spec_design_done`, `spec_released` and `spec_cancelled`; no plan, develop, tests or built gate exists on it.
- **Documents.** Exactly one is mandatory — `bug.md`; `cancelled` is refused on it (the asset is abandoned as a whole through `spec_cancelled`, never through its primary document). `test-plan.md` may stand beside it — the test cases hung through `Write test-plan` below. Plans and reports belong to the release that ships the fix; the `decisions` registry is opt-in and written only by the `lazy-spec.record-decision` primitive.

## There is no architecture step

The `Write architecture` checkbox never hangs on a bug — not on a code-bearing judgment, not on an expert's request, not on a large defect. A bug never has an architecture document: an architecture document describes the shape of code an asset introduces, and a bug introduces nothing — it returns the system to a shape already approved. The product's `architecture.md` is revised by the architect at the start of each release build if the fix needs it. When the fix does require changing the approved shape, it is not a bug: the coordinator raises an `[!asset-proposal]` for a `change` (or `feature`) asset that names the bug as its source, while the bug itself stays a description of the defect.

Accordingly, no block with that label ever appears in a bug's `# Gates`.

## Tool determination

Tools are determined from the **approved** `bug.md`, not earlier: before approval the reproduction can still change, and with it the defect's location.

The rule is simple: **whatever the defect lives in is what fixes it.**

- defect in product code → `code`;
- defect in entity data files (a wrong value, a wrong schema, a broken link between records) → `data`;
- defect in user documentation (what is written is not what the system does) → `docs`;
- plus `test` — nearly always: the regression case that would have caught this defect is part of the fix. Omitting `test` is a deliberate exception (the defect is not reproducible in the test environment), never a default.

The coordinator writes the resulting list into the status note's `spec_tools` through `note-set-key`, on the wake that sees `bug.md` approved. The asset does not enter a release delta until `bug.md` is approved; once a release carries it, the release implementer reads its `spec_tools` — the tool set IS the answer to "who does the work": the implementer does its own tool's work itself and, for every foreign tool, launches a child agent with that tool's expert (resolved as always from the review class of the tool's `report_doc`), handing it `bug.md` and the tool's guidelines. A tool named in `spec_tools` but not declared in the product's `tool_types` is a finding the coordinator reports in `# Status brief`, not a gap it fills in on its own.

A non-obvious choice is a `[!question]` in the status note listing the candidates with a short case for each. The coordinator invents neither a tool the declarations do not carry, nor a silent verdict in a `data`-versus-`code` split that `bug.md` genuinely leaves open.

## The gates

| Gate | What closes it on a bug |
|---|---|
| `spec_design_done` | `bug.md.spec_stage == approved` — the reproduction is accepted by review. |
| `spec_released` | the release that carries the bug in its `spec_includes` is published: the operator's `Publish` tick on the release note sets `spec_released: true` and `spec_released_at`, and adds the version tag `release/<major>-<minor>-<patch>` to the note. A re-approved `bug.md` turns it off again (`lazy-spec.coordination-playbook.md` Chapter 4), and the bug waits for the next release. |

The gates are a strict ladder — `spec_released` requires `spec_design_done`. The `lazy-spec.flip-gate` primitive flips whichever gate it is called on, unconditionally (it refuses every flip on a cancelled asset but the un-cancel `spec_cancelled --off`, and it refuses to turn `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` or `spec_built` on, because those keys exist on a release note only), so the ORDER is held by the coordinator's reasoning, not by a script.

`spec_released` is never this coordinator's to close: the product coordinator writes it when the release is published. Between the approval of `bug.md` and that publication the bug reads `spec_state: awaiting-release`, and `in-release` once an open release's `spec_includes` carries it.

**Downward reconciliation.** A gate already true goes stale when its governing document reappears un-accepted. The coordinator flips the gate back with `flip-gate --off` and re-runs its upward checks in the same pass. A re-approved document never lowers the stage of a document that depends on it (`lazy-spec.coordination-playbook.md` Chapter 4); contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The checkboxes

The coordinator reconciles this set on every relevant wake: it hangs the ones whose condition now holds and takes down the ones whose condition stopped holding. `spec_halted: true` overrides everything — a halted asset carries no checkbox at all.

| Checkbox | Appears when |
|---|---|
| `Write bug` | the asset exists and `bug.md` does not exist yet. |
| `Write test-plan` | `spec_design_done` is true and `test-plan.md` does not exist yet. |

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

No `Write` row's tick is a writer job. For `Write bug` the coordinator seeds the document with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc bug.md:bug` — the type's template chain, stage `empty`, the folder-note's `spec_source_requests` copied onto the doc — and then opens its review immediately with `Skill(lazycortex-review:lazy-review.start, "bug.md")`, whether or not the folder-note carries any `## Source requests` entry. The class's main writer works round 1 from whatever exists: the request(s) `context_from_frontmatter` resolves from the doc's own attribution, when there are any, and the documents its research aspect obliges it to read every time — the asset's own approved siblings and the system documents of the product chain. With neither a request nor an approved document above it, the writer starts from the asset's folder-note and raises what it cannot ground as in-document `[!question]` callouts. The coordinator never waits for the operator to write a first draft; an operator who edits the document does so during the review, as an ordinary operator edit.

**A parked document hangs no `Write` row.** Every row of this table reads "the document doesn't exist", and a document at `spec_stage: deferred` exists — so its row stays down and nothing seeds a replacement beside it, ever. The row that hangs for it instead is the review-launch `Review <doc>` row, whose deferred-document case (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md` Chapter 5) unparks and resubmits the document in one commit when the operator ticks it.

Callout shape in `# Gates` (`lazy-spec.coordination-playbook.md` Chapter 5):

```
> [!gate] Write
> - [ ] Write test-plan
>
> tick to create the document and open its review
```

The tick is an operator gesture; on its next wake the coordinator enacts it — the seed-then-start flow above, for `Write bug` and `Write test-plan` alike — and removes the row's checkbox line.

`Write test-plan` rides the same flow with its own document: the coordinator seeds it with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc <product> <folder-note-path> --doc test-plan.md:test-plan` and branches on `## Source requests` exactly as above; the class's main writer works round 1 inside the review loop, where `bug.md` plays exactly the source role that a design document plays on other types. `test-plan.md` is a definition document with test cases, not a plan of work: it goes through review and approval like `bug.md`, takes part in no gate of the asset, and the tester of the release that ships the fix later composes the release test plan from the product's standing test instructions, these cases and the regression. The row stays open while `test-plan.md` does not exist, including while the bug is already in an open release's `spec_includes`. A new or re-approved `test-plan.md` of an included bug hangs `Rebuild` on the release note, which pulls it into the next build.

The two rows above are the only ones a bug note ever carries. Every implementation and verification row — `Write code-plan`, the release's own `Write test-plan` (the composed release test plan, a different document from the bug's `test-plan.md`), `Rebuild` and `Publish` — hangs on the release note and is declared by `lazy-spec.release-playbook.md`; none of them ever hangs on a bug.

## Duplicates and regressions

A new bug is often not new. A tester who notices this while writing `bug.md` does not decide alone: they record a three-way proposal in the document's body —

1. **create** — the defect stands on its own and the resemblance is superficial;
2. **link** — the defect is separate but follows from a known one; the bug wikilinks the known asset;
3. **reopen** — this is the same defect, closed earlier: work continues in the existing asset, whose `spec_released` the coordinator turns off through `flip-gate --off` (there is no `spec_tests_passing` on the note), and no new asset is created.

The coordinator re-checks the proposal itself — reading the named candidate asset in full, not its title — and executes its own conclusion, not the submitted one. A divergence between the tester's reading and its own is never resolved silently: `[!question]`, naming the candidate and both readings. Reopening an asset the operator explicitly closed as "will not be fixed" always goes through a question.

A regression arriving from a release's test run is the same mechanism: a red run yields a proposal to open a bug, and the coordinator decides whether that is a new asset or a reopening of an old one.

## Attach before a release

When an incoming request attaches to a bug no release has picked up yet and is about to rewrite its reproduction, whatever was already written against the old version has to come down. The drop list for the `attach` line is **`test-plan.md`, when it exists** — its test cases describe the reproduction the request revises. No architecture document and no tool plan appear in that list and none can: a bug never creates the former, and the latter belong to the release.

Attach order (`lazy-spec.attach-drop-playbook.md`): stop review on `test-plan.md` when it is being dropped, unlink it from the worktree, then stamp the request's attribution onto `bug.md` (`spec_source_requests`) and return it to review through a fresh writer round — the writer reads the request itself through `context_from_frontmatter`; no delta text is written into the document. No gate is flipped: an attach leaves every gate on the note as it is.

Whether a request attaches to an asset a release already carries in `spec_includes`, or to a released one, or becomes a separate change, is the operator's tick at routing; an attach there takes this same path, and the release's own `Rebuild` is how the re-approved design reaches the build.
