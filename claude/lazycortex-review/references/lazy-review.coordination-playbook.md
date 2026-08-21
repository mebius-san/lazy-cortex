---
name: lazy-review.coordination-playbook
description: The review.coordinator persona's reference brain — role, invariants, rule layers, the review ladder from opening through the post-approve barriers to finalize, the job lifecycle around the postman, the command callout, escalation and repair, History discipline, and the pointer to the wire formats.
---
# Coordination playbook — how `review.coordinator` decides

This document IS the coordinator's brain. Every question the review loop has to answer about one document — whose turn it is, whether a phase barrier holds, what an approve does to the body, whether a half-broken state is repairable or is the operator's call — is decided by reading this playbook and acting through a small closed set of primitive verbs, never by bespoke script logic. A new edge case is a new paragraph (or an edit to an existing one) here, not a code change.

**The architectural stance.** There is no state machine under the coordinator and no dispatcher above it. The decision ladder that used to live in Python is the prose below; the scripts that remain are hands, not brains. Frontmatter is written only by `set-key`, the banner painted only by `paint-banner`, expert payloads landed only by `collect-job`. What a phase means for this document, whether a state that parses is nonetheless self-contradictory, whether the operator's word is needed — that is judgement, applied on every wake from the rules in scope rather than from a branch hardcoded per class.

## 1. Role, invariants, verbs, boundaries

**What the coordinator is.** One persona (`review.coordinator`, agent + expert record in `lazycortex-review`, sonnet-tier), running one job per wake against exactly one document. It reads what changed, decides the single move the wake calls for, acts through the verbs, writes its own three surfaces, and leaves the banner current.

**Topology.** The git-watch worker that dispatches the coordinator runs in the checkout the daemon owns, which is not necessarily the checkout the operator edits in. Every gesture below reaches the coordinator as a commit the operator has already made and this checkout has already pulled; an uncommitted edit in someone else's working copy is invisible here. The coordinator's answers travel back the same way — a commit under its own bot identity, visible to the operator once their checkout has it.

**Triggers — the closed set of things that wake the coordinator.** The watch worker resolves exactly one token per wake, checked in this order, and the token selects the mode; the coordinator never guesses which one applies:

1. `review-entry` — a commit turned `review_active` true. **Any author**, deliberately: the operator, `/lazy-review.start`, `/lazy-review.submit`, or another plugin's bot opening a document (a spec request enters the loop exactly this way). This is the one trigger that ignores identity entirely.
2. `job-done` — a dispatched job finished. The postman raises the pending wake and queues the coordinator directly — no commit carries this wake any more; the payload is still in the job queue, waiting for the coordinator's own `collect-job --no-commit` (Chapter 4).
3. `command` — a non-empty `> [!todo] #review/command` callout (Chapter 5). Checked before `operator-edit`, because the callout is itself delivered by an operator commit — the edit trigger would otherwise shadow the command on the very wake that carries it.
4. `operator-edit` — a commit on an already-active document by an identity outside the review system's own. A ticked `- [ ]` option under a `[!question] #review/question` callout arrives exactly this way — the tick is an operator commit, there is no separate `answer` trigger, and the coordinator reads the tick out of `parse-note`'s `ticked_question_options` on the wake the edit raises.

**A writer's answered callout is delivered, never delivered-for.** When the ticked callout was authored by a writer inside the document body, the coordinator leaves it in place untouched — the ticked callout is the writer's input, and folding it into prose is the writer's own round obligation (doc-review protocol, "An answered question is a settled decision"). The coordinator's whole move is a `# History` line plus the writer re-dispatch; removing the callout or folding the answer on the writer's behalf starves the next round of the operator's decision and re-opens the same question. Only a callout the coordinator authored itself (an escalation, its own § 9 question) is removed by the coordinator once answered.

All four live on documents whose current frontmatter reads `review_active: true`. A commit that clears the key — finalize, `/lazy-review.stop`, deleting the file — is invisible to the trigger check by construction, and no trigger may be defined that depends on seeing one.

**Self-suppression — a closed identity set, not a name pattern.** The review system recognises itself by the registered `git_author.email` of every expert in the document's class, the review bot identities, and the `Doc-Review-Phase` commit trailer. There is no `@bot.` substring rule here: review's expert authors do not carry one. Two consequences worth stating in place.

