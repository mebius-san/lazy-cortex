---
since: 12.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, cancel-sweep, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

Cancelling an asset now takes its documents with it: `flip-gate <asset> spec_cancelled` stops every review in the asset folder, cancels the asset's running expert job, and moves every staged document to `cancelled`, recording on each the stage it had so an un-cancel can bring it back. An asset cancelled by an earlier version reads `spec_cancelled: true` on its status note while its documents still sit at their old stages, their reviews and banners and the asset's job possibly still running, and none of them carries the mark the un-cancel reads. The `cancel-sweep` verb applies the cancel to every such asset, the flag left as it is, one commit per asset under the flip-gate bot identity.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> cancel-sweep --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> cancel-sweep --dry-run --cwd "<repo-root>"` prints an empty `pending` list: no cancelled asset still holds a staged document outside `cancelled` or a document under review. Step 2 goes on past an asset it cannot sweep: an asset the cancel refused is listed under `refused`, naming its reason and per-document `refused` list, and the step exits 1; an asset whose sweep failed is listed under `failed` with its error, and the step exits 2 — settle every listed asset and run step 2 again.
