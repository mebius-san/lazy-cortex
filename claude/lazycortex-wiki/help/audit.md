---
chapter_type: block
summary: Run integrity checks across a wiki scope — orphan topics, broken links, missing summaries, stale glosses, unknown axes, and overlapping scopes — with optional auto-repair.
last_regen: 2026-07-16
no_diagram: true
source_skills:
  - lazy-wiki.doctor
---
# Wiki integrity audit

Over time a curated wiki drifts: See-also links point to renamed or deleted nodes, summaries go missing on newly added files, the topic index falls out of sync with actual tag usage, and axes get mistyped. The audit block gives you a read-only snapshot of every integrity problem in a scope — categorised by severity and annotated with what is fixable automatically — and lets you apply the fixable repairs in a single confirmed step.

`/wiki.doctor` is the only member. It reads your scope configuration from `lazy.settings.json`, runs the built-in `lazycortex-wiki doctor` command against the target scope (or all scopes), and groups findings into `FAIL`, `WARN`, and `INFO` buckets before presenting them to you.

## When you'd use this

- After a large batch of file renames or moves — checking that See-also links and the topic index still match reality. (Node deletions are pruned automatically as they happen — see below — so this is mainly about renames, where the old link is stale rather than gone.)
- Periodically to catch missing summaries on nodes that were added outside the curator workflow.
- When `/wiki.query` returns unexpected results and you suspect the topic index is stale.
- After editing tag axes in `/wiki.configure` — verifying no existing tags reference a now-unknown axis.
- Before committing a milestone where you want the wiki in a clean state.

## How it fits together

You invoke `/wiki.doctor` with an optional scope id. Omit the id and the skill audits every scope configured in your project. The skill runs in two distinct phases separated by a confirmation gate.

Phase 1 is always read-only — nothing is written. The `lazycortex-wiki doctor` command prints per-scope findings grouped by severity, tagging each fixable finding so you can see what automated repair is available. Phase 2 presents those findings to you: per-scope counts by severity and a short list of check name, affected node, and message.

Findings fall into two categories. Fixable checks (`orphan-topic`, `index-desync`, `broken-see-also`, `stale-gloss`) have automated repairs the skill can apply. Report-only checks (`broken-repo-key`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`) require your own action — they surface a problem but the right resolution depends on your intent, so the skill does not rewrite your content for them.

If fixable findings exist, the skill asks whether to apply the repairs. On confirmation it passes `--apply` to the same command: the topic index is rebuilt, broken See-also lines are dropped, and stale glosses are refreshed. Applying a fix only touches the lines that need it — the rest of a node's See-also section is left exactly as it was. Each fix is reported individually. If you decline, the read-only audit result stands and no files are modified.

You'll see fewer `broken-see-also` findings than you might expect from deleted nodes specifically: deleting a wiki node now prunes every See-also line pointing at it automatically, either through the background daemon (if it's running) or the next `/wiki.relink` (if it isn't) — no audit run required. A `broken-see-also` finding here usually means the target was renamed or moved rather than deleted, or that the automatic pruning hasn't run yet.

If the scope id you pass is not in `lazy.settings.json`, the command exits non-zero and the skill surfaces the error without proceeding to the presentation or apply phases.

## Common adjustments

- **Auditing a single scope** — pass the scope id: `/wiki.doctor <scope-id>`. Useful when you know which scope changed and don't want to wait on a full multi-scope run.
- **Adding or editing scope configuration** — run `/wiki.configure`. It owns `lazy.settings.json[wiki.scopes]`; do not hand-edit that file.
- **Resolving unknown axes** — run `/wiki.configure` to add the axis to the scope definition, or to rename the axis used in existing tags. The skill writes the settings; then re-run `/wiki.doctor` to confirm the finding is cleared.
- **Missing summaries** — these are report-only. Run `/wiki.relink` (the curation block) to have the curator fill in summaries for uncurated nodes.
- **A `broken-see-also` finding keeps appearing after deleting a node** — if the background daemon isn't running, the automatic pruning happens on your next `/wiki.relink` rather than instantly. Run `/wiki.relink` on the affected scope, then re-run `/wiki.doctor` to confirm the finding is gone.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap the plugin, which also runs an initial integrity check as part of setup.
- [curation](curation.md) — the per-node curator that writes summaries, topic tags, and See-also links; resolves `missing-summary` findings produced here.
