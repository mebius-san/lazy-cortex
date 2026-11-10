---
description: Asset creation — materializing expert [!asset-proposal] callouts, the bug three-way choice, and the closed list of asset creators. Conditional chapter 12 of the coordination playbook.
---
# Asset creation — conditional chapter of the coordination playbook

Extracted chapter 12 of `lazy-spec.coordination-playbook.md`, loaded on demand: read this file when an accepted document surfaces an `[!asset-proposal]` callout to materialize, or before scaffolding an asset for any reason other than a routing spawn (routing carries its own chapter). Every "Chapter N" cross-reference below names a chapter of that common playbook.

**Experts never create assets — none, ever.** The single mechanism for proposing a new asset is a callout an expert drops in its own document, shaped per the signals protocol (Chapter 15) — working type `> [!asset-proposal]`. An architect proposes the assets a product is missing in the product `architecture.md` it revises as the first step of a release build; a tester proposes bugs in its report; the mechanism is available to any expert in any doc it owns.

**Bugs get a three-way choice.** Because a bug may already be known, a tester's proposal is one of: create a new bug asset, link to an existing one (duplicate), or reopen a closed one (regression). The tester searches existing bug assets before proposing. At materialization time the coordinator re-checks the same candidates and MAY convert a proposed `create` into a `link` or `reopen` if a better match turns up — a disputed conversion goes to the operator as a `[!question]` rather than being silently decided.

**Materialization happens after the proposal's own doc is accepted.** For a living doc that means the ordinary review approval — the product `architecture.md` included: its proposals materialize once the revised document is approved during the build, and each new asset then goes through its own ladder and ships in a later release, never in the build whose architecture proposed it; for a report that means the acceptance cycle of Chapter 8 closing (approve). Only then does the coordinator act: `create` runs the scaffold verb, forwarding the callout's optional `path` field to `lazy-spec.create-asset` as `--path <dir>` (absent, the type's own `default_path` decides), `link` wikilinks the existing asset, `reopen` clears the target's cancelled stage or rolls its gates back per the target type's own playbook (via the `set-stage` verb and `flip-gate --off`) — and every case ends with the originating callout replaced by a `[[...]]` link to the materialized (or linked, or reopened) asset. Materialization never writes a dependency between assets.

**Rejection is clean.** If the containing doc's review rejects it, nothing was ever born — there is nothing to clean up.

**The complete list of asset creators.** The operator, through the product/type/asset creation wizards; and the coordinator, either spawning per a routing decision (Chapter 9) or materializing an approved proposal (this chapter). No expert, no script, no other path creates a spec asset.
