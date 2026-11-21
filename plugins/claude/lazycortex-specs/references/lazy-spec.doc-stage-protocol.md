---
name: lazy-spec.doc-stage-protocol
version: 1
description: Per-file `spec_stage` contract for authored spec docs — the closed six-value set, which document types carry it, its mapping to lazycortex-review flags, the transitions (asset cancel and un-cancel, parking, the one downward Rebuild move), the `spec/<stage>` mirror tag, and `lazy-spec.set-stage` as the single mutator through which the coordinator's stage promotion also runs.
---
# Per-file stage protocol — `spec_stage` on authored docs

Extracted from `lazy-spec.lifecycle-protocol.md` Part 1, which keeps a stub under that number: the lifecycle protocol carries the flat gates on the status folder-note, this file the per-file stage layer that feeds them.

## Frontmatter

Every authored doc carries:

```yaml
spec_stage: draft        # empty | draft | approved | rejected | cancelled | deferred
tags:
  - spec/draft           # mirror of spec_stage value (see "Status mirror tag" below)
```

A document the cancel of its asset moved to `cancelled` also carries `spec_cancelled_with_asset: <stage>`, the stage it had before the move (`empty`, `draft`, `approved`, `rejected` or `deferred`; a mark reading `true`, left by an earlier version, means `draft`), and one whose review that cancel stopped carries `spec_review_stopped_with_asset: true`: the cancel writes the marks and the un-cancel reads them (§ Transitions).

## Closed stage set

Exactly six values. The old `review`, `done`, and `wtr` are gone — "in review" is now `spec_stage: draft` + `review_active: true`; "accepted" is `approved`.

- `empty` — doc seeded and not yet worked on, or not needed right now (resolved for optional docs). No review: a document leaves `empty` for `draft` in the same commit that opens its review.
- `draft` — content being written. Maps to `review_active: true` once opted into the loop, OR pre-review (authored but not yet submitted). No separate waiting-room state.
- `approved` — accepted: `review_approved: true`, with no review running at the moment of approval. The document may be put under review again later (the catalog and coordination playbooks reopen review on an approved document) and stays `approved` while that review runs: `review_active: true` on an `approved` document is a legal state, and only `lazy-spec.set-stage` moves the stage. Approved-with-concerns collapses to `approved`: the outcome is read from `review_result` (`approved` | `approved-with-concerns`), the one review key finalize leaves on the doc, but `spec_stage` is plain `approved`.
- `rejected` — review or developer flagged the doc unworkable (a finalize-revert): a rejection callout sits in the body. **NOT terminal** — the doc returns to `draft` to re-open the loop.
- `cancelled` — doc abandoned, on its own or together with its asset: cancelling an asset moves every staged document of its folder here. A document cancelled on its own leaves only for `draft`. One the cancel of its asset moved here leaves, when the asset is un-cancelled, for the stage the cancel recorded: `empty`, `deferred` and `rejected` back as they were, `draft` staying `draft`, `approved` to `draft` with its review opened at the writer round (§ Transitions).
- `deferred` — doc parked: it exists, it is not abandoned, and nothing automatic acts on it. Its own `review_result` raises no doc-transition wake, stage promotion passes it over, it closes no gate, no `Write` row is hung or replacement seeded for it, and no coordinator edits it. A commit touching it still wakes the owning coordinator as an ordinary operator edit, so the folder note is kept in order around it. Not terminal — it has two exits: `draft` brings it back, `cancelled` abandons it where it sits.

## Applies to

Documents whose `spec_doc_type` is declared with `stages: true` (the shipped types with the flag set: `vision`, `system-vision`, `use-cases`, `system-use-cases`, `design`, `system-design`, `ui-design`, `system-ui-design`, `code-plan`, `test-plan`, `bug`, `system-tech`, `system-architecture`, `system-test-plan`, `content-design`, `research-design`, `research-report`). Which document kinds those are is a property of the declaration, not of a filename — see `lazy-spec.file-roles-protocol.md` § Document type. Which of them a given asset actually carries is the type playbook's declaration, not this file's: a plan document exists exactly where a type playbook declares one (a release's `code-plan` and composed `test-plan`, an asset's own `test-plan` behind `Write test-plan`), and its absence is a declared state, not a gap `lazy-spec.audit` flags.

