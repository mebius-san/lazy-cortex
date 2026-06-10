---
name: lazy-review.doc-review-protocol
version: 6
description: Markdown-document review protocol for lazycortex-review — minimal request/response contract for jobs dispatched to experts via lazycortex-core's expert runtime queue.
---
# doc-review protocol v4

Canonical contract for jobs dispatched to experts by the ``lazycortex-review`` dispatcher (or any other consumer producing doc-review-shaped jobs). The dispatcher enforces ownership-isolation in code (``reapply.py`` + ``body.py``); the agent does NOT need to self-police section boundaries — those are restored by reapply byte-for-byte. The dispatcher classifies each dispatch into a structural ``mode`` (see § Mode rules) that determines what bytes the dispatcher will accept back. Consumer-side state machine, banner vocabulary, finalize behavior, and approve-gesture flow are out of scope for this wire contract — they belong to the consumer that drives the dispatcher.

## Request shape (``request.json``)

```json
{
  "mode":                  "main | validation | terminal | history | repair",
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
- ``role`` — free-form string transported from the expert's config (``review.classes[].experts.<bucket>[<name|section_id>].role``) to the agent verbatim. The protocol does NOT enumerate values or assign semantics; the agent treats it as its own self-label and may branch on it (or ignore it). Ownership / IO contract is keyed on ``mode``, not ``role``.
- ``source[0].path`` — relative to the job dir, points at the stripped document the expert reads. The dispatcher pre-strips protocol metadata (banner, ``# History``, any foreign tagged H1 sections the mode does not own, approve checkbox); the expert sees the content-only view.
- ``context[0..N].path`` — auxiliary files (e.g. the prior revision for the historian).
- ``result[0].path`` — relative to the job dir, points at the empty file the expert writes to when ``outcome=edited``. Writer modes (``main`` / ``validation`` / ``terminal`` / ``repair``) return body content this way. ``mode=history`` returns its entry as ``history_entry`` in the response, never via the file.
- ``edit_marker_style`` — names which annotation style is attached to the job. The agent reads this value and locates the matching block of marker rules in the ``lazy-core.markdown-style`` protocol attached to the job's ``config.json`` (one source of truth for marker shape — no per-style template duplicated in the payload).
- ``concerns`` — present only on ``mode=main`` dispatches AND only when at least one ``mode=validation`` section currently holds non-empty content. Each entry names one validation H1 section and carries its body (heading + ownership tag stripped). The main writer cannot edit the validation section content directly (the dispatcher restores it byte-for-byte on reapply); the field exists so the main writer's agent body has access to what the validator said.

## Response shape (``response.json``)

```json
{
  "outcome":                  "edited | empty | summarized | noop | error",
  "result":                   ["result/<file>"],
  "history_entry":            "<one declarative past-tense sentence>",
  "repaired_history_section": "<historian-only — best-effort History body when orphans detected; absent otherwise>",
  "error":                    {"category": "logical | transient | technical | broken", "message": "..."}
}
```

For ``outcome=edited`` every writer mode (``main`` / ``validation`` / ``terminal`` / ``repair``) returns body content via ``result/<file>``. ``mode=main`` writes the full document body; ``mode=validation`` and ``mode=terminal`` write only the markdown body of the owned section — **no H1 heading, no leading tag line**. The dispatcher emits the H1 and the owner-tag itself; the agent never authors them and cannot get them wrong.

A result file MAY open with an optional YAML frontmatter block (``---\\n<keys>\\n---``). The dispatcher parses the fence off, applies the declared keys as overlay to the document's frontmatter (reserved ``review_*`` keys and ``tags`` are filtered out), and uses the post-fence half as the body. Result files without a fence are parsed as body-only — back-compat for sections that have no frontmatter updates this round.

## Outcome table by kind

| kind     | valid outcomes              |
|----------|-----------------------------|
| review   | edited, empty, error        |
| repair   | edited, error               |
| history  | summarized, noop, error     |

Outcome semantics:

- ``review / edited`` — the expert wrote a new version to ``result[0].path``. The dispatcher reads that file and calls ``reapply`` to graft the edits onto the operator's current state per the dispatch's ``mode`` (see § Mode rules). ``history_entry`` MUST be present (one sentence, content-only — see § History entries).
- ``review / empty`` — the expert had nothing to add this round. The dispatcher writes an empty commit so the chain advances. ``history_entry`` is not required.
- ``repair / edited`` — doc_doctor produced a parseable version of the broken file; the dispatcher copies it back.
- ``repair / error`` (category=broken) — doc_doctor cannot repair; after 3 attempts the dispatcher emits an ``[!error]`` callout and halts the file.
- ``history / summarized`` — historian returns ``history_entry``; the dispatcher mechanically appends it as a new entry under ``# History``. MAY also carry ``repaired_history_section`` when the operator damaged the section (orphan paragraphs not directly preceded by a canonical heading); the dispatcher splices the repair in before appending the new entry.
- ``history / noop`` — operator's last commit only changed protocol metadata; the diff after stripping was empty. No ``history_entry`` is required. The dispatcher records an empty commit with the ``Doc-Review-Phase: history:noop`` trailer so the cycle does not loop.
- ``* / error`` — the expert failed. ``error.category`` routes the consumer's response: ``logical`` (input invalid — surface ``[!error]`` callout); ``transient`` (queue / claude crash — runner retries); ``technical`` (schema violation — log and exit); ``broken`` (repair-specific — see ``repair / error`` above).

## Mode rules

The dispatcher enforces ownership in code (`reapply.py` + `body.py`) keyed on the structural `mode` field. Each mode defines what bytes the dispatcher will read back from `result/<file>`, where they land, AND what content shape is expected inside those bytes — agent output outside the mode's footprint is silently dropped on reapply.

Agent-side persona / lens / phrasing live in the agent's own `.md` definition — the protocol prescribes the **shape footprint** (what content vocabulary belongs in which mode) but not the wording within. Consumers wiring an expert into a mode are responsible for picking an agent whose behaviour matches the mode's contract.

### mode == "main"

Dispatcher reads the full document body from `result/<file>` and grafts it back excluding tagged H1 sections, `# History`, banner, status callout, and approve checkbox (those are restored byte-for-byte from the operator's prior state). The document's first-level heading (the `# <title>` line — the document identity) is likewise restored from the operator's prior state when the writer omits it — a defensive guard, not a licence to drop it (Bug 105). Frontmatter overlay applied except for reserved keys (see § Frontmatter reserved keys). Receives `concerns` when at least one `mode=validation` section is non-empty.

