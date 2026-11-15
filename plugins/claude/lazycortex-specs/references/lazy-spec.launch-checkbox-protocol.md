---
name: lazy-spec.launch-checkbox-protocol
version: 1
description: Wire shape of the launch-checkbox layer in a status note's `# Gates` — the `spec_halted` key and the runtime `active_job` marker, the open label set, the grouped `[!gate]` callout shape, the review-launch block written by `review-rows`, the fixed dispatch wire (`target_doc`, expert resolution, guidelines context, dedup key), the `Publish` freeze point, and the wake hops between notes. Which labels exist and what a tick dispatches is the playbooks', never this file's.
---
# Launch checkbox protocol — operator-triggered dispatch

Extracted from `lazy-spec.lifecycle-protocol.md` Part 3, which keeps a stub under that number: the lifecycle protocol carries the gates, this file the checkbox layer built on top of them.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

A layer on top of the gates: checkbox rows the coordinator renders, reconciles, and dispatches in `# Gates`, letting the operator queue the next unit of work with a single tick. **This protocol documents the WIRE shape only — the frontmatter keys, the runtime job marker, and the checkbox callout's markdown shape.** Which labels exist, when each appears, when it comes down, and what a tick dispatches is declared by the asset's type and tool playbooks and applied by the coordinator (`lazy-spec.coordination-playbook.md` Chapter 5) — no script hangs, removes, or dispatches a checkbox anymore.

## Frontmatter and the job marker

One additional frontmatter key:

```yaml
spec_halted: true                                              # absent by default; only present once an active job dies
```

