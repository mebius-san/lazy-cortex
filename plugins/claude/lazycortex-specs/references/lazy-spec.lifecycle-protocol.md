---
name: lazy-spec.lifecycle-protocol
version: 6
description: Asset progression contract — the recorded `spec_asset_type` fact and the flat gates on the status folder-note (the six S0..S6 gates on a release note, `spec_design_done` / `spec_released` / `spec_cancelled` on a design-only one), the halt reasons and the attach-drop summary; per-file spec_stage, level gates, the launch-checkbox ladder and the change cascade live in the sibling `lazy-spec.doc-stage-protocol` / `lazy-spec.level-gates-protocol` / `lazy-spec.launch-checkbox-protocol` / `lazy-spec.change-cascade-protocol`, each under a stub here. The WORKFLOW layer (what closes a gate, which checkbox exists, what a label dispatches, how a cascade is ordered) belongs to the type playbooks, applied by `spec.coordinator` — this protocol documents the wire shapes and the primitives still living in code, never a workflow rule and never a script-side decision.
---
# Asset lifecycle protocol — per-file stages and gates

Asset progression is tracked at two levels that feed each other:

- **Per-file `spec_stage`** on every authored doc — author-level state of `use-cases.md` / `design.md` / `ui-design.md` / `test-plan.md` / `bug.md`, a release's `code-plan.md` / `test-plan.md`, product-level `tech.md` / `design.md` / `architecture.md`. Closed set: `empty | draft | approved | rejected | cancelled | deferred`. The append-only report journals of a release (`code-report.md` / `test-report.md`), and the opt-in `decisions.md` registry, carry no `spec_stage` — they sit outside this whole layer (see `lazy-spec.doc-stage-protocol.md` § Applies to).
- **Flat gates** on the status folder-note — the asset's overall progress: a design-only note (every type but `release`) carries `spec_design_done`, `spec_released` and `spec_cancelled`; a `release` note carries the six ladder gates through `S0..S6` (Part 2).

**Who decides, who executes.** `spec.coordinator` (agent + expert record; its law is `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`) is the SOLE judge of every sequencing decision this protocol used to hardcode — which sibling doc to promote, which gate's precondition currently holds, which launch checkbox to hang or dispatch, whether and how a change cascades. It acts only through a small set of primitives that remain script-level and unconditional on call: `lazy-spec.set-stage` (per-file stage), `lazy-spec.flip-gate` (gate booleans — refuses a gate off the note's ladder and any flip on a cancelled asset, no sequencing precondition of its own), `lazy-spec.gate-tick`'s worker (a pure poller now, no decisions), and the `note-set-key` / `note-check` verbs (`${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.audit/SKILL.md`'s sibling primitives, documented in `${CLAUDE_PLUGIN_ROOT}/bin/note_ops.py`). Anything below that reads like a rule the SYSTEM enforces is, since the coordinator's arrival, a rule the COORDINATOR follows, declared by the asset's type playbook (`asset_types.<name>.playbook`) — marked "playbook, not code" wherever the distinction matters. The shapes (frontmatter keys, callout formats, the launch-marker record) are still exact contracts; the workflow that decides when to apply them lives in the playbooks, never here.