The main writer owns the body's free prose. It rewrites paragraphs to address validator concerns, lifts each concern into a `[!question] ... #review/question` callout with discrete answer options the operator ticks, and folds answered callouts into the surrounding prose. Free prose, `[!question] #review/question` callouts, and `[!note]` / `[!info]` for non-system commentary are the allowed shapes. Other `#review/*` system callouts (banner, action-needed, ready, concerns-decision) are dispatcher-owned — the main writer does not author them. The document's first-level heading (`# <title>`) is identity, not editable prose: the main writer MUST return it verbatim as the body's first line and never drop or rename it (dropping it strands downstream banner placement — Bug 105).

**`[!question]` invariant (MANDATORY for ALL `[!question] #review/question` callouts the writer emits, this mode and any other).** Every `[!question]` callout MUST carry at least one `- [ ] <option>` row inside its body. The dispatcher detects an answered callout exclusively by the presence of a ticked `- [x]` row inside the callout body (see `_strip_answered_callouts` in `bin/dispatcher.py`); an open-ended `[!question]` with no `- [ ]` options has no way to be marked answered and silently blocks the chain forever — the operator's prose addition under the callout is not recognised as an answer signal. When the writer wants free-form clarification rather than a multi-choice tick, it MUST write the prompt as plain body prose (`The X dimension is undefined — please name it.`) instead of a `[!question]` callout. Reserve `[!question]` for prompts where the writer can enumerate concrete answer options; "Other" / "Free-form" options are acceptable when the writer accompanies them with a hint that the operator may edit the option text in place before ticking.

### mode == "validation"

Dispatcher reads the section body from `result/<file>` and grafts it into the H1 section the writer owns. Dispatcher emits the H1 heading and ownership tag itself; the agent never authors them, and any leading H1 / tag line inside the result file is stripped on reapply. No frontmatter overlay accepted from this mode.

The validator does not talk to the operator. Its job is to deliver a **verdict** on the document — name the problems, the contradictions, and the information missing for further work to proceed. Output is the verdict itself: a list of concrete findings, each one short, declarative, and self-contained. The next consumer of this section is the `mode=main` writer (another expert, not a human) — it reads the validator's verdict via the `concerns` payload field and decides what to surface to the operator.

Plain text is the medium: **no callouts of any kind** (`[!question]`, `[!attention]`, `[!note]`, `[!info]` etc.) inside a validator's section body. Callouts are operator-facing markdown; here there is no operator to render for. Findings go as bullet points or short paragraphs.

### mode == "terminal"

Dispatcher reads the section body from `result/<file>` and grafts it into the H1 section the writer owns. Dispatcher emits the H1 heading and ownership tag itself; the agent never authors them, and any leading H1 / tag line inside the result file is stripped on reapply. No frontmatter overlay accepted from this mode.

A terminal writer produces operator-facing content that **survives finalize**: the section is part of the finished document because a downstream consumer (typically an apply-gate routine that fires after the review closes) needs to read what the operator decided. Typical terminal outputs are routing choices, classification verdicts, domain decisions the consumer plugin will act on.

