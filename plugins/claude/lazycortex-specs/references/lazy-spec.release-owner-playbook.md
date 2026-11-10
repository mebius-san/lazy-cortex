---
name: lazy-spec.release-owner-playbook
description: Release-owner chapter of the level playbook — which product owns releases, the `Start release` row that opens one, the release start, and the first-step revision of the product's `architecture.md`. Read by `spec.catalog-coordinator` on a product note that owns releases, beside the catalog playbook.
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
| `Start release` | the level is a product root that owns releases AND the delta is non-empty AND no release is open (§ 5) | create the release from the delta, then wake its coordinator — the release start below |

## 3. The release start

`Start release` is the one row whose tick is not a document: on it, judge the version part over the whole delta — the asset types are a hint, not a rule — then `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-scaffold <product-key> --bump <part>`, which creates `releases/NNN/` with its status note, `spec_includes` filled from the delta and the version written, and then `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> coordinator-dispatch --release-start <release-note>`, which wakes the release's own coordinator once — the one downward hop a level ever makes. Both are verbs, not jobs; the release coordinator dispatches the build (`lazy-spec.release-playbook.md`). The delta itself is `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-delta <product-key>`: read it on every wake of a product that owns releases, hang `Start release` while it is non-empty and no release is open, and name what it holds back and why in `# Status brief`.

## 4. A first-step revision

On the product that owns releases, a `DOC_TRANSITION` that turns the product's `architecture.md` `approved` or `rejected` may concern the first step of an open build. Find the open release with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> release-delta <product-key>`; when that release waits on the architecture in its first step, wake it with `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> coordinator-dispatch --release-start <release-note>`, where `<release-note>` is a repo-relative path. A rejected revision is not rolled back. What the release does on the wake is `lazy-spec.release-playbook.md`'s ("The build").