## Part 1 — Per-file `spec_stage` (authored docs)

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.doc-stage-protocol.md`** for the per-file stage layer: the `spec_stage` frontmatter and its `spec/<stage>` mirror tag, the closed six-value set (`empty | draft | approved | rejected | cancelled | deferred`), which document types carry a stage (§ Applies to), the mapping to lazycortex-review flags, the transitions (§ Transitions — the asset cancel and un-cancel, parking, the one downward `Rebuild` move), and `lazy-spec.set-stage` as the single mutator (§ The single mutator), through which the coordinator's stage promotion also runs.

## Part 2 — Gates (asset progression)

### Frontmatter

The status folder-note carries the asset's recorded type, its gate booleans, and one overlay flag. Every type but `release` is design-only and carries two gates:

```yaml
spec_asset_type: feature                       # the asset's type; `unknown` is the sentinel, never a guess
spec_design_done: false
spec_released: false
spec_cancelled: false
spec_state: draft                              # derived; the coordinator's, read by the iconize registry
```

A `release` note carries all six, `spec_design_done` true from creation, plus `spec_version` and `spec_includes` (`lazy-spec.status-note-protocol.md` Part 4), the build record the coordinator writes through `note-set-key` — `spec_build`, `spec_build_at`, `spec_impl_build`, `spec_impl_build_at`, `spec_test_dispatched_at`, `spec_build_job`, `spec_test_job`, `spec_rebuild_owed` (`lazy-spec.release-type.md`, "The build"), every moment ISO 8601 UTC `YYYY-MM-DDTHH:MM:SSZ` — and `spec_version_pinned`, which `release-version --set` writes. The four middle keys — `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_built` — are absent from every other note, and `lazy-spec.flip-gate` refuses to turn one on there.

There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, and no `## Workflow` section — these keys are the entire model.

**`spec_state` is derived, not recorded.** It is the one key here no gate or row reasons with: the coordinator writes it on the same wake that rebuilds `# Status brief`, and it has two consumers — the iconize registry, which paints the asset folder from it, and the container counters `summary_render` writes on a product or group folder-note (`lazy-spec.layout-protocol.md`, "The container tallies read `spec_state`"). Besides the coordinator, three writers paint it in their own commits: `release-scaffold` paints the members it includes `in-release`, `release-publish` paints the members it releases `done` and those it leaves `awaiting-release`, and the cancel and the un-cancel of a release repaint its members `awaiting-release` and `in-release`; each repainted member's `release-member` wake then lets its coordinator write the value again. Legal values are `draft`, `in-review`, `implementation`, `testing`, `deferred`, `waits-operator`, `awaiting-release`, `in-release`, `done` (`spec_keys.py::AssetState`); `spec_halted` and `spec_cancelled` paint over it from their own keys rather than taking a value of their own. Two of the values are not derivable from this note at all — `in-review` lives as `review_active` on a sibling document, and `implementation` / `testing` track a job in the gitignored runtime sidecar — which is why the key exists instead of a matcher computing the state itself. A plain gate flip never writes it as a side effect.

**`spec_asset_type` is a recorded fact, not an inference.** It names one type declared under `products[<key>].asset_types` (over the shipped defaults in `references/lazy-spec.asset-types.json`), and it is what resolves the asset's type playbook. The sentinel `unknown` — and an absent key, which reads the same — means the type has not been determined yet; nothing downstream guesses it. The asset's FOLDER is a place, not a fact: where the operator filed the thing takes no part in resolving what it is, and a legally-typed asset may sit anywhere in the catalog, nested inside another asset included.

**The asset's boundary is its status folder-note** — the folder whose folder-note carries `spec_role: status`. A nested asset is its own asset with its own status note and its own gates, never a part of the asset it sits inside.

**The note carries no build fact.** Nothing on a status note, and nothing on its asset type, says who builds the asset: `spec_asset_type` chooses the type playbook and the start document only. An asset is part of its product and is built inside the release that ships it, by the product's release implementer with the product's specialists (`lazy-spec.release-type.md`, "The build"); every type but `release` is design-only and runs no build of its own.

**Cross-asset tokens are paths relative to the product's `spec_path`.** A `spec_targets` token (`lazy-spec.change-cascade-protocol.md`) is a path from `spec_path` down to the asset's own folder, so every asset is addressed by its full path from `spec_path`; for an asset sitting at the product root that path is its bare slug, and never a folder it does not actually sit under.

### Linear map S0..S6

The gates are a strict ladder. Each gate requires the one before it to be true:

| State | Meaning | True gates |
|---|---|---|
| S0 | new asset | (none) |
| S1 | design done | `spec_design_done` |
| S2 | plan done | + `spec_plan_done` |
| S3 | develop done | + `spec_develop_done` |
| S4 | tests passing | + `spec_tests_passing` |
| S5 | built | + `spec_built` |
| S6 | released | + `spec_released` |