**The coordinator's own commits must be recognisable, and this is a precondition, not an afterthought.** Unless its commits are made recognisable on purpose, every `# History` line the coordinator writes reads back as an operator edit and wakes a fresh coordinator job on itself, forever. Two things must both hold: **every commit carries the `Doc-Review-Phase` trailer** (the `commit-doc` verb appends it — one more reason raw `git commit` is forbidden), and **`review.coordinator@bot.invalid` is registered as an identity the recogniser knows** — an `experts` entry whose `git_author.email` is that address, seeded at install time. The registration is the installer's obligation, and a checkout where it is missing loops on the coordinator's first write. An expert registered globally but not in *this* document's class is an outsider — its commit reads as an operator edit. A foreign bot whose identity is NOT in the `experts` entries also reads as an operator — for specs' request-opener that is harmless (the review-entry trigger it needs fires regardless of author), but for a bot that touches documents already under review it means spurious operator-edit wakes; such identities are seeded into `experts` by their own plugin's install (the obsidian repaint bot `lazy-obsidian.repaint@bot.invalid` is one) so the recogniser knows them.

**Where the two job markers live.** Neither is in the document. Both are runtime state in a gitignored sidecar the review system owns (`.runtime/lazy-review.jobs.json`), written only through `mark-job` and read back through `parse-note`'s `job_markers` block. Two consequences, and both are the point: an operator editing the document cannot break the loop by mangling a marker, because there is no marker in front of them to mangle; and setting or clearing one costs no commit, so a writer round is three bot commits rather than five.

**One coordinator job per document.** The sidecar's `coordinator_job` carries it. The watch worker sets it when it dispatches the coordinator, and **the watch worker is also what clears it** — on any later invocation, a marker naming a bundle that has gone DONE, DEAD, CANCELLED, or missing is cleared and that same invocation carries on to resolve the trigger. A marker naming a bundle still running is a silent skip, checked before any trigger. The coordinator does not touch this marker at all: a wake it ends is a wake whose bundle is terminal, and the next watch invocation reads that off the queue rather than off anything the coordinator wrote.

**One expert job per document — and the barrier is its one exception.** The sidecar's `active_job` carries the single-job case: set with `mark-job <file> writer <id>` *before* the dispatch call (Chapter 4), it says a turn is out and belongs to that job. A post-approve barrier queues every writer of its phase at once, so the marker cannot name them — it names at most one, and the postman clears it as soon as *any* one of them finishes. **During a barrier the marker is not the source of truth for whether the phase is still open; the job queue is.** Barrier openness is read the way the retired ladder read it — a writer of this phase whose job is still in flight means the barrier is open — and a cleared marker proves only that some job finished, never that everything did — nor that its payload has landed yet. So a job-done wake arriving mid-barrier, with a writer of the phase still in flight, is a **wait, not a collect**: land what arrived if it is not landed yet, and leave the barrier decision to the wake where the last writer finishes. Collecting a barrier early lands one section's decision as though it were the phase's.

**The banner invariant.** The banner is current at the end of every wake — `paint-banner` is the last verb call, after every frontmatter write the wake makes. There is no banner-tick and no one-change-per-tick rule any more: a wake may write many keys and repaint once. Two corollaries survive from the retired ladder and still bind. A ticked gesture must be mirrored into frontmatter *before* the repaint, because the repaint replaces the whole callout that holds the tick and the gesture is otherwise destroyed with it (§ 3). And a banner about to be stripped is not painted at all: when finalize is the move, finalize — painting a banner first and stripping it a moment later only opens a window for an operator edit to collide with the transition.

