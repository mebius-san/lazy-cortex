---
chapter_type: block
summary: Mirror external design repos into your vault and keep a spec doc's visible source list matching its frontmatter.
last_regen: 2026-08-19
diagram_spec:
  anchor: "How an upstream unit becomes part of a spec"
  request: "flow diagram: upstream-run mirrors and diffs a unit from a foreign repo, an operator ticks its Take into work / Process update checkbox, a body-only request opens and freezes the unit to in-review, the request lands against an asset (recorded in spec_source_requests), and refresh-sources re-projects that attachment into the asset doc's visible Sources list"
source_skills:
  - lazy-spec.upstream-run
  - lazy-spec.refresh-sources
source_sha: 80e73e18e264de362567002f96b3f548b26969de
---

Some design material for your product doesn't start life in your spec vault — it lives in someone else's repository, updated on its own schedule. This block covers two jobs that keep your specs honest about material like that: pulling in what changed in a mirrored external source, and making sure a doc's visible list of sources actually matches what its frontmatter says it's built from.

## What's in this block

**lazy-spec.upstream-run** runs one full fetch/detect pass over every source configured under the `spec.upstream` settings section. Each configured source names a foreign git repo (URL, optional branch) and one or more mounts — a path inside that repo plus glob patterns naming which subdirectories count as "units". The pass mirrors matching unit directories into the vault under `upstream/<repo-key>/<mount>/<unit-path>/`, diffs them against what's already there, and assigns each unit a status: `new` (never seen before), `drifted` (changed since it was last processed), `processed` (unchanged), `orphaned` (vanished from the source), `excluded` (dropped by the mount's glob or `exclude` list), `invalid`, or `postponed`. A unit that comes back `new` or `drifted` gets a `Take into work` / `Process update` checkbox on its own folder-note; ticking it opens a body-only request under `requests/` and freezes that unit onto `in-review` until the request's review concludes. This skill is the manual, on-demand counterpart of the scheduled `lazy-spec.upstream-tick` routine `lazy-spec.install` registers once at least one source is configured — same underlying primitive, same result, run by hand instead of waiting for the next tick.

**lazy-spec.refresh-sources** re-projects a single authored spec doc's visible `# Sources` section — its `## Docs` and `## Requests` bullet lists — from that doc's `spec_source_docs` / `spec_source_requests` frontmatter, which is the actual source of truth. It preserves any operator gloss already on an existing bullet by matching on the wikilink target, drops bullets whose wikilink left the frontmatter, and adds a plain bullet for anything new. After the bullets are in sync, it also regenerates the one-sentence `# Summary` précis for the asset note itself and for its category and product-root containers, and refreshes their deterministic stats. It touches exactly one file per call — nothing loops inside it.

## How they work together

Registering a source is a one-time, hand-edited step: you add a `<repo-key>` entry (`url`, optional `branch`, one or more `mounts` each with a `source_path` and a `units` glob) under `spec.upstream` in `lazy.settings.json`. From there, `/lazy-spec.upstream-run` — or the scheduled tick, if you'd rather not run it by hand — walks every configured source, mirrors what its `units` glob currently matches, and tells you which units are new or drifted.

A unit landing as `new` or `drifted` doesn't do anything on its own; it waits on its checkbox. Tick `Take into work` (or `Process update`) on that unit's folder-note under `upstream/<repo-key>/<mount>/<unit-path>/` and re-run the pass — or let the next scheduled tick catch it — and the unit opens a body-only request under `requests/`, freezing itself to `in-review` until that request's review concludes. From there the request travels through the standard review pipeline on its own schedule; `/lazy-spec.upstream-run` never dispatches an expert job itself.

Once a request from an upstream unit lands against one of your assets, that asset's `spec_source_requests` frontmatter gains the request's wikilink — but the doc body doesn't update itself. Run `/lazy-spec.refresh-sources <doc-path>` on that asset's authored doc and the `## Requests` list under its `# Sources` section catches up: the newly attached request appears as a bullet, any bullet whose wikilink is no longer in frontmatter drops out, and everything else you or another skill wrote there stays untouched. The same call regenerates the asset's, its category's, and the product root's `# Summary` précis and stats, so the vault's higher-level notes reflect the attachment too.

In practice: reach for `/lazy-spec.upstream-run` when you want to know right now what changed in a mirrored source instead of waiting on the schedule. Reach for `/lazy-spec.refresh-sources` any time you've hand-edited a doc's `spec_source_docs` / `spec_source_requests`, or after a request — upstream-derived or otherwise — has landed and you want the doc's visible Sources section to actually say so.

## Where this fits

`spec.upstream` sources are independent of the `products[<key>].source` binding that ties a product to its own code repository, and independent of the `repos` table that source-links resolves against — an upstream source is a foreign *design* repo, cloned into its own runtime scratch space and tracked entirely separately. What upstream-run and refresh-sources hand off to is the same request review pipeline the requests block documents: an upstream-opened request is body-only and unclassified exactly like a request an operator files by hand, and it's routed and attached the same way from there.

## How an upstream unit becomes part of a spec