Does NOT carry `spec_stage` — every type declared `stages: false`, plus the untyped notes: the status folder-note (carries gates instead); container folder-notes (`<product>.md`, `bugs/bugs.md`, …); the append-only report journals (a release's `code-report.md` / `test-report.md`, and any document of a type a product declares with `append_only: true`) — they are written during execution, never approved into a stage, and carry no lifecycle state of their own; the opt-in `decisions.md` registry (product-level or asset-level) — it is an append-only registry written only by the `decide` primitive, never opted into review, and carries no lifecycle state of its own. They sit outside both layers of this protocol: no per-file stage, no role in any gate precondition. A report whose type is declared with stages — a research asset's `research.md`, typed `research-report` — carries a per-file stage like any authored document and is not in this set.

## Mapping to lazycortex-review v4 flags

| `spec_stage` | lazycortex-review v4 flags |
|---|---|
| `empty` | no review opened on the doc |
| `draft` | `review_active: true` (in the loop), OR pre-review (authored, not yet submitted) |
| `approved` | `review_approved: true`; `review_active` reads `false`, or `true` while a reopened review runs on the still-approved document; approved-with-concerns collapses here (the outcome is read from `review_result`) |
| `rejected` | finalize-revert; a rejection callout in the body |
| `cancelled` | abandoned; leaves for `draft`, or, on its asset's un-cancel, for the recorded stage (`empty`, `deferred`, `rejected` as they were; `draft` and `approved` to `draft`, an `approved` one with a writer-round review) |
| `deferred` | parked; whatever review flags the doc carries raise no transition while it stays here |

## Transitions

Forward: `empty → draft → approved`.

`rejected` is reachable when a review or developer rejects the doc; the only path out is back to `draft` (re-open). `cancelled` is reachable from `empty`, `draft`, `approved`, `rejected` and `deferred`.

Cancelling an asset cancels its documents. `flip-gate <asset> spec_cancelled` sets the flag and, in the same commit, stops the review of every markdown file directly in the asset folder that carries `review_active: true` — a report journal included — marking each stopped document `spec_review_stopped_with_asset: true`, and moves every staged document there to `cancelled` through `lazy-spec.set-stage`, marking each moved document `spec_cancelled_with_asset: <stage it had>` in the same write as the stage, its `spec/<stage>` tag following, its top-of-body `#status/<state>` callout — the review plugin's status banner — removed through the review plugin's `strip-status` verb (no commit), and its attachments with it, clears the note's `pending_wake`, and cancels the asset's running job last, recording it as `last_job` with `outcome: cancelled`. The defining documents go too: this is the one call that moves a `design.md` or a `bug.md` to `cancelled`. On a release the same commit repaints the members with `spec_design_done: true` `awaiting-release`, and each repainted member gets a `release-member` wake. When a review cannot be stopped or the job cannot be cancelled, the whole cancel is refused and nothing is written: the reviews already stopped in the call are resumed and their wakes raised again. A cancel refused or crashed after it has killed the job leaves `active_job` null, that job recorded as `last_job` with `outcome: cancelled`, raises `pending_wake: job-done`, and names it as `killed_job` in the result. A published release and a release under `releases/archive/` refuse the cancel the same way. A stopped review keeps its round and phase, so nothing is lost if the asset comes back. A document that cannot be moved keeps its bytes and is named in the call's result; documents of a nested asset are not touched.

An accepted document still at `empty` is promoted like a draft: `promote-approved` moves a document whose review ended accepted from `empty` or `draft` to `approved`, so a verdict never strands on a document whose stage was not advanced when its review opened.

`cancelled` is left through `draft`, or, on an un-cancel, through the stage the cancel recorded. The un-cancel is the operator's `flip-gate <asset> spec_cancelled --off` — the verb clears `spec_cancelled` and returns every document the cancel marked through `lazy-spec.set-stage`, its `spec/<stage>` tag following and the mark removed: a document recorded at `empty`, `deferred` or `rejected` goes back to that stage, one recorded at `draft` (or carrying a `true` mark) to `draft`, and one recorded at `approved` to `draft` with its review opened at the writer round in the same commit (through the review plugin's `start --no-commit`; a document whose review the cancel also stopped is resumed once, not opened twice); the verb resumes every review it marked `spec_review_stopped_with_asset: true`, turns off every derived gate whose document it took out of `approved` — on a release, a `code-plan.md` taken out of `approved` turns off `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built`, a `test-plan.md` alone `spec_tests_passing` and `spec_built` — on a release sets `spec_rebuild_owed` only for the job this cancel retired — a `last_job` carrying `retired_by_cancel: true` and `unlanded: true` whose `job_id` equals the release's `spec_build_job` or `spec_test_job` — and drops that stamp; an earlier unlanded failure (a refused landing, a dead job) carries no stamp and keeps waiting for the operator's `Rebuild` tick, and on a release repaints the members with `spec_design_done: true` `in-release` and wakes each with `release-member`, all in one commit, then wakes the asset's own coordinator; a document cancelled on its own before the asset was cancelled carries no mark and stays `cancelled`; on a release the un-cancel is refused, with nothing written, while another release of the same owner is open or when the release sits under `releases/archive/`; from there each document takes the ordinary path, review then approval. Every return from `cancelled` also drops the document's `review_result`, so a document cancelled after approval is not promoted straight back on the verdict it carried before the cancellation. A direct `set-stage` call moves a cancelled document to `draft` only; every other move out of `cancelled` — to `approved`, or to `rejected`, `deferred` or `empty` outside the un-cancel's restore of the recorded stage — is refused. `approved` is terminal for every writer but one: on a `Rebuild` tick `spec.coordinator` moves a release's approved `code-plan.md` / `test-plan.md` back to `draft` when an included asset's document the plan was made from changed — a re-approved design, a newly included asset, a new or re-approved `ui-design.md` or test-cases document — while a plan of the release's own re-approved after the release's `spec_impl_build_at` (the `test-plan.md` after its `spec_test_dispatched_at`) stays `approved`, and a `cancelled` plan stays `cancelled` (`lazy-spec.release-type.md`, "Rebuild", step 3) — the only downward stage move in the system, always with a `# Status brief` sentence naming the change. The move also drops the document's `review_result`: the verdict no longer describes it, and a draft still carrying an accepted verdict would be promoted straight back to `approved` on the next promote walk. A re-approved source never lowers the stage of a document that depends on it; contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19). `rejected` is a re-open marker, NOT terminal.