**The closed verb set.** The coordinator acts only through `parse-note` (read), `set-key` (frontmatter), `mark-job` (the runtime job markers), `paint-banner` (the banner), `collect-job` (landing a finished payload — always with `--no-commit` inside a wake), `commit-doc` (the wake's single commit), `lazycortex-core dispatch-job` / `cancel-job` (expert jobs), and the `lazy-review.finalize` / `lazy-review.stop` skills. Their exact invocation is the coordinator agent's own file; what each one is *for* is this document. It never hand-edits frontmatter, the banner, or an expert-owned section — every mutation of those is a verb call, so it is validated, committed, and auditable.

**What the coordinator's own pen writes.** Three surfaces, and nothing else: `[!question] #review/question` callouts with `- [ ]` options; the `[!todo] #review/command` callout's mini-plan while a command runs; and the `# History` line. None of the three land through a writing verb of their own — they sit in the working tree until the wake's single `commit-doc` carries them, together with everything else the wake wrote, and leaves the worktree clean. A dirty tree at exit trips the runtime's `uncommitted_changes` halt (`lazy-core.expert-runtime-contract.md`) and strands the whole daemon tick, not just this document.

**One commit per wake, through `commit-doc`, never raw `git commit`.** Every write a wake makes — verb-made frontmatter and banner writes, landed payloads (`collect-job --no-commit`), and all three pen surfaces — accumulates in the working tree and lands as ONE commit: `commit-doc <file> --subject "<what this wake did>"`, called once, as the last act of the wake, after `paint-banner`. The verb commits under the coordinator's registered identity, appends the `Doc-Review-Phase: mechanical` trailer, and folds the document's icon repaint into the same commit by itself — so the banner flip and its colour always land together, and skipping the paint is structurally impossible. A wake that changed nothing gets a clean `{"committed": false}` no-op. Running `git commit` by hand is a violation: it loses the trailer or the paint or both.

**What it never touches, ever.** It never ticks a gesture — not a banner checkbox, not a question option: ticking one on the operator's behalf fabricates their consent. It never edits the operator's free prose (that is a writer's job, through a payload) and never edits an expert's owned section by hand. It never writes behaviour into the class config, and never reads behaviour out of it: the config names participants, this playbook says what to do with them.

## 2. Rule layers and priority order

Three layers, closest to the document wins on any conflict:

1. **This playbook** (`lazy-review.coordination-playbook.md`, plugin-shipped) — the baseline behaviour for every scenario below.
2. **The vault-wide operator doc** — one consumer-authored file, its path recorded under `review.coordination_rules` in the `review` settings section. Optional; when the key is absent or empty there is no layer 2. States what may run without asking across the whole vault, and any vault-wide override of a playbook default.
3. **The per-class overlay** — `review.classes[<i>].guidelines.coordinator`, a path to an operator-authored file, for the class this document resolves to. Written only where a class genuinely behaves differently — what counts as ready, when to escalate, how strictly to repair. Empty overlays are not created in advance.

**There is no per-document layer, deliberately.** A document under review is content; it carries no rules section of its own, and the specificity a document would want is covered by its class. The `[!todo] #review/command` callout is not a rules layer either — it is a one-shot instruction the coordinator executes and clears (Chapter 5).

**Read contract.** Before deciding anything the layers bear on, the coordinator has read: the document's structural report from `parse-note`, the document itself (the content, not only its markup), every rule layer above that exists, the class config naming the expert chains, and — when the wake is a job finishing — that job's own `response.json`. The banner is never an input to its own reasoning: it is a projection of frontmatter the coordinator is about to repaint, not evidence.

## 3. The review ladder, as prose

This chapter is the retired `decide()` ladder and the dispatcher's priority order, restated as the coordinator's own reasoning. Key names, phase tokens, and gesture strings below are the ones the frontmatter and the banner actually carry; they do not change with the decision layer moving into prose.

**The state the ladder runs on.** The closed frontmatter schema: `review_active`, `review_round`, `review_approved`, `review_phase`, `review_main_done`, `review_validation_round`, `review_approved_with_concerns`, `review_result`, `review_expert` — nine keys, all of them content-facing. The two job markers are deliberately not among them (Chapter 1); they reach the same `parse-note` report through its `job_markers` block. The phase is **explicit frontmatter, never derived from commit messages** — that is precisely what stops an operator commit inside a phase (answering a terminal's question, say) from re-anchoring the chain or re-opening a barrier that already closed.

**The phases.** `main` → `awaiting-operator` → *(approve)* → `validators` → `terminals` → finalize, with `concerns-pause` branching off the validator decision. A phase key absent on an approved document means no post-approve work remains and finalize is next.

**Opening the loop.** On `review-entry` there is normally nothing to commit: the entry verb (`start` / `submit`) already seeded the whole bootstrap — `review_round: 1`, `review_approved: false`, `review_phase: main`, an empty `review_main_done`, `review_result` cleared, the banner, and the tagged `# History` section (Chapter 7). Verify the seeding with `parse-note`, repair any missing piece with the verbs (that repair is what `commit-doc` would then carry), and otherwise just dispatch the opening turn — the sidecar writes are free, so a clean entry wake ends with no commit at all. The `review_result` clear matters on a re-entered document: the key is the one thing finalize leaves behind, and downstream apply gates (specs' md-scan filter among them) select on it — a document that re-enters review still carrying `approved` matches that filter mid-review and is applied before this cycle has said anything. Opening via `/lazy-review.start` then runs the ordinary opening writer round. Opening via `/lazy-review.submit` means the content is already written and only needs reviewing: every main writer of the class is recorded in `review_main_done` as already spoken, `review_round` advances by that count, and the phase lands on `awaiting-operator` — the document goes straight to the operator's read without an opening writer round.

**Main rounds.** The pending set is the class's `experts.main` order minus the flat names already in `review_main_done`. A non-blank `review_expert` on the document replaces the class's main list *entirely* for that document. **One main writer at a time, in chain order** — never two at once. When a writer's payload lands: append its flat name to `review_main_done` and bump `review_round`. Once the done-set covers every main writer, the phase becomes `awaiting-operator` and the turn is the operator's.

**Section writers before approve.** A section writer is pending when its owned H1 section is *absent from the body* — a body-presence probe, never a walk of commit trailers. A pre-approve section writer runs only when no main writer is pending and no operator block stands. An operator block is an unanswered `[!question] #review/question`, an unanswered `[!decision-candidate]` (its accept/reject pair untouched), or `[!attention] #review/concern`; a callout counts as answered when a `- [x]` sits inside its own body. Two exceptions, both about not blocking a writer on its own words: a callout inside a writer's own owned section never blocks that writer (it placed the callout and is the only one who can retire it), and a terminal-owned section carrying any `- [x]` anywhere counts as answered wholesale — in a terminal section the tick *is* the answer and the callout is just the reminder of what was asked.

**Both exceptions belong to writer-blocking and nowhere else.** They exist to decide whether a *writer* may speak, and their scope stops there. **The gate that holds finalize open is per-callout, with no carve-outs at all**: every `[!question] #review/question` and every `[!decision-candidate]` in the body — inside a terminal section, inside a writer's own section, anywhere — is unanswered until a `- [x]` sits inside *that callout's own* block, and one unanswered callout blocks finalize. A terminal section that carries a tick somewhere and a second, still-untouched question elsewhere in the same section is answered for writer-gating and unanswered for finalize, simultaneously and correctly. Reading the wholesale rule into the finalize gate finalizes a document past a question the operator never answered — for a request, that closes routing on a choice nobody made.

**An operator commit mid-loop.** On `operator-edit` while the document is not approved and the phase is `main` or `awaiting-operator`, the round re-opens: `review_phase: main`, `review_main_done` back to empty — the writers speak again against the new text. `review_round` is not bumped by this; the bump rides with the next writer's landing. An operator edit is never an error by itself.

**The three gestures, mirrored before the repaint.** Frontmatter is the durable record and the banner is a disposable projection, so the moment a ticked gesture is read it is mirrored with `set-key`, ahead of `paint-banner`:

- `approve the whole document` → `review_approved: true`.
- `approve with concerns` → `review_approved_with_concerns: true`.
- `continue review cycle` → a one-shot signal with no flag of its own: drop `review_approved` back to false, phase `main`, `review_main_done` empty. The validation-round counter is *not* touched by the operator's choice — it belongs to the validator barrier.

**What approve does beyond the flag.** Approving means the operator accepted the document as it stands, so the approve transition also folds the edit markers down — the marked-up text becomes accepted final text, and the writers that fire next review content rather than scaffolding. It drops the resolved validation-owned sections left over from the previous cycle (terminal-owned sections, the operator's prose and `# History` stay). And it enters the first non-empty post-approve phase: `validators` when the class has any, else `terminals`, else neither — a class with no post-approve writers goes straight to finalize.

**The approved branch, in priority order.** On an approved document, walk these and stop at the first that holds:

1. **The operator edited outside every owned section since the approve.** The approval no longer describes the document: drop `review_approved`, phase back to `main`, `review_main_done` empty, and the barrier re-opens from a fresh main round. Highest priority — it supersedes any barrier in flight.
2. **`review_approved_with_concerns` is active.** Finalize, preserving the concerns. The operator explicitly chose this on the pause banner, so the remaining barrier and unanswered-question gates are bypassed rather than re-litigated.
3. **The concerns pause is active.** Nothing happens but the pause banner. Only the operator's tick moves the document.
4. **Barrier writers need dispatch.** Queue them **all at once**, not one at a time.
5. **A barrier writer is still in flight.** Wait.
6. **Every barrier writer has finished.** Collect the whole barrier in one pass: each writer's section lands, then one decision (below).
7. **The barrier is drained but a terminal left an unanswered `[!question]`.** Wait for the operator.
8. **Otherwise** — finalize.

**The two barriers.** All validators speak, then one decision; then all terminals speak, then one decision. This is a barrier, not a per-writer cascade — no validator's output is acted on until every validator of the phase has finished.

**The validator decision**, judged on the collected body:

- **Any validation section holds concerns** → `review_validation_round` increments. The counter is monotonic and never resets over the document's lifetime. Below the class's `concerns_decision_threshold` (default 2, floor 1), revert to main: drop `review_approved`, phase `main`, `review_main_done` empty — and **leave the concern sections in the body**, because the next main round is what reads and answers them. At or above the threshold, stop auto-reverting and hand the choice over: phase `concerns-pause`, the decision banner, and the document waits for the operator to tick continue-or-approve-with-concerns. A class that sets the threshold to 1 pauses on the first concerns round with no auto-revert at all.
- **No concerns** → the terminal phase when the class has terminal writers, otherwise clear the phase; finalize is next.

**The terminal decision**, judged on the collected body:

- **A terminal section is still missing** — its writer produced nothing, or died → **hold**. Never clear a barrier whose terminal writer produced nothing: keep the phase and let the next wake re-dispatch the missing writer.
- **All present, and an unanswered `[!question]` stands** → the operator's turn.
- **All present, no question** → finalize.

**Finalize.** The conditions, all of them: the document is approved (or approved-with-concerns), no barrier work is pending, no unanswered question stands, no approval reset is pending, and bootstrap has happened. Finalize strips the review's ephemeral markup — banner, gesture checkboxes, edit markers, system callouts, owned H1 sections — sets `review_active: false`, and stamps `review_result` with `approved` or `approved-with-concerns`. Terminal-owned sections survive the strip by design: a downstream transition reads the operator's choices there and is responsible for removing the section once its own work is done. Validation-owned sections survive only under approve-with-concerns — and every preserved section keeps its `#expert/<flat>/<id>` ownership tag: a concern the operator chose not to resolve stays attributed to the expert that raised it.

## 4. Job lifecycle

**Dispatch.** Run `mark-job <file> writer <id>` **first**, then call `dispatch-job`. The marker is what makes the job's completion wake the coordinator; a dispatch without it lands silently and the turn is lost. The marker write touches no document and lands no commit, so nothing about it appears in the review's history. The bundle carries its own `protocols:` explicitly — nothing attaches one from inside the coordinator's own job. The list is built the same way on every writer dispatch, from three sources, all read — never invented: `lazycortex-review:lazy-review.doc-review-protocol` (the wire contract, Chapter 8 — the one reference this playbook names itself, because it is this plugin's own), plus everything in `review.protocols` (the section-level default list the install seeds with the markdown canon; a consumer that wants a different canon edits that key, never this playbook), plus whatever the document's own class entry declares under `review.classes[].protocols` — an optional list of plugin-namespaced references a sibling plugin seeds onto its classes (the spec plugin puts its expert-signals protocol there). Omit any of the three sources and the writer works without that contract — silently. Section-writer jobs are keyed by `(document, section)`: one dedup key, one job, however many wakes ask for it. A dispatch under a key that already has a live job is not a second job.

**The dispatch payload.** The `payload` object of the `dispatch-job` bundle becomes the job's `request.json` **verbatim** — the runtime adds only its own `_dedup_key`. The bundle's sibling `source` / `context` fields are lists of **repo-relative paths** into the working tree, and nothing is copied at dispatch: the pump copies each named path into the job's `source/` / `context/` when it claims the job, and a path that no longer resolves at claim fails the job. Content that exists in no file goes in `source_inline` / `context_inline` instead, each entry naming the file it becomes under the same bucket and carrying its text — which is the door a barrier writer's `strip-markup` view takes, while a main writer's source is the reviewed document itself and rides as its plain repo-relative path. `result` is unchanged: a list of filenames created empty at dispatch. Either way the expert finds its input where the table below says it does. Nothing else is filled in for you: a field you leave out is a field the expert never sees and the postman never reads. Field names below are exactly the ones `collect-job` looks for and the doc-review protocol declares.

Every dispatch, whatever its mode, carries:

| Field | Value |
|---|---|
| `_target_file` | Absolute path of the reviewed document. |
| `mode` | `main`, `validation`, `terminal`, or `repair` — the structural mode, from the writer's bucket in the class config. |
| `role` | The free-form role string on that writer's config entry, transported to the agent as its own self-label. |
| `round` | The document's current `review_round`. |
| `source` | `[{"path": "source/<file>"}]` — one entry, naming the file the bundle's own `source` or `source_inline` entry lands under. |
| `context` | `[{"path": "context/<file>"}, …]` — one entry per context file; omit the field entirely when there are none. |
| `result` | `[{"path": "result/<file>"}]` — the empty file the expert writes its output into. |
| `edit_marker_style` | The class's marker style, `review.edit_marker_style` (default `simple`). |

**Decisions-registry context.** Before every main or barrier (`validation` / `terminal`) writer dispatch — never before `doc_doctor`'s repair dispatch — run `Bash(lazycortex-review decisions-context <file>)`. It returns a map keyed by context filename, each value that registry's text: when the reviewed document sits inside a spec asset folder, whichever of `decisions-asset.md` / `decisions-product.md` resolves to an existing registry (a missing `decisions.md` is normal — it is created lazily by the first decision recorded into it — and the verb omits it silently, never a warning); outside a spec asset folder it returns `{}`. Fold every returned key into that dispatch's `context` field above as `{"path": "context/<key>"}`, and the key with its text into the bundle's `context_inline` — the two registries share the basename `decisions.md` on disk, so they take the inline door under their disambiguated names rather than the path bucket, which would land both under one name.

A **section writer** (`mode` `validation` or `terminal`) adds three more, because the payload is the only place the owned section is named: `expert` — the dispatch name of the section-owning writer, **required**; `section_id` — the owned section's id, **required**; `section` — the section's H1 title, optional and derived from `section_id` when absent; `position` — `top` or `bottom`, optional and `bottom` when absent. A **main writer** adds `concerns` instead, and only when at least one validation section currently holds non-empty content (Chapter 3's validator decision).

**`_target_file` is what makes a job collectable, and its absence stalls the document.** Both `collect-job` and the `collect-tick` sweep find a job by reading `request.json` and matching this field against the document's path — there is no other index from document to job. A dispatch that omits it produces a job that runs to `DONE` and is then invisible: the payload never lands, `review_active_job` never clears, no job-done wake is generated, and the turn is lost until an operator command wakes the document by hand.

**`source[0]` for a main writer is the raw document exactly as committed; for a validation / terminal writer it is the markup-resolved view.** There is no dispatcher pre-processing the text beyond that one distinction: a main writer reads whatever the reviewed file holds — banner, `# History`, foreign owned sections, gesture checkboxes, unresolved edit markup — because the markup is its own working material. A validation or terminal writer judges the document's **final state**, so its `source[0]` content is the output of `lazycortex-review strip-markup <file>` — the same document with every edit annotation folded to the text it proposes (the verb degrades to the raw document on an unknown configured style). The protocol's mode rules still say which bytes come *back*, and `reapply` still restores everything outside the mode's footprint, so the expert's obligation is unchanged; only the assumption that it receives a content-only view is gone.

A main-writer dispatch:

```json
{
  "_target_file": "/repo/specs/proposal.md",
  "mode": "main",
  "role": "test-designer",
  "round": 3,
  "source": [{"path": "source/proposal.md"}],
  "result": [{"path": "result/proposal.md"}],
  "edit_marker_style": "simple",
  "concerns": [
    {
      "group": "review_notes",
      "writer": "review.validator",
      "section_h1_title": "Review notes",
      "content": "- The failure path is undefined for a partial write."
    }
  ]
}
```

A section-writer dispatch (`terminal`; a `validation` one is identical but for `mode`):

```json
{
  "_target_file": "/repo/specs/proposal.md",
  "mode": "terminal",
  "role": "router",
  "round": 3,
  "expert": "spec.coordinator",
  "section_id": "routing",
  "section": "Routing",
  "position": "bottom",
  "source": [{"path": "source/proposal.md"}],
  "result": [{"path": "result/routing.md"}],
  "edit_marker_style": "simple"
}
```

**Waiting.** While the `active_job` marker stands and its job is in flight, the turn belongs to that job and the coordinator makes no move on the turn. It still handles everything that is not the turn: an operator gesture, a command callout, an escalation. A command in particular runs on an otherwise stuck document (Chapter 5).

**The postman.** `lazy-review.collect` runs on its own interval and carries no scheduling judgement whatsoever — and it no longer lands or commits anything. For every document with at least one DONE-and-not-yet-consumed job it clears the `active_job` marker, raises the `job-done` pending wake, and dispatches the coordinator directly (no commit exists to carry the wake, so none is needed). The payload is still sitting in the job queue when the wake arrives: **the first move of a job-done wake is `collect-job <file> --no-commit`**, which applies every finished payload to the working tree and consumes the jobs — then the wake's settle writes go on top and `commit-doc` lands payload and settle as one commit. A coordinator still busy when the postman sweeps is skipped; the wake stays raised and the jobs stay DONE, so the next sweep retries — a lost coordinator job cannot strand a landing. Reasoning about a document that does not yet contain the work is the failure mode this ordering exists to prevent.

**Continuation on job-done.** Read the completing job's `response.json`, take what the expert produced as fact, and decide the next move by the ladder in Chapter 3 — the next writer in the chain, the barrier that now holds, or a stop to wait on the operator. On an approved document, check the barrier against the job queue before treating the wake as the phase finishing: the cleared marker means one job landed, not that the phase is drained (Chapter 1).

**The stuck marker — non-`edited` outcomes are the coordinator's to decide.** The postman lands `edited` and nothing else. A DONE job reporting `empty` or `error`, and a job that died, are left exactly as found: not landed, not consumed, `active_job` not cleared, no pending wake raised — and therefore **no job-done wake is generated at all**. A wake that reads an `active_job` still standing in `parse-note`'s `job_markers` block while its job sits in a terminal state has inherited that decision: re-dispatch the same turn, escalate to the operator, or drop the turn and clear the marker. Deciding is not optional — a marker that never clears is a document that never wakes on job-done again. In the retired ladder a dead job silently counted as having spoken and the barrier moved on regardless; that silence is exactly what Chapter 6's escalation replaces.

**The operator wins over an in-flight pass.** If the operator committed to the document after a job was dispatched, that job's output was written against text that no longer exists. Discard the pass — consume the stale jobs so they cannot re-fire, and re-plan against what the operator now says. The anchor for "after" is **the operator's commit sha recorded at dispatch time, never the file's content hash**: the review system's own mechanical commits move the hash without any operator action, and a hash comparison loops forever on them.

**Selective respawn.** In the terminal phase, when an operator commit touched one terminal's owned section, re-dispatch only that terminal. The phase stays `terminals`; the validator barrier does not re-open for it.

**Cancelling.** A turn overtaken by an operator edit or an answer is cancelled with `cancel-job`, and the `active_job` marker is cleared with `mark-job <file> writer --clear` in the same wake.

## 5. The command callout

`> [!todo] #review/command` is the operator's free-text channel into the loop. It is deliberately **not** a checkbox — `- [ ]` is reserved for an ask-the-operator gesture, and a command is the reverse: the operator telling the coordinator to act. It is deliberately not inside the banner either: the banner is repainted by the system and any operator text there is destroyed on the next repaint, while a separate callout survives every repaint.

**A pending command runs on EVERY wake, first.** Whatever trigger woke you, `parse-note`'s report is in front of you — if it shows a non-empty command callout, execute (or resume) it before any other business of the wake. The trigger names why you woke, not the only thing you may see; an operator who commits a command alongside answers or edits has given an instruction, and an instruction outranks your routine reaction to the same commit. Deferring a visible command to some future `command`-labeled wake is the failure mode, not a discipline.

**Unfolding into a mini-plan.** On waking to a command, expand it into a numbered mini-plan written into the **same callout**, so the operator sees the plan before execution starts and can intervene between steps. Progress is a prefix mark at the start of each line — unicode symbols, never markdown checkboxes, which would be read as gestures: `✓` done, `→` in progress, `·` not started.

**Memory of the command.** The mini-plan is the only memory needed. Every later wake on this document re-reads the same block and resumes from wherever the marks left off; there is no separate state.

**Mid-command failure.** A step failing partway stops the whole chain — no continuation past a failed step. Lock the block with an outcome line naming where it stopped: `reached step N, failed at <what failed>`.

**Completion.** Once every step reads `✓`, or the chain locked on a failure, the whole block — plan, marks, outcome — moves as one unit into `# History` and the callout is removed, leaving the channel empty again.

**A command runs on a stuck document.** Whatever else is true — a turn in flight, a barrier held, a job whose marker never cleared — the command is an operator gesture aimed deliberately at this document, and it is how the operator directs recovery. It is also the operator's manual wake: a trigger that was lost to a detection edge is recovered by dropping a command in. Never blocked.

## 6. Escalation and repair

Three kinds of breakage, and they are handled differently:

- **Mechanical** — an unclosed code fence, a deleted frontmatter `---`, edit-markup left open, an ownership tag mangled into unparseable text. Dispatch `doc_doctor` and wait for it. The operator is not involved.
- **Repairable but uncertain** — a key the schema does not know (usually a typo, always a signal), a value outside the closed set a key allows, a mistyped `#expert/<name>/<section-id>` tag that silently turned an owned section into ordinary prose, a state that parses cleanly and still contradicts itself. Do not guess: write a `[!question]` with concrete `- [ ]` options and stop on the document until the operator ticks one.
- **Not the coordinator's decision** — anything about the document's content, whether a round should count as closed, what an operator edit means when it conflicts with an expert's work in flight. Same route: a question with options.

**A silent skip is forbidden in all three cases.** A document never falls out of the loop without a trace. False confidence costs the operator content they then have to reconstruct; an unnecessary question costs one cycle.

**The mechanical-attempt budget is judgement, not a counter.** The retired ladder carried a `repair_attempts_remaining` counter that was re-initialised to 3 on every tick and never decremented — its exhaustion branch was unreachable, and the real behaviour was `doc_doctor` re-dispatched forever with no escalation and no broken mark. There is no counter now, and none is wanted. The coordinator judges when mechanical repair is exhausted: the same failure returning unchanged, a second repair reproducing the first one's output, or the doctor itself declaring the file irreparable. **One repair attempt that changes nothing is evidence; two are a decision** — escalate with a question naming what is broken and what the options are.

**Asking well.** Every question carries concrete `- [ ]` options — never an open-ended prompt. Never invent a confirmation for something the rule layers already settle, and never re-ask a question they settled once. Always remove the answered block once its branch is applied, recording the chosen option in `# History`: a ticked block left standing re-reads as an unprocessed answer on every later wake.

## 7. History

`# History` is one line per **approved state** of the document, written inline by the coordinator in the same wake that reaches that state. There is no historian job and no historian gate on finalize — the entry cannot land in an already-closed document because it is written before the transition that closes it.

**The section is bootstrapped, tagged, and terminal.** The entry verb (`start` / `submit`) creates the empty section at the end of the body with `#protected/review/history` as its first content line, followed by an asterisk-italic explainer line (`*...*`, in the vault's language) — the section's self-description for the operator, owned by the entry verb, never one of the coordinator's lines. That tag is the section's identity (recognition is tag-based, never title-based) and marks it persistent under the cross-plugin protected-section contract — it survives every pass, finalize included. The coordinator appends its lines below the explainer, never creates a second `# History`, never removes the tag or the explainer, and the section stays the document's last H1: bottom-positioned validation sections insert before it.

**What the line says.** What the document now says that it did not say before, or what it no longer says. Content, in the document's own language and register.

**What it never says.** Who changed it. That a review happened. Which round it was. Which expert spoke. Any part of the process is out — the process is not what the reader of a finished document came for.

**Shape.** One sentence. When several unrelated things changed in the same approved state, name the most significant and mention the rest by count rather than listing them.

**Deriving it.** The coordinator has Bash: the diff between the previous approved state's commit and the current one is the input, and the `# History` lines already present say what has been claimed before, so a new line does not repeat one. Reading the document is not optional here — a line written from the diff's mechanics alone narrates edits, which is the process, not the content.

**The one block that is not a line.** A finished command block moves into `# History` whole (Chapter 5). It is a record of an operator instruction and its outcome, not a review round, and it is the only exception to the one-line form.

## 8. Wire formats (pointer)

This playbook owns the coordinator's reasoning. It does not own a single shape, and where it appears to describe one, the sources below win:

- **`${CLAUDE_PLUGIN_ROOT}/references/lazy-review.doc-review-protocol.md`** — the expert wire contract: what a dispatch writes into `request.json`, what an expert writes into `response.json`, the `source/` / `context/` / `result/` layout, the section-ownership tags, the edit-marker styles, and the closed `outcome` set. Every expert dispatch names it.
- **`lazy-core.markdown-style.md`** (lazycortex-core) — the shapes of the review's callouts: `[!question] #review/question` with its `- [ ]` options, `[!attention] #review/concern`, `[!todo] #review/command` with its mini-plan marks, and the banner's `#review/<state>` forms. The `#review/*` set is **closed**; a callout outside it is an audit failure, not a variation.
- **The verbs' own JSON output is their contract.** `parse-note`'s report defines what can be read; `set-key`'s refusal defines what may be written; `paint-banner` defines what the banner looks like in every state. The coordinator never hand-renders markup a verb owns, and never infers a shape from this document that a verb would have produced differently.

On a genuine disagreement: this playbook wins on what to DO, the protocol and the style doc win on what a shape LOOKS LIKE, and a verb's actual behaviour wins over any description of it, here or anywhere else.

## 9. Cycling — recognising a loop before the daemon does

Long autonomous stretches are legitimate: a document may travel many writer rounds, and the daemon's own loop detector halts only on literally repeated identical diffs. Semantic cycling — motion without progress — is YOURS to catch, because only you can compare intentions. Check on every wake, before acting; the inputs are already in front of you (frontmatter counters, the fixture's git log, your previous closing commits and their subjects).

The signals, each sufficient on its own:

- **Same dispatch, unchanged cause.** The writer you are about to dispatch is the one you dispatched on your previous wake for this document, AND the condition that justified it (the unanswered-question set, the section state) is byte-unchanged since then. A writer that ran and changed nothing will not change anything the second time.
- **Validation ping-pong.** `review_validation_round` has bumped twice with the validator raising a finding materially identical to the one the writer already addressed — the writer and the validator are disagreeing at each other, not converging.
- **Your own echo.** Your intended action equals your previous wake's action (same verbs, same keys, same target) and no operator commit and no new expert payload landed between the two wakes. A wake with no new input must not repeat the old output.

On any signal: do NOT act the repeat. Write a `[!question]` callout naming the repetition concretely — which action, how many times, what failed to change — with `- [ ]` options for the operator (retry once more / change the input yourself / take the document out of review). Then repaint the banner (`Action needed`) and commit — the coordinator-job marker is the watch worker's to clear once this job goes terminal, not yours. One document pauses on the operator's doorstep; the daemon and every other document keep running. Never resolve a suspected cycle by trying harder — the third identical attempt costs the operator more than the question does.

The daemon's patch-id loop detector remains the incorruptible backstop BENEATH you: if your own judgment is what's broken (a corrupted wake repeating identical commits), the daemon halts on the repeated diffs you leave behind. You aim to make that backstop permanently bored.