The writer addresses the operator directly. Each open decision should be expressed as a `[!question] ... #review/question` callout with discrete answer options the operator ticks, alongside prose that explains context. Free prose and `[!note]` / `[!info]` callouts are also fine. Other `#review/*` system callouts (banner, action-needed, ready, concerns-decision) are dispatcher-owned and not authored here. The `[!question]` invariant from `mode == "main"` applies here too: every `[!question]` MUST carry at least one `- [ ]` row inside its body — the dispatcher's answered-detection lives on a `- [x]` tick inside that row, so an open-ended callout blocks the chain forever. For free-form clarifications, write plain body prose, not a `[!question]` callout.

Ready text is the medium: terminal writers emit the section content as the **settled final form** of the decision, with **no edit-marker fences** (`diff`, `criticmarkup`, `html`) wrapping in-section mutations. Each round either replaces the section's authoritative content with a new settled version, leaves it unchanged, or empties it — the terminal writer is stating a decision, not iterating on prior prose. The dispatch's `edit_marker_style` field governs `mode=main` body-prose refinement and does not apply to this mode (see § Edit-marker persistence across rounds). Downstream consumers parse the section's ready text directly; diff fences here would force every consumer (apply gates, audits) to disambiguate proposed-vs-settled lines — exactly what the ready-text rule eliminates.

### mode == "history"

Dispatcher reads `history_entry` from the response (not from `result/`); no result file is written. May also read `repaired_history_section` when present.

### mode == "repair"

Dispatcher reads the full file body from `result/<file>` and writes it back byte-for-byte (no reapply, no graft; this is a structural-fix mode).

## Edit-marker persistence across rounds

The dispatch's ``edit_marker_style`` field names a marker shape from ``lazy-core.markdown-style`` (``simple`` / ``diff`` / ``criticmarkup`` / ``html``). That shape governs how the ``mode=main`` writer renders body-prose mutations THIS round. ``mode=validation`` and ``mode=terminal`` are plain-text / ready-text modes per their respective sections above and do NOT emit edit markers regardless of ``edit_marker_style``.

Across rounds the invariant is: **every marker emitted by the main writer in any prior round MUST be returned to ``result/<file>`` verbatim**. A main writer NEVER resolves (collapses, folds, applies) a marker on its own initiative — not its own from this round, not its own from a prior round. Markers accumulate in the document body across the entire pre-approve review cycle; only the consumer's finalize step (run after the operator approves) folds every marker of the configured style into final prose.

The invariant holds regardless of:

- **Round age.** A prior-round marker is document state — the current main writer treats the body it receives as the source of truth and preserves every marker it finds.
- **Apparent staleness.** A marker sitting unchanged across several operator commits is NOT an implicit acceptance. The operator's silence is the operator's choice; the marker persists until the operator either modifies it (see below) or the document reaches finalize.

The operator REJECTS or REVISES a prior-round marker by editing the document directly. Per-style shapes:

- **``diff`` style** — overwrite the ``+`` line(s) with the desired final text, or delete the fence entirely (drops the proposed change). Re-emitting the fence in the next writer round MUST NOT regenerate the rejected proposal.
- **``simple`` / ``criticmarkup`` / ``html``** — modify the marker's payload (e.g. change ``==add==`` to ``==revised==``) or delete the span outright. Same re-emission rule.

A writer that "tidies" old markers by silently collapsing them is a protocol violation regardless of how clean the resulting prose reads.

### Cross-fence ``+`` / ``-`` cancellation (``diff`` style)

When a writer in a later round wants to **replace** prose introduced by a prior-round ``+`` line, the writer emits a NEW ``diff`` fence pairing ``- <prior-content>`` with ``+ <revision>``. The ``- <prior-content>`` line MUST be byte-for-byte equal to the prior ``+`` content (no rewrap, no whitespace tidy) — exact match is the cancellation key. The writer does NOT edit the prior fence in place (that would violate the "tidies old markers" prohibition); it emits its own fence and cites the prior emission in its ``-`` line.

At finalize the consumer's ``strip_markers(style="diff")`` resolves the fences as one pass: each ``-`` line in any fence cancels the FIRST surviving ``+`` (or ``!``) emission from any earlier fence whose content matches byte-for-byte. Context (``  ``) lines are never cancellable — they show unchanged prose, not a writer-emitted insertion. A ``-`` that finds no matching prior ``+`` is silently dropped from its own fence (the legacy within-fence behavior for a deletion against plain body prose). Matching is one-shot — one ``-`` cancels exactly one ``+``; a fence wanting to retract two prior insertions of the same line emits two ``-`` entries.

