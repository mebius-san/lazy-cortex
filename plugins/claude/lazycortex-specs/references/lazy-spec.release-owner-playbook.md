---
name: lazy-spec.release-owner-playbook
description: Release-owner chapter of the level playbook — which product owns releases, the `Start release` row that opens one and what holds it, the release start, and the `Revise architecture` row that keeps the product's `architecture.md` current with the approved designs. Read by `spec.catalog-coordinator` on a product note that owns releases, beside the catalog playbook.
---
# Release owner — how `spec.catalog-coordinator` opens a release

Extracted from § 3 of `lazy-spec.catalog-playbook.md`, loaded on demand: read this file on every wake of a product note that owns releases, after that playbook. Every bare "§ N" below names a section of the catalog playbook.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file, resolved as the catalog playbook's § 3 says. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

## 1. Which product owns releases

Releases are owned by the outermost product in the chain whose record declares a `source`. A product nested under such an owner owns none, even when it declares a `source` of its own whose paths lie inside its parent's: that `source` only narrows the code area for `sync-with-code` and the audit. Only a nested `source` naming a path outside the parent's source paths is a configuration error, which `lazy-spec.product-config` refuses and `lazy-spec.audit` reports.

## 2. The `Start release` row

The row joins the catalog playbook's launch-checkbox table (§ 3) on this product's note, reconciled by the same discipline as every row there:

| Checkbox | Appears when | On tick |
|---|---|---|
| `Start release` | the level is a product root that owns releases AND the delta is non-empty AND no release is open (§ 5) AND the architecture is current AND no conflict is open (below) | create the release from the delta, then wake its coordinator — the release start below |
| `Revise architecture` | the level is a product root that owns releases AND `architecture.md` is `approved` AND outside review AND `release-delta` reports `architecture.behind` non-empty | bring `architecture.md` up to date and open its review — § 4 below |

**What holds `Start release`.** Both facts come from `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-delta <product-key>`, never from reading the tree by hand:

- **The architecture is current** when `architecture.behind` is empty: `architecture.md` is `approved`, and approved later than the start document of every asset in the delta. A product whose `# Coordinator rules` declare that it carries no architecture document is always current, whatever the verb reports.
- **No conflict is open** when `conflicted` is empty: neither the product's level notes nor the notes of the delta's assets carry an open coherence conflict. The operator closes one with `Resolve here` or `Not a conflict` (`lazy-spec.coordination-playbook.md` Chapter 19).

While either holds the row down, `# Status brief` says so in plain words: which approved designs the architecture does not cover yet and that `Revise architecture` waits for a tick — or `Write architecture`, when the document does not exist — and which notes carry a conflict.

## 3. The release start

`Start release` is the one row whose tick is not a document: on it, judge the version part over the whole delta — the asset types are a hint, not a rule — then `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-scaffold <product-key> --bump <part>`, which creates `releases/NNN/` with its status note, `spec_includes` filled from the delta and the version written, and then `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> coordinator-dispatch --release-start <release-note>`, which wakes the release's own coordinator once — the one downward hop a level ever makes. Both are verbs, not jobs; the release coordinator hangs the release's own rows and dispatches the build on the operator's tick there (`lazy-spec.release-playbook.md`). The delta itself is `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-delta <product-key>`: read it on every wake of a product that owns releases, hang `Start release` by the rule of § 2, and name what it holds back and why in `# Status brief`.

## 4. `Revise architecture`

The architecture is the product's and is one for all its releases: it is brought up to date here, on the product note, when an approved design is not covered yet — never inside a release. The row hangs whether or not a release is open.

On the tick, read `architecture.behind` from `release-delta` and write ONE `> [!todo] #review/command` callout into `architecture.md` naming the start document of every asset listed there, telling the writer to bring the architecture up to date with those approved designs and to change nothing else. Then open the document's review at the writer round with `Skill(lazycortex-review:lazy-review.start, "<doc>")`. The review's coordinator carries the command out as the round's input (`lazy-review.doc-review-protocol.md`), and the review then runs as any other. The tick dispatches no job, and the callout is the second of the two writes this coordinator ever makes into a document's body, beside the one `Resolve here` makes.

The writer may leave the text as it is when the architecture already covers the designs. The approval of the review is what counts either way: it restamps the document's approval moment (`promote-approved --transitioned`, catalog playbook § 1), and `architecture.behind` reads empty from then on.

**A verdict wakes an open release.** On the `DOC_TRANSITION` that turns `architecture.md` `approved`, find the open release with `release-delta`; when one is open, wake it with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> coordinator-dispatch --release-start <release-note>`, where `<release-note>` is a repo-relative path, so it can hang its `Rebuild` row for the designs the architecture now covers (`lazy-spec.release-playbook.md`, "Rebuild"). A rejected revision wakes nothing and is not rolled back: `Start release` stays held until the document is approved again.