Only a `release` note walks the whole ladder; a design-only note steps from S1 straight to S6 — its `spec_released` is written by the release that ships it, with the four middle keys absent.

**`spec_released` is the readiness flag.** On every asset status note it alone answers "is this published and ready for a downstream consumer": `true` means published and ready, absent or `false` means not ready. A re-approved start document turns it off (`lazy-spec.coordination-playbook.md` Chapter 4), so the asset stops reading as ready until a release publishes it again. On a release note `spec_built` holds the state "tests pass and the build is merged, not yet published", and `spec_released` means published, exactly as on the assets the release includes. The shape a healthy note's gate state must respect follows from its type, and `lazy-spec.audit`'s precedence check (Part 2-adjacent, its own SKILL.md) flags a later gate true while an earlier one is false on a release note, and a middle key present at all on any other. What changed is who enforces the ORDER of flips at flip time: nobody. `lazy-spec.flip-gate` flips whichever gate it is called on, unconditionally, and trusts the coordinator's own reasoning (below) to have called it in the right order.

### Gate readiness (playbook, not code)

**No readiness rule lives in this file.** What each gate closes on is declared by the asset's own playbooks, and this protocol describes only the mechanism of the booleans and the S0..S6 order above. `spec_design_done` is the type playbook's subject — what the type's defining document is and when it counts as approved is a property of the type, not of the ladder. `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built` exist on a release note only and are the release playbook's: the settled plan, the last implementation build's `code-report.md` entry accepted and its branch merged, the current build's `test-report.md` entry green and accepted; what a build does is the release playbook's, what a test run does the testing stage's (`lazy-spec.test-job.md`). `spec_built` closes on a release once its tests pass and the last implementation build's branch is merged. `spec_released`, on the release and on each member of `spec_includes` the publish releases, is the release's `Publish` tick's write (`release-publish`), together with the version tag — the one freeze point of the ladder; a cancelled member is skipped, and a member whose start document is not `approved`, or whose start document or `ui-design.md` was approved after the release's `spec_impl_build_at`, gets the tag and stays unreleased — a re-approved member whose note reads `spec_design_done: true` is painted `awaiting-release`, every other one keeps the `spec_state` its own coordinator painted; a research asset's closes on its report's approval, and a spec-only product's on the operator's word.

`lazy-spec.flip-gate` reads none of this — it flips the named gate on call, refusing only a gate off the note's ladder (above) and every flip on a cancelled asset regardless of direction but the un-cancel `spec_cancelled --off`. `lazy-spec.audit` still validates the coupling (a gate reading true while the state its playbook names has not been reached is a doctor finding, per its Agent D check); the playbooks are its reference for what "ready" means, exactly as they are the coordinator's.