Readiness for a downstream repo (another repo's own `lazy-spec.upstream-tick` when this repo happens to be its configured source) is `spec_released` alone (`lazy-spec.lifecycle-protocol.md` Part 2, Linear map). Notes written before the readiness flag moved there still carry a `spec_draft` key; the `migrate-readiness` verb, run by `/lazy-spec.install`, rewrites them.

The dispatched job itself is NOT frontmatter. It lives in the gitignored runtime sidecar at `<repo>/.runtime/lazy-specs.jobs.json`, keyed by the note's repo-relative path, under the `active_job` field:

```json
{"checkbox": "Build", "expert": "claude-plugin.developer", "job_id": "20260101-abcd"}
```

Writes go through `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> mark-job <asset_note> active <json>` (or `--clear`), which validates the object's SHAPE and nothing else: exactly the three keys `checkbox` / `expert` / `job_id`, each a non-empty string. The label's spelling is not checked against any list — the vocabulary belongs to the playbooks, not to this primitive. The coordinator writes the marker as part of dispatching the job it tracks; `lazy-spec.gate-tick`'s active-job polling pass (`lazy-spec.lifecycle-protocol.md` Part 2) is the one piece of code that clears it, and on clearing it records the retired job in the same entry as `last_job`, `{"checkbox", "expert", "job_id", "outcome", "marker"}`, `outcome` being the job's own `response.json` `outcome` (the lowercased marker when the job left no response naming one) and `marker` the job bundle's terminal marker lowercased (`done`, `dead`, `cancelled`); the `job-done` wake reads the finished job from there, never from `active_job`. Because the marker is runtime state rather than document content, neither write costs a commit, and an operator hand-editing the folder-note cannot lose a live job's record. Read it back through `note-check`, whose result carries the note's `job_markers` entry; a `spec_active_job` key found in frontmatter is a regression, not a source.

## The label set is open

There is no fixed list of labels in this protocol, and no primitive holds one. The VOCABULARY — which labels exist on a note, what each one's appearance condition is, and what a tick enacts — is declared by the note's type playbook (and, on a level note, the level playbook); the coordinator reconciles exactly that declared set on every relevant wake (`lazy-spec.coordination-playbook.md` Chapter 5). A design-only asset hangs `Write <doc>` rows only; a release note hangs `Write code-plan`, `Build`, `Write test-plan`, `Test`, `Rebuild` and `Publish`, and dispatches its jobs under the labels `Build` and `Test` — each on the operator's tick, never by rule; a product note that owns releases hangs `Revise architecture` and `Start release` beside its `Write` rows. No `Start coding` / `Start data entry` / `Start documentation` / `Start testing` row exists any more — the implementation of every asset is a release's build (`lazy-spec.release-playbook.md`).

The one label outside that arrangement is the review-launch label documented below. It belongs to no playbook's vocabulary because it is not a unit of work a playbook could declare — its condition is per-file and reads only a document's own type declaration, its `review_active` flag and its `spec_stage`, so every asset of every type hangs it under the same rule.

`spec_halted: true` overrides every declared label unconditionally in the coordinator's own reasoning — no checkbox is hung, and any already up come down, regardless of gate state.

## Checkbox block shape

```
> [!gate] Write
> - [ ] Write code-plan
> - [ ] Write test-plan
>
> tick to create the document and open its review
```

A launch row is one checkbox line, `- [ ] <label>` or `- [x] <label>`. The rows whose labels open with the same verb — the label's first word: `Write`, `Review`, `Start`, `Build`, `Test`, `Rebuild`, `Publish`, `Revise`, any other — share one `[!gate]` callout inside each layout group: a head line naming the verb exactly as the labels write it, in every note language, one checkbox line per row, a blank quoted line (`>`), and one footer line, in the note's language, saying what a tick does. No row carries a hint of its own. The blank quoted line is structural: without it the footer is the last checkbox item's continuation, and Obsidian's task renderer hides it in reading view (`lazy-spec.status-note-protocol.md` Part 4). A row's label is always read off its checkbox line, never off the callout's head. A note written before this shape may still carry one block per row — the label in the head, the same label on the checkbox line, a blank quoted line, a hint — and every reader takes it the same way. `[!gate]` callouts in `# Gates` are checkbox callouts and nothing else — `lazy-spec.flip-gate` writes no callout of its own.

A label therefore reads one of two ways: a **dispatch label** declared by the asset's type or tool playbook, or the **review-launch label** `Review <file>.md`, naming a reviewable markdown file of the asset. The second is the one label class this protocol names itself, because it belongs to no playbook's vocabulary — see below.

## The review-launch block

The second class of launch row. Label `Review <file>.md`, in the `Review` callout of its group, under the footer that says a tick opens review:

```
> [!gate] Review
> - [ ] Review pricing.md
>
> tick to open review: the document re-enters the loop at the reviewer round
```

The rows are written by one verb, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> review-rows <note>`: it computes the reviewable set below for the note, hangs a missing row into its `Review` callout, takes down an un-ticked row whose document left the set by deleting its checkbox line (the callout goes with its last row), never removes a ticked one, lays the whole section out into the grouped shape, and commits nothing. The coordinator runs it on every wake and again after enacting a tick; when it runs and how a tick is enacted is `lazy-spec.coordination-playbook.md` Chapter 5. The `migrate-gate-rows` verb folds an older note's one-row blocks into the grouped shape the same way, without adding or removing a row.

- **The reviewable set.** One row per markdown file of the asset whose `spec_doc_type` declares `review: true` and not `append_only: true`, in any `spec_stage` except `cancelled`. The verb reads each file's type declaration; a document whose type has `review: false` never hangs a box, and neither does a file carrying no type at all. The append-only report journals never hang one: a report enters review only when the job writing it finishes. Ownership does not enter this — an attachment and a canonical document are gathered by exactly the same rule, which is the point of typing. A level note (product root, catalog root) is gathered by the same rule over the level's own documents.
- **Granularity is the file.** The asset layout is flat, so there is nothing coarser to offer.
- **A document already under review hangs no box.** A file carrying `review_active: true` is in the loop; a second entry gesture is meaningless. The box returns when the review ends.
- **The tick opens review, it does not dispatch.** It invokes `lazy-review.submit` for that file — preceded by the `set-stage` verb with `<file> draft` when the file sits at `empty` or `deferred` — so review opens at the reviewer round, and the writer-round entry is never reachable from this row. A file that is still the untouched template has nothing to review, and its tick launches nothing. No expert job is queued and no `active_job` marker is written, which is the one structural difference from a dispatch label. In that respect it behaves like `Publish` below, but it clears no flag and hangs on a per-file rather than a per-asset condition.
- **Class resolution is not this block's business.** Every row resolves its class the same way any document does, from its own `spec_doc_type`. The verb only decides which files get a row.
- **`spec_halted: true` takes every un-ticked row down**, exactly as it does for a dispatch label.

## Dispatch (ticked checkbox → expert job)

A launch row a human left ticked is queued as one expert job through the `dispatch-job` verb. WHICH role, source, context and result each label carries is named by the playbook that declares the label; what stays fixed across every label is the wire below:

- **`target_doc` in the payload** — every job dispatched to write a catalog document carries `target_doc` in its `request.json` payload: the repo-relative path of the document that job writes. The job returns only content, through its own `result/`; where that content belongs is settled at dispatch, by the side that knows the ladder, and travels with the job. The `land-result` collector reads the key to place the returned document, and refuses a job that declares none — nothing is landed, the document stays in the job's `result/`, and the job reads as undelivered. A declared path outside the asset's own folder is refused the same way — except a cascade job, whose target lies in another asset's folder by design and is named explicitly by the coordinator at landing time: `gate-tick` neither refuses nor halts on a `target_doc` in another asset's folder inside the catalog, it retires the marker, records `last_job`, raises `job-done` and leaves the bundle for the coordinator's `land-result --target` (`lazy-spec.change-cascade-protocol.md`).
- **Expert resolution** — a release's `Build` job, and every continuation of it, goes to the release implementer `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product release-implementer <product-key>` names for the product that owns the release (`lazy-spec.release-playbook.md`, "The build"). Every other job's expert is resolved from the review class of the checkbox's own RESULT document (its basename with `.md` stripped), read from `review.classes[<class>].experts.main[0].name` — the same class the document's own review loop uses once it exists.
- **Guidelines context** — the product's `guidelines[<role>]` paths, then the asset type's `asset_types[<type>].guidelines`, then the wildcard `guidelines["*"]` paths (per `lazy-spec.config-protocol.md`) fold into the job's `context`; a declared path that does not resolve to a file is a dispatch warning journaled in `# History` as a job that failed to start — by the coordinator through `note-history` for a job it dispatched itself — never a silent drop.
- **Dedup key** — `<note-path>:<label>` (the status note's repo-relative path plus the label, per `lazy-spec.coordination-playbook.md` Chapter 5's dedup clause), guarding a second tick of the same checkbox while the first job is still active.
- **On success** — the coordinator removes the ticked block and marks `active_job: {"checkbox", "expert", "job_id"}` via `mark-job`. The marker follows every `dispatch-job` against an asset, ticked or not: a release's `Test` and `Build`, the build a `Rebuild` tick owes, and every continuation of the acceptance cycle are marked the same way, under their own label. Nothing is journaled for the dispatch itself — except a release's `Test` dispatch, which lands its once-per-build `note-history` line naming the build — and nothing for the job's finish or cancellation either — only its death, which halts the asset, reaches `# History`.
- **Guards** — a halted asset ignores every ticked checkbox; an asset already tracking an `active_job` also waits — one active job per asset at a time, checked by the coordinator before every dispatch, ticked or rule-driven.

## `Publish` — the release's freeze point

`Publish` hangs on a release note only, once the release's `spec_built` has closed while its `spec_released` is still false; a design-only asset never hangs it. The tick is enacted with `release-publish <release-note>`, which never queues an expert job: when the product declares `release.deploy.production` it deploys there first — a failed deploy writes one `# History` line, changes nothing else and re-hangs the row — and on success it stops every review still open in the release folder and walks `spec_includes` against the release's `spec_impl_build_at`: a cancelled member is skipped; a member whose start document is not `approved`, or whose start document or `ui-design.md` was approved after `spec_impl_build_at`, gets the `release/<x-y-z>` tag and stays unreleased — a re-approved member whose note reads `spec_design_done: true` is painted `awaiting-release`, every other one keeps the `spec_state` its own coordinator painted; every other member gets `spec_released: true` with its moment and the tag. It sets the release's own `spec_released: true` with its moment, writes the version into the product's manifest when one is named, and lands the whole set in one commit; its answer lists the members under `assets` (released), `reapproved` (tagged, left unreleased because a later approval was not built), `unbuilt` (tagged, left unreleased in the state its own coordinator painted because the start document is missing, not approved or carries no `spec_approved_at`) and `cancelled` (skipped). A refused publish leaves nothing behind: every review it stopped gets its bytes back and its wake raised again, and nothing is left uncommitted. The release is frozen from that commit on; every later edit goes into the next release (`lazy-spec.release-playbook.md`, "Release and Publish").

`spec_released` names one downstream consumer today (another repo's own `lazy-spec.upstream-tick`, when it configures this repo as one of its `spec.upstream` sources), but its documented meaning is not tied to that path — it is "this asset is published and ready for a downstream consumer to pick up" (absent or false means not ready). Two notes close it without a release: a research asset's closes on the approval of its `research.md`, and in a spec-only product (`lazy-spec.coordination-playbook.md` Chapter 17) the coordinator closes it on the operator's explicit word.

## Wake hops between notes

Four wakes travel between notes, each one hop, each raised after the raising note's own write has landed, each best-effort:

- `asset-approved` — the `spec_design_done` or `spec_cancelled` of an asset of any type but `release` changing value, in either direction, the re-approval of its start document, which crosses no gate, and the `spec_cancelled` of a `release` changing value, reaches the level note of the product that owns releases, with `payload["asset"]` relative to that product. It re-hangs rows and rewrites `# Status brief`, and beyond that may only cancel an open release whose every `spec_includes` member is cancelled or released — `lazy-spec.catalog-playbook.md` § 5.
- `release-start` — the product coordinator waking a release's own note once after `Start release`, and again when the product's `architecture.md` turns `approved` while a release is open — or on an `asset-approved` wake naming an approved asset that is not a member of the open release, while `release-delta` reports `architecture.behind` empty (no `architecture.md` file, or the product's `# Coordinator rules` waive it and the call carries `--no-architecture`) — through `coordinator-dispatch --release-start <release-note>` — the one downward hop a level makes; a note that is not a release refuses it. The same wake reaches an open release when a `review_result` turns approved on a stage-bearing document of one of its members, and when one of its members' `spec_cancelled` changes value, so a re-approval reaches the release's `Rebuild` reasons without an operator edit. The release reconciles its rows, rewrites `# Status brief` and `spec_state`, and dispatches nothing.
- `release-published` — `release-publish` waking the level note of the product that owns the release once, after the publish commit; a failed production deploy raises nothing, and a failed wake never fails the publish. It only re-hangs rows.
- `release-member` — a release waking the status note of each member it repainted, after its scaffold, refresh, publish, cancel or un-cancel commit landed; a release or a level note refuses it, and a member busy with a job keeps it as a declined wake. The member re-reads its state, rewrites `# Status brief` and `spec_state`, and dispatches nothing.

`asset-approved`, `release-start` and `release-member` are raised by `coordinator_dispatch.py`.
