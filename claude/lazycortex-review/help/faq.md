---
chapter_type: faq
summary: Answers to common questions about installing, configuring, and running the lazycortex-review document-review loop.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-review.install
  - lazy-review.configure
  - lazy-review.start
  - lazy-review.submit
  - lazy-review.status
  - lazy-review.stop
  - lazy-review.finalize
  - lazy-review.audit
source_sha: a2062bca54f427d017f9acfce7dee26e2b1db066
---
# Frequently asked questions

## What do I need before running `/lazy-review.install`?

`lazycortex-core` must be installed and configured first. The expert runtime, the daemon, and the `lazy.settings.json` schema all live there — `lazycortex-review` is a hard dependent. Run `/lazy-core.install` in the same repo, confirm the daemon is enabled (the review loop is entirely daemon-driven), then run `/lazy-review.install`.

---

## I ran `/lazy-review.install` but the review routines were not registered. Why?

Three routines only work when `lazycortex-core`'s runtime daemon is enabled: `lazy-review.coordinator-watch`, which turns a commit into a coordinator wake; `lazy-review.collect`, which lands finished expert payloads; and `lazy-review.sanitize`, a daily deterministic sweep that repairs lost writer wakes, orphaned reviews, and markers on documents that have since vanished. If the `daemon.enabled` flag in `lazy.settings.json` is `false`, the install step removes all three to avoid leaving dead config. The rest of the plugin — settings sections, directories, the CLI allow-pattern — is still installed. Enable the daemon via `/lazy-core.install` (or the relevant core configure skill), then re-run `/lazy-review.install` to register them.

---

## During install I was asked to pick optional protocols for `lazy-review.coordinator-watch`. What are these?

`lazy-review.coordinator-watch` always carries two mandatory protocols — the coordination playbook the woken coordinator reasons from, and `lazy-core.markdown-style` — that ship attached and are never asked about. Other plugins can ship references that are useful while working on reviewed documents but aren't required (for example, a diagram-writing guide), and those self-flag as optional candidates. `/lazy-review.install` discovers them and lets you pick which ones to attach; declining just means the coordinator doesn't get that extra guidance. Nothing you pick changes how the loop behaves — that is the playbook's business. If you skip one and change your mind later, re-run `/lazy-review.install` — anything not yet attached is offered again. (`lazy-review.collect` and `lazy-review.sanitize` take no protocols; neither dispatches an agent.)

---

## Do I need to add anything to `.gitignore` after installing?

The runtime writes operator-private state into `.experts/` (job queue, trackers, subprocess locks) and tick logs under `.logs/lazy-review/`. Both trees are typically not for version control. `/lazy-review.install` prints the recommended lines but never touches `.gitignore` itself — add them by hand:

```
.experts/
.logs/lazy-review/
```

---

## What does `/lazy-review.configure` actually ask me?

The wizard collects the things the plugin cannot derive on its own: which file globs belong to this review class and the short identity token that names it (e.g. `design`, `request`), which experts act as main writers, which additional sections (validation or terminal) to add and who owns them, and which edit-marker style to use (`simple`, `diff`, `criticmarkup`, or `html`). Every value already persisted in `lazy.settings.json` is reused silently — re-running the wizard on a fully-configured class re-validates without asking a single question. A class may also carry a `protocols` list attached automatically by the plugin that owns the document kind; the wizard never asks about it and always preserves whatever is on record.

---

## What is the difference between `/lazy-review.start` and `/lazy-review.submit`?

`/lazy-review.start` opens the document and sends it through the full loop beginning with the main-writer round. Use it when you want the expert to draft the first pass.

`/lazy-review.submit` opens the document and skips the main-writer round, landing directly on the reviewer. Use it when the document already has your edits in place and you want reviewers to assess the current text rather than re-draft it. The optional `--expert` flag pins a per-document main-writer override for the submit path.

Both operations are idempotent — re-running on an already-opted-in document is a no-op.

---

## Can I pause review on a document without losing my progress?

Yes. Run `/lazy-review.stop <file>`. This sets `review_active` to false but preserves `review_round`, `approved`, and the `# History` section. When you are ready to resume, run `/lazy-review.start <file>` again and the daemon picks up from the same round.

---

## How do I check where a document is in the review cycle?

Run `/lazy-review.status <file>`. It prints one-line JSON with `review_active`, `review_round`, `approved`, the current banner state, and the list of owned sections with their assigned experts. The call is read-only and never modifies the document.

---

## The daemon finalized my document automatically. Can I also finalize manually?

Yes. `/lazy-review.finalize <file>` is the operator's hand-crank. It folds all edit-annotation markers into final text, strips the review banner and approve checkbox, removes system callouts (the `# History` section survives), sets `review_active` to false, and commits with a `Doc-Review-Phase: finalize` trailer. If the document is already in finalized shape the call is a no-op.

---

## `/lazy-review.audit` is reporting `expert_<name>_missing FAIL`. How do I fix it?

A review class references an expert name that is not registered in the top-level `experts` dict in `lazy.settings.json`. Run `/lazy-review.configure` to add the missing expert, or remove the class member that references it. Never edit `lazy.settings.json` directly for this — the configure wizard writes the file with the correct shape and re-runs the audit at the end.

---

## `/lazy-review.audit` reports `settings_present FAIL`. What does that mean?

The audit script could not find `.claude/lazy.settings.json`. Run `/lazy-review.install` first to create and seed it, then re-run the audit.

---

## Can I change the edit-marker style after configuring a class?

`/lazy-review.configure`'s style question is read-first: it only asks when nothing is on record for `review.edit_marker_style`, so re-running the wizard on a class that already has a style just reuses it silently — there's no prompt to pick a different one. There is currently no configure flow for changing an already-set style; the wizard is still the correct entry point for everything else about the class (globs, writer groups, sections), just not for revisiting this one value.

---

## Where do run logs land?

Each skill writes a timestamped log under `.logs/claude/<skill-name>/` in the current repo. For example, a `start` run lands at `.logs/claude/lazy-review.start/<UTC-timestamp>.md`. The `status` skill is read-only and does not write a log.