`spec_cancelled: true` freezes all gates — `lazy-spec.flip-gate` refuses every flip, forward or `--off`, while the asset is cancelled, with one exception: `spec_cancelled --off` itself, the un-cancel. Beside the ladder-shape refusals above, this is the one state the primitive still enforces on its own, because it is the asset's own state, not a sequencing precondition. The cancel, `flip-gate <asset> spec_cancelled`, sets the flag, stops the review of the asset's documents, moves its staged documents to `cancelled`, marking each with the stage it had and stripping its `#status/<state>` callout through the review plugin's `strip-status` verb (no commit) (`lazy-spec.doc-stage-protocol.md` § Transitions), clears the note's `pending_wake`, and cancels the asset's running job last, recording it as `last_job` with `outcome: cancelled`, `unlanded: true` and `retired_by_cancel: true`, in one commit; on a published release and on a release under `releases/archive/` it is refused with nothing written. A cancel refused or crashed after it has killed the job leaves `active_job` null, that job recorded as `last_job` with `outcome: cancelled`, raises `pending_wake: job-done`, and names it as `killed_job` in the result. `spec_cancelled` is written only through this verb (`lazy-spec.coordination-playbook.md` § 4, "A cancel the verb did not make"). An asset cancelled before the cancel took its documents with it keeps them at their old stages; the `cancel-sweep` verb (migration step `010`) applies the cancel to them, the flag left as it is, and goes on past an asset it cannot sweep: an asset the cancel refused is listed under `refused`, its entry carrying the cancel's per-document `refused` list, and the run exits 1; an asset whose sweep failed is listed under `failed` with its error, and the run exits 2. The un-cancel, `flip-gate <asset> spec_cancelled --off`, clears the flag, returns only the marked documents to the stage each had — `empty`, `deferred` and `rejected` as they were, `draft` and `approved` to `draft`, an `approved` one with its review opened at the writer round — resumes only the marked reviews (`lazy-spec.doc-stage-protocol.md` § Transitions), turns off every derived gate whose document it took out of `approved` — on a release, a `code-plan.md` taken out of `approved` turns off `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built`, a `test-plan.md` alone `spec_tests_passing` and `spec_built` — and on a release sets `spec_rebuild_owed` only for the job this cancel retired — a `last_job` carrying `retired_by_cancel: true` and `unlanded: true` whose `job_id` equals the release's `spec_build_job` or `spec_test_job` — and drops that stamp; an earlier unlanded failure (a refused landing, a dead job) carries no stamp and keeps waiting for the operator's `Rebuild` tick, in one commit, then wakes the asset's own coordinator — on a release, only while no other release of the same owner is open and the release is not under `releases/archive/`, else it is refused with nothing written; the asset then follows its normal path. An operator or the coordinator invoking `--off` on any other gate by hand needs no precondition — turning a gate off has never needed one — but is still refused while cancelled.

### Derived vs human-signal gates — vocabulary, not enforcement

Each gate is still one of two kinds, a distinction the coordinator's own reasoning (and `lazy-spec.audit`) still uses, even though no script branches on it anymore:

- **Derived** = `{spec_design_done, spec_plan_done, spec_develop_done, spec_tests_passing, spec_built}`. Readiness is derivable from state the coordinator reads — document stages, a report entry's review verdict against the release's build keys, a merged branch — so the coordinator flips each with `flip-gate --auto` the moment the playbook's own condition holds and with `--off --auto` the moment it stops holding, no operator input needed.
- **Human-signal** = `{spec_released}`. Readiness needs the operator's `Publish` tick; `spec_released`, on the release and on each member of `spec_includes` the publish releases, is `release-publish`'s own write.

### The single mutation channel — `lazy-spec.flip-gate`

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`bin/flip_gate.py` (driven by the `/lazy-spec.flip-gate` skill, and called directly by `spec.coordinator` through the `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> flip-gate` CLI verb) is the **only** writer of gate booleans. The flip is unconditional on call:

1. Reads the folder-note frontmatter.
2. Refuses, before anything is written, an unknown gate name, a gate off the note's own `spec_role` ladder (`lazy-spec.level-gates-protocol.md`), a middle gate turned on anywhere but a `release` note, and every flip while the asset is cancelled (`spec_cancelled: true`) except the un-cancel `spec_cancelled --off` — no sequencing precondition check.
3. Rewrites the gate boolean in frontmatter.
4. Writes `spec_<gate>_at` (an unquoted ISO 8601 UTC datetime) beside a gate turning true and removes it when the gate turns false. Nothing is written to `# Gates` or `# History`; the reason (`--reason`, prefixed `auto:` under `--auto`) is recorded in the run log only.
5. **Atomic git commit of the folder-note edit** under `lazy-spec.flip-gate@bot.invalid` (subject `lazy-spec.flip-gate: <gate> → <true|false> on <asset>`). Without this commit the daemon's next iteration trips its dirty-tree-skip guard and silently halts every routine on the asset. Defensive skip when the asset is not inside a git repository (test-fixture path) — the file write remains but the commit step is no-op.
6. Writes a run log under `.logs/claude/lazy-spec.flip-gate/`.

