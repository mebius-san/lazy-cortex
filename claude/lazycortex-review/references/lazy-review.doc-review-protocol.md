---
name: lazy-review.doc-review-protocol
version: 8
routine_protocol_candidate: true
description: Markdown-document review protocol for lazycortex-review — minimal request/response contract for jobs dispatched to experts via lazycortex-core's expert runtime queue.
---
# doc-review protocol v8

Canonical contract for jobs dispatched to experts by the ``lazycortex-review`` dispatcher (or any other consumer producing doc-review-shaped jobs). The dispatcher enforces ownership-isolation in code (``reapply.py`` + ``body.py``); the agent does NOT need to self-police section boundaries — those are restored by reapply byte-for-byte. The dispatcher classifies each dispatch into a structural ``mode`` (see § Mode rules) that determines what bytes the dispatcher will accept back. Consumer-side state machine, banner vocabulary, finalize behavior, and approve-gesture flow are out of scope for this wire contract — they belong to the consumer that drives the dispatcher.

## Request shape (``request.json``)

```json
{
  "mode":                  "main | validation | terminal | repair",
  "role":                  "<free-form string from expert config>",
  "round":                 1,
  "source":                [{"path": "source/<file>"}],
  "context":               [{"path": "context/<file>"}, ...],
  "result":                [{"path": "result/<file>"}],
  "edit_marker_style":     "simple | diff | criticmarkup | html",
  "concerns": [
    {
      "group":            "<section-id>",
      "writer":           "<expert-name>",
      "section_h1_title": "<H1 title>",
      "content":          "<markdown body, ownership tag stripped>"
    }
  ]
}
```

Field notes:

- ``mode`` — closed enum, derived structurally by the dispatcher from the expert's bucket in config. The protocol's per-mode rules (§ Mode rules) describe what bytes the dispatcher will accept back from each mode. Independent of ``role``: two experts in the same bucket share a mode but may carry different roles.
- ``role`` — free-form string transported from the expert's config to the agent verbatim; the consumer plugin's class-configuration skill (``lazy-review.configure``) is the authoritative source of this value. The protocol does NOT enumerate values or assign semantics; the agent treats it as its own self-label and may branch on it (or ignore it). Ownership / IO contract is keyed on ``mode``, not ``role``.
- ``source[0].path`` — relative to the job dir, points at the document the expert reads. For ``mode=main`` it is the **raw document exactly as committed** — banner, ``# History``, foreign tagged H1 sections, gesture checkboxes, and unresolved edit markup all included; nothing pre-strips it on the way in. For ``mode=validation`` / ``mode=terminal`` the dispatching consumer supplies the **markup-resolved view** (every edit annotation folded to the text it proposes) — those experts judge the document's final state. What comes back is still bounded by § Mode rules, and everything outside the mode's footprint is restored from the operator's prior state on reapply.
- ``context[0..N].path`` — auxiliary files (e.g. a prior revision, or a related document the class declares as context). A consumer MAY stage additional materials here beyond what this protocol enumerates; the expert MUST read every file present, not only the ones this protocol names.
- ``result[0].path`` — relative to the job dir, points at the empty file the expert writes to when ``outcome=edited``. Writer modes (``main`` / ``validation`` / ``terminal`` / ``repair``) return body content this way.
- ``edit_marker_style`` — names which annotation style is attached to the job. The agent reads this value and locates the matching block of marker rules in the ``lazy-core.markdown-style`` protocol attached to the job's ``config.json`` (one source of truth for marker shape — no per-style template duplicated in the payload).
- ``concerns`` — present only on ``mode=main`` dispatches AND only when at least one ``mode=validation`` section currently holds non-empty content. Each entry names one validation H1 section and carries its body (heading + ownership tag stripped). The main writer cannot edit the validation section content directly (the dispatcher restores it byte-for-byte on reapply); the field exists so the main writer's agent body has access to what the validator said.

## Response shape (``response.json``)

