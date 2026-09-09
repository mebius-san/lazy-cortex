---
chapter_type: faq
summary: Answers to common questions about installing, configuring, and running the lazycortex-review document-review loop.
last_regen: 2026-09-09
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
source_sha: 4fc1434f9297bd2173e9a38ba45d75f8d68a26f8
---
# Frequently asked questions

## What do I need before running `/lazy-review.install`?

`lazycortex-core` must be installed and configured first. The expert runtime, the daemon, and the `lazy.settings.json` schema all live there — `lazycortex-review` is a hard dependent. Run `/lazy-core.install` in the same repo, confirm the daemon is enabled (the review loop is entirely daemon-driven), then run `/lazy-review.install`.

---

## What routines does `/lazy-review.install` register, and does the daemon have to be running?

Three routines carry the review loop: `lazy-review.coordinator-watch` (the git-watch that turns a commit into a coordinator wake), `lazy-review.collect` (the interval postman that lands finished expert payloads into the reviewed document), and `lazy-review.sanitize` (a daily deterministic sweep that repairs lost writer wakes, orphaned reviews, and markers on documents that have since vanished). All three are registered unconditionally, whatever the repo's daemon posture is — `/lazy-runtime.tick` fires the same interval, git-watch, and cron routines on a checkout with no daemon running, so withholding registration behind `daemon.enabled` would only leave the manual tick with less config to work from. If a routine is missing after install, re-run `/lazy-review.install` — Step 1 is idempotent and re-applies the seed.

---

## Does `/lazy-review.install` ask me to pick protocols for the coordinator routine?

No. `lazy-review.coordinator-watch` always carries two mandatory protocols, attached automatically with no prompt: the coordination playbook the woken coordinator reasons from, and `lazy-core.markdown-style` (every wake produces markdown in the vault). The coordinator is a system expert, so its protocol set is fixed by design — install never offers optional protocols for its routine. If you want to attach an extra protocol to the routine yourself, run `/lazy-routine.offer-protocols` directly; that skill is the operator-facing channel for it, not an install sub-step. (`lazy-review.collect` and `lazy-review.sanitize` take no protocols; neither dispatches an agent.)

---

## Do I need to add anything to `.gitignore` after installing?

The runtime writes operator-private state into `.experts/` (job queue, trackers, subprocess locks) and tick logs under `.logs/lazy-review/`. Both trees are typically not for version control. `/lazy-review.install` prints the recommended lines but never touches `.gitignore` itself — add them by hand:

```
.experts/
.logs/lazy-review/
```

---

## What happens if my vault's `review-callouts.css` conflicts with a shipped update?

`/lazy-review.install` syncs the `review-callouts.css` snippet into `<vault>/.obsidian/snippets/` non-destructively: a missing or byte-identical snippet is written silently, and a local edit that lands in a different region than the shipped change merges silently too. Only a genuine conflict — the same region edited both locally and in the shipped version — asks, offering `merge-shipped` (the shipped version wins for that region, your other edits are kept) or `keep-local` (your version wins for that region, the rest of the shipped delta still applies).

When install runs through a path with no operator to ask — an unattended rollout across several repos, for example — it cannot stall on that question. It keeps your local region, applies the rest of the shipped delta, and names the file so you know to resolve it. Re-run `/lazy-review.install` yourself afterwards (interactively) to answer the conflict directly.

---

## What does `/lazy-review.configure` actually ask me?

The wizard collects the things the plugin cannot derive on its own: which file globs belong to this review class and the short identity token that names it (e.g. `design`, `request`), which experts act as main writers, which additional sections (validation or terminal) to add and who owns them, and which edit-marker style to use (`simple`, `diff`, `criticmarkup`, or `html`). Every value already persisted in `lazy.settings.json` is reused silently — re-running the wizard on a fully-configured class re-validates without asking a single question. A class may also carry a `protocols` list attached automatically by the plugin that owns the document kind; the wizard never asks about it and always preserves whatever is on record.

---

## What is the difference between `/lazy-review.start` and `/lazy-review.submit`?

`/lazy-review.start` opens the document and sends it through the full loop beginning with the main-writer round. Use it when you want the expert to draft the first pass.

`/lazy-review.submit` opens the document and skips the main-writer round, landing directly on the reviewer. Use it when the document already has your edits in place and you want reviewers to assess the current text rather than re-draft it. The optional `--expert` flag pins a per-document main-writer override for the submit path.

Both operations are idempotent — re-running on an already-opted-in document is a no-op.

---

## I changed the edit-marker style in `/lazy-review.configure`, but a document already under review still uses the old one. Why?

Because the style is pinned to the document, not read live from settings. The first time a document enters the loop — via `/lazy-review.start` or `/lazy-review.submit` — the class's `edit_marker_style` is copied into that document's own `review_marker_style` frontmatter key, and every later step of that cycle (dispatch, strip-markup, finalize) reads the pin instead of going back to `lazy.settings.json`. A settings change made mid-cycle therefore never reaches a review that is already open; it only takes effect on the next document that opts in fresh. To pick up the new style on the current document, `/lazy-review.stop` it and `/lazy-review.start` it again — re-opening seeds a new pin from whatever the class carries now.

---

## Can I pause review on a document without losing my progress?

Yes. Run `/lazy-review.stop <file>`. This sets `review_active` to false but preserves `review_round`, `approved`, and the `# History` section. When you are ready to resume, run `/lazy-review.start <file>` again and the daemon picks up from the same round — the document keeps whatever `review_marker_style` it was pinned with at entry.

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

`/lazy-review.configure`'s style question is read-first: it only asks when nothing is on record for `review.edit_marker_style`, so re-running the wizard on a class that already has a style just reuses it silently — there's no prompt to pick a different one. There is currently no configure flow for changing an already-set style; the wizard is still the correct entry point for everything else about the class (globs, writer groups, sections), just not for revisiting this one value. Note that even a settings-level style change only ever reaches documents that have not yet entered review — see the pinning question above for why an open review keeps its own copy.

---

## Where do run logs land?

Each skill writes a timestamped log under `.logs/claude/<skill-name>/` in the current repo. For example, a `start` run lands at `.logs/claude/lazy-review.start/<UTC-timestamp>.md`. The `status` and `audit` skills are read-only and do not write a log.