There is no post-flip cascade anymore — a forward flip of `spec_design_done` does not itself open review on a plan document. Opening that review is now a coordinator decision executed as an ordinary launch-checkbox dispatch (`lazy-spec.launch-checkbox-protocol.md`), ordered by the playbooks, not a side effect wired into the flip primitive.

CLI: `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> flip-gate <asset_dir> <gate> [--off] [--auto] [--reason TEXT]`.

### The `gate-tick` md-scan worker — a pure poller, no decisions

`bin/gate_tick.py` is dispatched per matched status folder-note by the `lazy-spec.gate-tick` `md-scan` routine, same as before. It performs exactly two concerns now, both mechanical:

1. **Active-job polling.** An asset whose runtime sidecar tracks an `active_job` has that job bundle's terminal marker (`DONE` / `DEAD` / `CANCELLED`, read file-wise from the `lazycortex-core` job-runtime layout, never imported cross-plugin) checked before anything else. Every marker clears the tracked job and raises `pending_wake: job-done` in its place — both sidecar writes, so that half costs no commit. `DONE` and `CANCELLED` write nothing into the folder-note: the raised flag is the whole wake, and the `lazy-spec.collect` postman dispatches the coordinator on it directly, with no commit behind it. `DEAD` sets `spec_halted: true`, journals the halt, and appends a persistent `[!failure]` callout to `# Gates` — un-halting is a manual operator act, out of scope for this worker.

**This worker opens no review.** Opening review on any freshly-written document, a job's report included, is a `lazy-review.submit` call made by the coordinator on the `job-done` wake this very pass raises (`lazy-spec.coordination-playbook.md` Chapter 6) — never a follow-up wired into the poller.
2. **Structural note-check.** `note_ops.note_check`'s violations (an unrecognized or mistyped frontmatter key, a missing or misordered required section) are folded into the tick's own result — read-only; repairing what it finds is the coordinator's job, through its pen and `note-set-key`, never this worker's.

Everything this worker used to decide — sibling-doc stage promotion, gate readiness, the launch-checkbox ladder, downward reconciliation, change-cascade dispatch — is gone from this file entirely; it lives in `lazy-spec.coordination-playbook.md`, executed by `spec.coordinator`. A no-op tick (no terminal marker yet, note structurally clean) returns `{"action": "noop"}`.

CLI: `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> gate-tick <asset_note> [--today YYYY-MM-DD]`.

## Part 2b — Level gates (catalog root and product root)

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.level-gates-protocol.md`** for the gates of a level note (`spec_role: catalog` or `product`): the five derived booleans `spec_vision_done` / `spec_use_cases_done` / `spec_design_done` / `spec_ui_design_done` / `spec_tech_done`, each closed by one loose document, with no ladder among them and `spec_halted` as the level's only overlay, and the gate-to-note pairing `lazy-spec.flip-gate` validates on every call.

## Part 3 — Launch checkboxes (operator-triggered dispatch)

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.launch-checkbox-protocol.md`** for the wire shape of the checkbox layer in `# Gates`: the `spec_halted` key and the runtime `active_job` marker, the open label set, the grouped `[!gate]` callout shape, the review-launch block, the fixed dispatch wire (§ Dispatch — `target_doc`, expert resolution, guidelines context, dedup key, guards), the `Publish` freeze point, and the wake hops between notes. Which labels exist and what a tick dispatches stays the playbooks'.

## Part 4 — Change cascade (`spec_targets`)

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.change-cascade-protocol.md`** for the cascade's wire shape: the `spec_targets` / `spec_cascade_done` / `spec_cascade_targets_done` keys on a change asset's status note, the virtual dispatch labels a cascade job rides on, the cascade job's `target_doc` into another asset's folder, and the `MERGE_CONFLICT` halt a reported conflict raises. The order of the cascade's phases is the `change` type playbook's (`lazy-spec.change-type.md`).

## Part 5 — Halt reasons (closed four-item set)

`spec_halted: true` is set exclusively by `flip_gate.halt_asset` / `flip_gate.halt_asset_text` — the single writer, regardless of which component calls it. Every caller passes a `reason` string drawn verbatim from the closed `HaltReason` class in `${CLAUDE_PLUGIN_ROOT}/bin/spec_keys.py`; no caller composes or invents a new phrase. The reason lands byte-for-byte in both the `# Gates` callout (`> [!failure] asset halted: <reason>`) and the `# History` line. Reproduced here exactly as the class defines them, in declaration order:

