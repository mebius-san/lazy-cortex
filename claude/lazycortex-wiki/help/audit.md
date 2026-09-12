---
chapter_type: block
summary: Run integrity checks across a wiki scope, its terms dictionary, structure map, mirrors, and domain tree — with optional auto-repair.
last_regen: 2026-09-11
no_diagram: true
source_skills:
  - lazy-wiki.audit
source_sha: 3f4c00192599a38cbb9db4308367d5db80ec2dfd
---
# Wiki integrity audit

Over time a curated wiki drifts: See-also links point to renamed or deleted nodes, summaries go missing on newly added files, the topic index falls out of sync with actual tag usage, axes get mistyped, a document and the terms dictionary settle on different words for the same concept, or the project-structure map stops matching the tree it describes. The audit block gives you a read-only snapshot of every integrity problem across a scope — categorised by severity and annotated with the route that repairs each one. It writes nothing: running the repair is your move. When a scope mirrors a foreign repo, or the domain-spec tree is configured, the same run checks those too.

`<wiki-cli>` stands for the wiki plugin's `bin/lazycortex-wiki` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-wiki/<version>/`, or `claude/lazycortex-wiki/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`/lazy-wiki.audit` is the only member. It reads your scope configuration from `lazy.settings.json`, runs the built-in `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> doctor` command against the target scope (or all scopes), audits any configured terms scopes and the project-structure map, and groups every finding into `FAIL`, `WARN`, and `INFO` buckets before presenting them to you.

## When you'd use this

- After a large batch of file renames or moves — checking that See-also links and the topic index still match reality. (Node deletions are pruned automatically as they happen — see below — so this is mainly about renames, where the old link is stale rather than gone.)
- Periodically to catch missing summaries on nodes that were added outside the curator workflow.
- When `/lazy-wiki.query` returns unexpected results and you suspect the topic index is stale.
- After editing tag axes in `/lazy-wiki.configure` — verifying no existing tags reference a now-unknown axis.
- When a document and the terms dictionary have drifted onto different words for the same concept, or a term looks unused — the audit surfaces both, one at a time, for you to resolve.
- When `docs/structure.md` no longer matches the tree it maps, or its own configuration looks off.
- When a mirrored scope's clone is stale, missing, or carries local edits a sync would overwrite.
- When the domain-spec tree (`docs/domains/` by default) is missing a group's gloss, carries a doc for a group the dictionary no longer lists, or its hashes are stale against the code.
- Before committing a milestone where you want the wiki, and its companion trees, in a clean state.

## How it fits together

You invoke `/lazy-wiki.audit` with an optional scope id. Omit the id and the skill audits every scope configured in your project. The run has four steps and ends at its report — nothing is ever written.

**Phase 1 — the core audit.** Read-only: `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> doctor` prints per-scope findings grouped by severity, tagging each one the CLI can repair, and ends with a grand-total count. This is also where the mirror checks and, when `wiki.domains` is configured, the domain-tree checks are printed — both report-only. If the scope id you name is unknown, or no scopes are configured at all, the command exits non-zero and the skill stops there rather than proceeding to later phases.