`deferred` is reachable from any stage on any stage-bearing type — asset-level and level documents alike — and its only exits are `draft` (unpark) and `cancelled` (abandon the parked document). Those three calls are the whole vocabulary of parking: `lazy-spec.set-stage <doc> deferred` parks, `lazy-spec.set-stage <doc> draft` unparks, `lazy-spec.set-stage <doc> cancelled` abandons it where it sits, and no other target stage is accepted while the document sits parked. Nothing else moves the stage on its own — a review verdict landing on a parked document is recorded on the file and read by nobody until it comes back.

A `set-stage <doc> cancelled` call is refused on `design.md` (asset-level and system-level alike), on `bug.md`, and on the product root's `architecture.md` (type `system-architecture`) — an asset's defining documents are abandoned as a whole through `spec_cancelled`, never one at a time, and a system's design and its architecture are its defining documents too. No asset carries an `architecture.md` of its own. `tech.md` (type `system-tech`) and the plan documents (`code-plan.md`, `test-plan.md`) MAY be `cancelled` — a plan whose work turned out not to be needed is walked back without abandoning the asset. (Enforced by `lazy-spec.set-stage`.) Report journals carry no `spec_stage` at all (see § Applies to), so cancellability is not a question that applies to them.

## Status mirror tag

Every doc carrying `spec_stage:` ALSO carries a hierarchical Obsidian tag mirroring the value:

```yaml
spec_stage: approved
tags:
  - spec/approved
```

The `set-stage` verb behind `lazy-spec.set-stage` is the only writer of both fields. The one exception is a document `lazy-spec.sync-with-code` creates: it is born at `deferred` with both keys written by hand in its Step 8; every later stage change goes through the verb. `lazy-spec.audit` validates that the tag matches the field; a mismatch is a finding.

The tag enables Obsidian queries (`#spec` for all stage-bearing docs, `#spec/approved` for accepted only, etc.) without requiring Dataview to parse frontmatter values.

## The single mutator — `lazy-spec.set-stage`

`lazy-spec.set-stage <file-path> <new-stage>` is the ONLY primitive that changes a per-file stage. Every per-file stage change in the system goes through it; no skill, worker, or coordinator call raw-edits `spec_stage`. The skill runs the `set-stage` CLI verb, which owns every check, the mirror tag and the `spec_approved_at` stamp; its refusals arrive in `reason`. The stamp is the moment the document last entered `approved`, and it exists only while the document is `approved`: it is written on entry into `approved` (and on an explicit restamp), and removed on every move out of `approved`, so a reader such as the coherence check never takes a stale stamp for a current approval. Its type check reads the declaration, never the path or basename, which is what keeps the status folder-note, every append-only report journal and the `decisions` registry out of reach — none of them carries an independently-settable stage. No history line is written on any stage move.

It does NOT advance the folder-note's gates — deciding whether a gate is ready to move, and calling `lazy-spec.flip-gate` to move it, is `spec.coordinator`'s call (`lazy-spec.lifecycle-protocol.md` Part 2). The full skill contract lives at `${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.set-stage/SKILL.md`.

## Stage promotion — a coordinator decision, executed through this same primitive

**Playbook, not code.** Nothing in this repo auto-promotes a stage anymore. Per `lazy-spec.coordination-playbook.md` Chapter 4 ("Stage promotion"), the coordinator itself runs one `promote-approved <note>` call on every wake, before evaluating any gate; the verb owns which documents it promotes and which it skips, and reports each refusal in `reason` without stopping the walk. Running it before the gates matters because a gate reads the promoted stage. Each promotion is the exact same mutation `lazy-spec.set-stage` always performed (the `set-stage` verb's write, no history line), simply invoked through a coordinator primitive rather than by a dedicated worker step. There is no longer a separate "auto-promotion" code path, and no separate `empty → draft` pre-review promotion tied to a gate flip's own side effect — opening review on a freshly-authored plan document is itself now a coordinator-dispatched launch-checkbox job (`lazy-spec.launch-checkbox-protocol.md`), not something a gate flip triggers as a cascade.