| # | `HaltReason` member | Phrase (verbatim) | Fired by |
|---|---|---|---|
| 1 | `JOB_DIED` | `job {job_id} ({label}) died` (format template, `job_id`/`label` substituted) | `gate_tick.py` (`apply_job_marker`) — an asset's active job bundle carries a `DEAD` terminal marker. |
| 2 | `MERGE_CONFLICT` | `change delta could not be applied cleanly to the feature docs` | `spec.coordinator`, via `flip-gate --halt` — a change-cascade job reports `conflict: true` (`lazy-spec.change-cascade-protocol.md`; `lazy-spec.expert-signals-protocol.md`) folding its delta into a target doc. |
| 3 | `PLAN_DROP_PARTIAL` | `plan drop left the asset half-cleaned` | `apply_request.py` (`_drop_attached_docs`, Part 6) on an attach drop step failure; `spec.coordinator`, via `flip-gate --halt`, on a cascade's own document-drop failure or a vanished cascade target (`lazy-spec.change-cascade-protocol.md`). |
| 4 | `GATE_PRECEDENCE` | `later gate true while an earlier gate is false` | The operator, by hand — the escalation `lazy-spec.audit` names as the alternative to turning the orphaned later gate back off on a gate-precedence FAIL. |

(The split-repo push-question / import-drift reasons — `DESIGN_DRIFT_ON_PUSH`, `IMPORT_DRIFT`, `NO_PUSH_ACCESS`, `PUSH_UNDELIVERED`, `IMPORTED_EDITED` — were removed with the `push_question.py` / `import_specs.py` channel they served.)

Un-halting (`spec_halted: false`) is always a manual operator edit — no worker ever clears the flag on its own. While `spec_halted: true`, the coordinator's own reasoning hangs no checkbox and dispatches no cascade job (playbook § 1), but the five gate booleans themselves are left exactly as they were — `spec_halted` silences the automation layers built on top of the gates, never the gates.

## Part 6 — Attach drop (a request attaching with documents to drop)

**Conditional chapter — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.attach-drop-playbook.md` when a request's routing resolves to an ATTACH target whose attach line names documents in `drop=`, BEFORE any of them is deleted.** An attach never flips a gate, for any asset type: `spec_design_done` and `spec_released` keep their values — and so do `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built`, which exist on a release note only — and `spec_released` turns off only later, on re-approval of the start document. What `lazy-spec.request-apply` does before seeding the attach delta (`lazy-spec.request-protocol.md` § Body distribution rules, point 2) is delete the documents the attach line's own `drop=` names, so the request does not land on top of in-flight planning work a fresh design change is about to revise. Whether a request attaches at all, rather than spawning a change that names the asset via `targets=`, is the operator's tick on the request's routing `[!question]`; apply never refuses an attach because of implementation signals. The extracted Part carries the unconditional halted- and cancelled-target refusals, and the ordered steps — cancel the active job, stop review, drop the named documents, seed and reopen review through `start` — each with the halt-and-abort rule that governs a failure at that step. An attach with an empty `drop=` deletes nothing and cancels nothing, and this summary is all this Part contributes.

## A narrated example — design approved → a launch checkbox dispatches

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-example.md`** for the end-to-end narration: one asset walked from a review approval through stage promotion, the gate flip, checkbox reconciliation, the operator's tick, dispatch, `job-done`, and the next approve — every link a `spec.coordinator` decision over an unconditional primitive, and every operator arrow a full commit-push-pull round trip. It illustrates the shapes this protocol contracts; nothing normative lives there.