The response envelope — ``outcome`` / ``result`` / ``error`` — is owned by ``lazy-core.expert-runtime-contract``; read it alongside this protocol. This protocol adds ``history_entry`` on top of it (see § ``history_entry`` shape) and declares its own values:

- ``outcome`` — ``edited | empty | error`` for a review-kind dispatch (``mode`` one of ``main`` / ``validation`` / ``terminal``); ``edited | error`` for a repair-kind dispatch (``mode == "repair"`` — a repair produces a parseable file or fails, there is no partial-progress ``empty``).
- ``error.category`` — ``logical`` (the input was invalid), ``transient`` (a queue or Claude-process crash), ``technical`` (a schema violation), or ``broken`` (repair-specific — see `mode == "repair"`). ``broken`` is reserved for ``mode == "repair"``; the other three apply to every mode.

For ``outcome: "edited"``, every writer mode (``main`` / ``validation`` / ``terminal`` / ``repair``) returns body content via ``result/<file>`` per its own footprint (see § Mode rules); ``mode=validation`` and ``mode=terminal`` write only the markdown body of the owned section — **no H1 heading, no leading tag line** — the dispatcher emits those itself. A result file MAY open with an optional YAML frontmatter fence (``---\\n<keys>\\n---``); the dispatcher applies the fence's keys as an overlay onto the document's frontmatter (reserved keys — see § Frontmatter reserved keys — and ``tags`` are filtered out) and treats the remainder as the body. A result file without a fence is body-only — back-compat for sections that have no frontmatter updates this round.

## Mode rules

The dispatcher enforces ownership in code (`reapply.py` + `body.py`) keyed on the structural `mode` field. Each mode defines what bytes the dispatcher will read back from `result/<file>`, where they land, AND what content shape is expected inside those bytes — agent output outside the mode's footprint is silently dropped on reapply.

Agent-side persona / lens / phrasing live in the agent's own `.md` definition where one owns the mode; for the config-filled validation and terminal modes, the role-level lens in their own sections below is the shared baseline. Consumers wiring an expert into a mode are responsible for picking an agent whose behaviour matches the mode's contract.

### mode == "main"