Rationale: without cross-fence cancellation, the writer who emits ``- A / + B`` saw ``A`` cancelled within its own fence (dropped) and ``B`` kept — but the prior fence's ``+ A`` survived independently, leaving both ``A`` and ``B`` in the finalized body as side-by-side near-duplicates. With cross-fence cancellation the prior ``+ A`` is retired and only ``B`` ships, which is the writer's actual intent.

Out of scope here: fuzzy / similarity-based matching. The protocol guarantees only exact-content cancellation; a writer that needs to revise a paragraph whose wording is also slightly reflowed MUST copy the prior content verbatim into its ``-`` line, or accept that both versions ship.

## When ``concerns`` is populated

``concerns`` appears on ``mode=main`` dispatches only, and only when at least one ``mode=validation`` H1 section currently holds non-empty content. Each entry names one such section and carries its body (heading + ownership tag stripped). The field exists so the main-mode agent has read access to validator-authored content despite ownership-isolation preventing cross-section edits; how the agent uses the data is agent-side. How the consumer state machine decides when validation sections fire, when to auto-revert, and when to pause for an operator decision is out of scope for this wire contract.

## ``history_entry`` shape

For ``kind=review`` and ``kind=history (summarized)``, the response MUST carry ``history_entry``: one declarative past-tense sentence, 80–200 characters, **naming WHAT is now in the document** (sections added/removed, prose rewritten, callouts appeared/disappeared) — strictly substantive content describing the document as an artefact, never the process that changed it. **Name the change, not the conclusion** — "A rollback paragraph appeared under Failure-path", NOT "Made the failure-path handling clearer".

Exhaustive forbidden-vocabulary list (shared by every expert that emits a ``history_entry``):

- **No ``#tag`` syntax** — ``#review/*`` or any ``#anything``.
- **No actor names** — ``operator``, ``writer``, ``main writer``, ``section writer``, ``final writer``, ``test-designer``, ``specialist``, ``expert``, ``historian``, or any expert-group name (``main`` / ``<section>`` / ``final`` / ``history``).
- **No process verbs that imply an actor** — ``answered``, ``folded``, ``lifted``, ``approved``, ``ticked``, ``reviewed``, ``raised a concern``.
- **No review-machinery vocabulary** — ``status callout``, ``banner``, ``above the title``, ``# History`` / ``History section`` / ``history entry``, ``review round`` / ``round N`` / ``first/next round``, frontmatter fields (``review_active`` / ``review_round`` / ``review_approved`` / ``approved``), lifecycle verbs about the review itself (``open review``, ``close review``, ``review cycle``, ``approve checkbox``).
- **Writer-authored callouts ARE content** — the appearance or disappearance of ``[!question] #review/question`` and ``[!attention] #review/concern`` callouts is a content change; narrate it in content terms ("Four open questions about export scope appeared"), never as actor action.

**Noise vs content (the ``noop`` boundary).** The only noise is whitespace-only changes and the banner-state line at the top of body (``[!hint] Waiting`` / ``[!caution] Action needed`` / ``[!success] Ready to approve``) — the dispatcher pre-strips banner-state callouts from both revisions before the expert sees them. Count the non-whitespace, non-banner diff lines: zero ⇒ ``outcome=noop`` (bookkeeping only); greater than zero ⇒ ``outcome=summarized`` is REQUIRED (``noop`` is forbidden when content is visible; if the diff genuinely cannot be summarised, ``outcome=error`` with a one-line reason).

The dispatcher wraps the sentence as ``### <UTC YYYY-MM-DD HH:MM>`` (timestamp only, no actor metadata) and inserts it under ``# History`` ordered by timestamp — newest entries on top, oldest at the bottom. When the historian is invoked is consumer-state-machine policy, out of scope for this wire contract.

## Side-effect rules

- Expert MUST NOT touch any file outside its job dir.
- Expert writes ONLY into ``result/`` (paths declared in the response's ``result`` array).
- For ``kind=history``, the expert NEVER writes to ``result/`` — only fills ``history_entry`` and (optionally) ``repaired_history_section`` in the response.

## Frontmatter reserved keys

The following frontmatter keys are managed by the dispatcher and cannot be written by agent overlays via the reassembly pipeline:

- ``review_active`` — `true` while the document is in the review cycle.
- ``review_round`` — current round number, monotonic per main-writer commit.
- ``review_approved`` — `true` once the operator approved.
- ``review_validation_round`` — count of validation rounds since opening.
- ``review_approved_with_concerns`` — `true` if the operator chose to finalize with outstanding concerns.
- ``review_result`` — terminal discriminator stamped by finalize as the LAST step (``approved`` | ``approved-with-concerns``). All other ``review_*`` keys are stripped at finalize; ``review_result`` is the single key that survives and signals downstream md-scan routines (e.g. consumer apply-gates) that the review has closed. Cleared by the open transition when a doc re-enters the review loop.

Agent-supplied values for these keys are silently dropped on reassembly. Every other frontmatter key is fair game for the agent's overlay.
