---
chapter_type: block
summary: Run integrity checks across a wiki scope — orphan topics, broken links, missing summaries, stale glosses, unknown axes, and overlapping scopes — with optional auto-repair.
last_regen: 2026-06-01
no_diagram: true
source_skills:
  - lazy-wiki.doctor
---
# Wiki integrity audit

Over time a curated wiki drifts: See-also links point to renamed or deleted nodes, summaries go missing on newly added files, the topic index falls out of sync with actual tag usage, and axes get mistyped. The audit block gives you a read-only snapshot of every integrity problem in a scope — categorised by severity and annotated with what is fixable automatically — and lets you apply the fixable repairs in a single confirmed step.

`/wiki.doctor` is the only member. It reads your scope configuration from `lazy.settings.json`, runs the built-in `lazycortex-wiki doctor` command against the target scope (or all scopes), and groups findings into `FAIL`, `WARN`, and `INFO` buckets before presenting them to you.

## When you'd use this

- After a large batch of file renames, deletions, or moves — checking that See-also links and the topic index still match reality.
- Periodically to catch missing summaries on nodes that were added outside the curator workflow.
- When `/wiki.query` returns unexpected results and you suspect the topic index is stale.
- After editing tag axes in `/wiki.configure` — verifying no existing tags reference a now-unknown axis.
- Before committing a milestone where you want the wiki in a clean state.

## How it fits together

You invoke `/wiki.doctor` with an optional scope id. If you omit the id the skill audits every scope configured in your project. Phase 1 runs the audit in read-only mode — nothing is written. Phase 2 presents the findings grouped by severity, distinguishing fixable checks (`orphan-topic`, `index-desync`, `broken-see-also`, `stale-gloss`) from report-only ones (`broken-repo-key`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`). Phase 3 asks you whether to apply the fixable repairs; if you confirm, `--apply` is passed and the skill reports each fix individually.

Fixable repairs rewrite tracked files — the topic index is rebuilt, broken See-also lines are dropped, and stale glosses are refreshed. Report-only findings require your own action: add a summary to a node, fix a broken repo key in your settings, resolve an unknown axis by running `/wiki.configure`, or manually separate overlapping scope globs.

If the scope id you pass is not in `lazy.settings.json`, the command exits non-zero and the skill surfaces the message without proceeding. The remedy is to run `/wiki.configure` to create the scope, or to re-invoke with a scope id that exists.

## Common adjustments

- **Auditing a single scope** — pass the scope id: `/wiki.doctor <scope-id>`. Useful when you know which scope changed and don't want to wait on a full multi-scope run.
- **Adding or editing scope configuration** — run `/wiki.configure`. It owns `lazy.settings.json[wiki.scopes]`; do not hand-edit that file.
- **Resolving unknown axes** — run `/wiki.configure` to add the axis to the scope definition, or to rename the axis used in existing tags. The skill writes the settings; then re-run `/wiki.doctor` to confirm the finding is cleared.
- **Missing summaries** — these are report-only. Run `/wiki.relink` (the curation block) to have the curator fill in summaries for uncurated nodes.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap the plugin, which also runs an initial integrity check as part of setup.
- [curation](curation.md) — the per-node curator that writes summaries, topic tags, and See-also links; resolves `missing-summary` findings produced here.
