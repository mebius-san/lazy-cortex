---
description: Attach drop — the halted/cancelled refusals and the ordered steps that delete the documents an attach line's `drop=` names before the attach delta is seeded; an attach never flips a gate. Conditional Part 6 of the asset lifecycle protocol, read when a request's attach line names documents to drop.
---
# Attach drop — conditional chapter of the asset lifecycle protocol

Extracted Part 6 of `lazy-spec.lifecycle-protocol.md`, loaded on demand: read this file when a request's routing resolves to an ATTACH target whose attach line carries a non-empty `drop=` field. Every bare "Part N" cross-reference below names a Part of that protocol.

An attach never rolls an asset back. For every asset type, `lazy-spec.request-apply` leaves the gates exactly as they are — `spec_design_done` and `spec_released` keep their values at attach time. `spec_released` turns off later, and only when the start document is re-approved, which is the coordinator's ordinary reaction to that approval. What an attach does change is the asset's documents: the ones the attach line's `drop=` names are deleted before the attach delta is seeded (`lazy-spec.request-protocol.md` § Body distribution rules, point 2), so the request does not land on top of documents a fresh design change is about to revise.

## Halted- and cancelled-asset refusal

An attach target already carrying `spec_halted: true` refuses the ENTIRE attach outright — automation stays off a halted asset until an operator resolves it by hand, so a halted asset errors rather than losing documents. This is unconditional: an attach with no `drop=` at all, whose only effect would be the seed step, is refused the same way, before any mutation. The same unconditional refusal applies to a `spec_cancelled: true` target, checked first: a cancelled asset would otherwise have its named documents deleted and its review reopened on an asset nothing will ever advance.

## What `drop=` may name

Every `drop=` name is a bare sibling filename in the attached asset's own folder: no path separator (`/` or `\`), no `:`, never `.` or `..` itself, and never empty. Two names are never droppable — the asset's status folder-note and its start document (the type declaration's `start_doc`, the document the attach reopens for review) — and the comparison ignores letter case, since on a case-insensitive filesystem a differently cased name opens the same file. A level document (a product's or the catalog root's system document) is never dropped, so a `drop=` field on an attach line whose target is a level document is refused outright, whatever names it carries.

**Every target is checked before any document is dropped.** Every attach and reference target is resolved, every attach target passes the cancelled and halted refusals above, and every `drop=` name passes the rules of this section, before any job is cancelled or any file deleted on any target. An unresolvable or refused target, an invalid `drop=` name, or a `drop=` on a level-document target aborts the whole run with nothing dropped.

## The drop steps (strict order; a failure anywhere halts and aborts rather than proceeding partially)

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`<review-cli>` stands for the review plugin's `bin/lazycortex-review` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-review/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-review/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <review-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

Steps 1–3 run only when the attach line's `drop=` names at least one document. An attach line with no `drop=` field skips them entirely: no job is cancelled, no review is stopped, every file stays on disk.

1. **Cancel the active job.** When the sidecar tracks an `active_job`, invoke the `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> cancel-job` CLI (resolved via `$LAZYCORTEX_PLUGIN_DIRS`, the § 1c inter-plugin contract). A return that does not confirm the job is dead halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts the whole apply run — deleting documents a job may still be writing is worse than leaving them. On confirmed success, the `active_job` marker is cleared.
2. **Stop review on the dropped documents.** `"${LAZYCORTEX_PYTHON:-python3}" <review-cli> stop` on each named document that exists, best-effort — any failure (CLI crash, timeout) degrades to a silent skip, since the doc is about to be deleted regardless of its review state.
3. **Drop those documents.** Unlink each one from the worktree directly (not `git rm`). A document surviving its own deletion attempt halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts — attributing the request to an asset that is only partly dropped would leave a state nothing downstream can tell apart from a deliberate one. The deleted paths ride into the run's single atomic apply commit, named explicitly by path; on a halt they ride into the halt's commit instead.

**WHICH documents Steps 2–3 touch comes from the CALLER, never from a list this worker holds.** The attach line's own `drop=<name>[,...]` field (`lazy-spec.request-protocol.md` → Routing-block grammar) names them; the router decides what an attach removes, because which documents an asset even has is a property of its type and its tools.

4. **Seed the attach delta and reopen review.** The ordinary attach-seed step runs exactly as it does for any attach target (`lazy-spec.request-protocol.md` § Body distribution rules, point 2), and the primary doc re-enters review through the review CLI's `start` verb — a fresh writer round — whether or not anything was dropped.

Steps 1–3 are the drop's own responsibility; Step 4 is the ordinary attach-seed flow every attach target runs, unchanged by a drop. Whether a request attaches AT ALL — an `attach` onto the asset rather than a change-spawn naming it via `targets=` — is the operator's tick on the request's routing `[!question]` (`lazy-spec.routing-playbook.md`), never a judgment of the coordinator or of the apply worker; the drop itself stays unconditional on its own refusal checks (halted, cancelled, and the `drop=` name rules above) no matter who calls it.

The halt phrases these steps pass — `HaltReason.PLAN_DROP_PARTIAL` above included — are drawn verbatim from the closed set in `lazy-spec.lifecycle-protocol.md` Part 5; no caller composes one.