Dispatcher reads the full document body from `result/<file>` and grafts it back excluding tagged H1 sections, `# History`, banner, status callout, and approve checkbox (those are restored byte-for-byte from the operator's prior state). The document's first-level heading (the `# <title>` line — the document identity) is likewise restored from the operator's prior state when the writer omits it — a defensive guard, not a licence to drop it (Bug 105). Frontmatter overlay applied except for reserved keys (see § Frontmatter reserved keys). Receives `concerns` when at least one `mode=validation` section is non-empty.

The main writer owns the body's free prose. It rewrites paragraphs to address validator concerns, restates each concern as an operator question with answer options, and folds answered questions into the surrounding prose once resolved. Free prose, operator questions with answer options, and non-system commentary are the allowed shapes — the dispatcher-owned state blocks (the banner and its variants) are not authored by the main writer. The document's first-level heading (`# <title>`) is identity, not editable prose: the main writer MUST return it verbatim as the body's first line and never drop or rename it (dropping it strands downstream banner placement — Bug 105).

**Operator-question invariant (MANDATORY for every operator question the writer emits, this mode and any other).** A question to the operator MUST carry answer options, or the dispatcher never sees the answer — ticking an option is the only answer signal a consumer can detect. When the writer wants free-form clarification instead, it writes the prompt as plain body prose, not as a question block.

**An answered question is a settled decision (MANDATORY).** A callout carrying a ticked option is the operator's decision: the writer folds it into the surrounding prose in the SAME round and removes the callout. Re-asking the same question — in any rewording, with refined options, split into sub-cases — is a round defect, not diligence; a new question is legitimate only for a genuinely new gap the fold uncovered. When the ticked answer seems ambiguous or underspecified, the writer folds the literal choice as given and marks the residual call it had to make as a `[!decision-candidate]` — never by handing the operator the same fork twice.

### mode == "validation"

Dispatcher reads the section body from `result/<file>` and grafts it into the H1 section the writer owns. Dispatcher emits the H1 heading and ownership tag itself; the agent never authors them, and any leading H1 / tag line inside the result file is stripped on reapply. No frontmatter overlay accepted from this mode.

The validator does not talk to the operator. Its job is to deliver a **verdict** on the document — name the problems, the contradictions, and the information missing for further work to proceed. Output is the verdict itself: a list of concrete findings, each one short, declarative, and self-contained. The next consumer of this section is the `mode=main` writer (another expert, not a human) — it reads the validator's verdict via the `concerns` payload field and decides what to surface to the operator.

Plain text is the medium: no operator-facing block belongs inside a validator's section body. Callouts are operator-facing markdown; here there is no operator to render for. Findings go as bullet points or short paragraphs.

### mode == "terminal"

Dispatcher reads the section body from `result/<file>` and grafts it into the H1 section the writer owns. Dispatcher emits the H1 heading and ownership tag itself; the agent never authors them, and any leading H1 / tag line inside the result file is stripped on reapply. No frontmatter overlay accepted from this mode.

A terminal writer produces operator-facing content that **survives finalize**: the section is part of the finished document because a downstream consumer (typically an apply-gate routine that fires after the review closes) needs to read what the operator decided. Typical terminal outputs are routing choices, classification verdicts, domain decisions the consumer plugin will act on.

The writer addresses the operator directly. Each open decision should be expressed as an operator question with answer options, alongside prose that explains context. Free prose and non-system commentary are also fine; the dispatcher-owned state blocks are not authored here. The operator-question invariant from `mode == "main"` applies here too.

Ready text is the medium: terminal writers emit the section content as the **settled final form** of the decision, with **no edit-marker fences** (`diff`, `criticmarkup`, `html`) wrapping in-section mutations. Each round either replaces the section's authoritative content with a new settled version, leaves it unchanged, or empties it — the terminal writer is stating a decision, not iterating on prior prose. The dispatch's `edit_marker_style` field governs `mode=main` body-prose refinement and does not apply to this mode (see § Edit-marker persistence across rounds). Downstream consumers parse the section's ready text directly; diff fences here would force every consumer (apply gates, audits) to disambiguate proposed-vs-settled lines — exactly what the ready-text rule eliminates.

### mode == "repair"

Dispatcher reads the full file body from `result/<file>` and writes it back byte-for-byte (no reapply, no graft; this is a structural-fix mode).

## Edit-marker persistence across rounds

The dispatch's ``edit_marker_style`` field names a marker shape from ``lazy-core.markdown-style`` (``simple`` / ``diff`` / ``criticmarkup`` / ``html``). That shape governs how the ``mode=main`` writer renders body-prose mutations THIS round. ``mode=validation`` and ``mode=terminal`` are plain-text / ready-text modes per their respective sections above and do NOT emit edit markers regardless of ``edit_marker_style``.

Across rounds the invariant is: **every marker emitted by the main writer in any prior round MUST be returned to ``result/<file>`` verbatim**. A main writer NEVER resolves (collapses, folds, applies) a marker on its own initiative — not its own from this round, not its own from a prior round. Markers accumulate in the document body across the entire pre-approve review cycle; only the consumer's finalize step (run after the operator approves) folds every marker of the configured style into final prose.

The invariant holds regardless of:

- **Round age.** A prior-round marker is document state — the current main writer treats the body it receives as the source of truth and preserves every marker it finds.
- **Apparent staleness.** A marker sitting unchanged across several operator commits is NOT an implicit acceptance. The operator's silence is the operator's choice; the marker persists until the operator either modifies it (see below) or the document reaches finalize.

The operator REJECTS or REVISES a prior-round marker by editing the document directly, and a later writer round may replace prior-round prose the same way (see ``lazy-core.markdown-style`` § Revising or retiring a marker across rounds and § Cross-fence ``+`` / ``-`` cancellation for the concrete per-style shape). A writer that "tidies" old markers by silently collapsing them is a protocol violation regardless of how clean the resulting prose reads.

## When ``concerns`` is populated

``concerns`` appears on ``mode=main`` dispatches only, and only when at least one ``mode=validation`` H1 section currently holds non-empty content. Each entry names one such section and carries its body (heading + ownership tag stripped). The field exists so the main-mode agent has read access to validator-authored content despite ownership-isolation preventing cross-section edits; how the agent uses the data is agent-side. How the consumer state machine decides when validation sections fire, when to auto-revert, and when to pause for an operator decision is out of scope for this wire contract.

## ``history_entry`` shape

For ``kind=review`` with ``outcome=edited``, the response MUST carry ``history_entry``: one declarative past-tense sentence, 80–200 characters, **naming WHAT is now in the document** (sections added/removed, prose rewritten, callouts appeared/disappeared) — strictly substantive content describing the document as an artefact, never the process that changed it. **Name the change, not the conclusion** — "A rollback paragraph appeared under Failure-path", NOT "Made the failure-path handling clearer".

Exhaustive forbidden-vocabulary list (shared by every expert that emits a ``history_entry``):

- **No ``#`` tag syntax** — no ``#``-prefixed marker of any kind.
- **No actor names** — ``operator``, ``writer``, ``main writer``, ``section writer``, ``final writer``, ``test-designer``, ``specialist``, ``expert``, ``historian``, or any expert-group name (``main`` / ``<section>`` / ``final`` / ``history``).
- **No process verbs that imply an actor** — ``answered``, ``folded``, ``lifted``, ``approved``, ``ticked``, ``reviewed``, ``raised a concern``.
- **No review-machinery vocabulary** — ``status callout``, ``banner``, ``above the title``, ``# History`` / ``History section`` / ``history entry``, ``review round`` / ``round N`` / ``first/next round``, frontmatter fields (``review_active`` / ``review_round`` / ``review_approved`` / ``approved``), lifecycle verbs about the review itself (``open review``, ``close review``, ``review cycle``, ``approve checkbox``).
- **Writer-authored blocks ARE content** — the appearance or disappearance of an operator question or an open concern is a content change; narrate it in content terms ("Four open questions about export scope appeared"), never as actor action.

**Noise vs content.** The only noise is whitespace-only changes and the dispatcher-owned state block at the top of body, whichever of its states is showing — the dispatcher pre-strips it from both revisions before the expert sees them. An expert whose edit leaves nothing but noise returns ``outcome=empty`` rather than inventing a sentence about it.

The sentence is the expert's account of its own edit. Whether and how the consumer lands it under ``# History`` — the heading shape, the ordering, who writes the section — is consumer policy, out of scope for this wire contract.

## Side-effect rules

- Expert MUST NOT touch any file outside its job dir.
- Expert writes ONLY into ``result/`` (paths declared in the response's ``result`` array).

## Frontmatter reserved keys

The following frontmatter keys are managed by the dispatcher and cannot be written by agent overlays via the reassembly pipeline:

- ``review_active`` — `true` while the document is in the review cycle.
- ``review_round`` — current round number, monotonic per main-writer commit.
- ``review_approved`` — `true` once the operator approved.
- ``review_validation_round`` — count of validation rounds since opening.
- ``review_approved_with_concerns`` — `true` if the operator chose to finalize with outstanding concerns.
- ``review_result`` — terminal discriminator stamped by finalize as the LAST step (``approved`` | ``approved-with-concerns``). All other ``review_*`` keys are stripped at finalize; ``review_result`` is the single key that survives and signals downstream md-scan routines (e.g. consumer apply-gates) that the review has closed. Cleared by the open transition when a doc re-enters the review loop.

Agent-supplied values for these keys are silently dropped on reassembly. Every other frontmatter key is fair game for the agent's overlay.