**Phase 2 — terms scopes and the structure map.** Neither has a CLI of its own, so this phase reads `lazy.settings.json` directly. For each configured terms scope it checks two things: configuration you can judge by reading (a missing dictionary file, overlapping scope globs, a dictionary that isn't excluded from the wiki scope that would otherwise try to curate it) and meaning, dispatched to the terms curator in report mode, which returns divergence / missing / duplicate / dead findings without writing anything. The project-structure map gets the same treatment — configuration read directly, then a structure-curator dispatch in report mode comparing the map against the tree. Either sub-check is skipped with a stated reason when nothing is configured (`no-terms-scopes`, `no-structure`).

Structure configuration checks also cover the three scan routines' `watch` setting — `new_files` / `deleted_files` / `renamed_files` on the change / deletion / rename routine respectively — and flag any of the three registered before `docs/structure.md` exists, since every incremental dispatch fails its precondition until `/lazy-wiki.structure rebuild` creates the map.

**Phase 3 — presentation.** Every finding from both phases is summarised: per-scope counts by severity, plus check name, affected node or entry, and message — with the findings `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> doctor --apply` repairs called out separately from the ones needing a hand repair, and a named repair route for every class.

**Applying the repairs.** The audit stops at its report. To repair the index/link findings, run `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> doctor <scope-id> --apply` yourself — index rebuild, See-also path rewrite, broken-line drop, gloss refresh, left uncommitted in the worktree for you to inspect. The daily `lazy-wiki.doctor-apply` routine already runs the same command with `--commit` across every scope, so on a checkout with a running daemon these usually clear on their own. Terms findings are never decided for you — which side is "right", the document's wording or the dictionary's, is a judgment call, and the audit reports both sides for you to settle. Once you have settled a `divergence` in the dictionary's favour, `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-apply <document> --from "<the document's word>" --to "<the dictionary's term>"` carries out that substitution: whole-word, prose only, with the frontmatter, code fences, inline code spans, link targets and the `# See also` block left exactly as they are, the rewrite left uncommitted in your worktree, and a flat refusal (exit 1, reason on stderr) on a document carrying `review_active: true` or living inside a scope's mirror tree. Re-running it after it has applied reports `noop` and rewrites nothing. Every other terms finding — and the other side of a divergence, where the dictionary's term is the one that changes — stays a hand edit.

Applying a fix only touches the lines that need it — the rest of a node's See-also section, or the rest of the topic index, is left exactly as it was.

## Findings, fixable vs report-only

**Repaired by `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> doctor --apply`:** `orphan-topic` and `index-desync` rebuild the topic index; `see-also-path-base` rewrites a See-also link written against a non-canonical path form; `broken-see-also` drops a dead link; `stale-gloss` refreshes an outdated gloss.

**Report-only** — the right fix depends on your intent, so the skill surfaces the problem and names a route rather than rewriting content for you:

- `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap` — the core scope checks the original audit shipped with.
- `dangling-at-prefix` — a leftover pre-mirror cross-repo link (`@`-prefixed). Rewrite it to the mirrored node's local path if a mirror scope now covers the target, or drop the line.
- `mirror-clone-orphaned`, `mirror-dir-missing`, `mirror-paths-uncovered`, `mirror-stale-fetch`, `mirror-local-edit` — a mirrored scope's clone versus its configuration. Register or remove the `mirror` block via `/lazy-wiki.configure mirror`, run the mirror sync by hand or wait for the `lazy-wiki.mirror-sync` routine, or widen the scope's `paths` to cover the mirror directory. `mirror-local-edit` warns that the next sync overwrites local changes — salvage them first.
- `domain-dictionary-missing`, `domain-doc-unknown`, `domain-gloss-missing`, `domain-group-unknown`, `domain-hash-stale`, `domain-output-in-scope`, `domain-routine-mismatch`, `domain-tag-axis-unknown` — the domain-spec tree versus the code and dictionary that feed it. `domain-tag-axis-unknown` names a generated doc carrying a `wiki/<axis>/...` tag whose axis is not in `wiki.tag_axes` — register the axis or stop the writer minting it, since the doc is regenerated and hand-editing its tags never holds. `domain-output-in-scope` specifically means a wiki scope's `paths` glob reaches the domain-spec output tree, which is excluded from every scope structurally — no file is contested, the fix is narrowing the scope's `paths` via `/lazy-wiki.configure` so its coverage matches what it actually curates. See [domains](domains.md) for the tree itself; the audit here only reports drift.
- `divergence`, `missing`, `duplicate`, `dead`, plus terms `format` / `config` findings — the terms dictionary versus the documents it serves. See [terms](terms.md) for how the dictionary is normally kept current.
- `missing-dir`, `missing-file`, `dead-entry`, `divergence`, `depth`, plus structure `config` findings — the project-structure map versus the tracked tree. See [structure](structure.md) for how the map is normally kept current.

## Common adjustments

- **Auditing a single scope** — pass the scope id: `/lazy-wiki.audit <scope-id>`. Useful when you know which scope changed and don't want to wait on a full multi-scope run.
- **Adding or editing scope configuration** — run `/lazy-wiki.configure`. It owns `lazy.settings.json[wiki.scopes]`, plus the `wiki.domains`, `terms.scopes`, and `structure` sections; do not hand-edit that file.
- **Resolving unknown axes** — run `/lazy-wiki.configure` to add the axis to the scope definition, or to rename the axis used in existing tags. The skill writes the settings; then re-run `/lazy-wiki.audit` to confirm the finding is cleared.
- **Missing summaries** — these are report-only. Run `/lazy-wiki.relink` (the curation block) to have the curator fill in summaries for uncurated nodes.
- **A `broken-see-also` finding keeps appearing after deleting a node** — if the background daemon isn't running, the automatic pruning happens on your next `/lazy-wiki.relink` rather than instantly. Run `/lazy-wiki.relink` on the affected scope, then re-run `/lazy-wiki.audit` to confirm the finding is gone.
- **A `divergence` or `dead` terms finding** — the audit will not auto-apply either side; when it asks, it shows both words and names which side each answer picks, and you tell it which one wins (the document's or the dictionary's). A document with `review_active: true`, or anything under an upstream mirror tree, is never touched this way — resolve those by hand.
- **Structure or domain drift after a rename sweep** — `missing-dir` / `missing-file` / `dead-entry` / `divergence` findings usually clear with a wholesale `/lazy-wiki.structure rebuild` rather than fixing entries one at a time; `domain-hash-stale` clears with `/lazy-wiki.domain-sync`.
- **A structure-scan routine reports `config` right after registration** — if `docs/structure.md` doesn't exist yet, every one of the three scan routines fails its precondition until you run `/lazy-wiki.structure rebuild` once to create the map.
- **`docs/structure.md` shows up as a finding in its own scope** — the map has no frontmatter to defend itself against being curated as an ordinary node. The exclusion belongs to the whole vault, not one scope: add `docs/structure.md` to `wiki.exclude` via `/lazy-wiki.configure vault` rather than excluding it scope by scope.
- **If the scope id you pass is not in `lazy.settings.json`** — the command exits non-zero and the skill surfaces the error without proceeding to the presentation or apply phases.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap the plugin, which also runs an initial integrity check as part of setup.
- [curation](curation.md) — the per-node curator that writes summaries, topic tags, and See-also links; resolves `missing-summary` findings produced here.
- [terms](terms.md) — the terms dictionary this audit's terms findings check against.
- [structure](structure.md) — the project-structure map this audit's structure findings check against.
- [domains](domains.md) — the domain-spec tree this audit's domain findings check against.
