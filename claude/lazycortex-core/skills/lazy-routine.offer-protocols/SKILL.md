---
name: lazy-routine.offer-protocols
description: "Shared configurator helper: discover reference files flagged as routine-protocol candidates, judge which are relevant to a given routine's context from their frontmatter, offer the relevant optional ones to the operator, and union the chosen into the routine's existing protocols list. Invoked as a sub-step from a plugin's install/configure skill via Skill dispatch. The routine config and runtime are untouched apart from the flat protocols list."
execution-discipline-waiver: "nested helper invoked from install/configure skills via Skill dispatch — the parent skill owns step discipline; a MANDATORY preamble here would re-anchor the parent's step pointer (lazy-core.skill-writing § 1.5)"
allowed-tools: Read, Glob, AskUserQuestion, Bash(lazycortex-core *)
---
# lazy-routine.offer-protocols

A configurator that sets up a writer-dispatching routine calls this to offer the operator optional protocol references for that routine. Mandatory protocols are whatever the configurator already seeded into the routine's `protocols` list — they are never analyzed and never offered. This helper only ever appends operator-chosen optional references; it never removes, reorders, or adds a field to the routine config, and the runtime keeps reading the same flat `protocols` list.

## Inputs

Passed as `keyword=value` / flags in the dispatch prompt:

- **`--routine`** *(required)* — the routine key under `routines` in `.claude/lazy.settings.json` whose `protocols` list the chosen references are unioned into.
- **`--context`** *(required)* — one line describing what the routine's writers produce (e.g. `review of authored markdown documents`, `spec design/tech/plan authoring`). This is the yardstick for the relevance judgment in the Process below.

## Process

### Discover candidates

Glob both source roots and `Read` each match's frontmatter:

- `claude/*/references/*.md` — monorepo plugin sources (present only inside the marketplace repo; absent in a consumer install).
- `~/.claude/plugins/cache/**/references/*.md` — installed plugins.

Keep every file whose frontmatter carries `routine_protocol_candidate: true`. For each, record:

- `id` = `<plugin>:<stem>` — `<plugin>` is the path segment under `claude/` (monorepo) or under `…/cache/<registry>/<plugin>/<version>/` (cache); `<stem>` is the filename without `.md`. This is the same string `reference_resolver` resolves.
- `description` = the file's `description` frontmatter (its essence).

Dedupe by `id`, preferring the monorepo hit when the same id appears in both.

### Subtract the routine's current protocols

`Read` `.claude/lazy.settings.json` and take `routines.<routine>.protocols` (absent → empty). The **optional pool** is every discovered candidate whose `id` is NOT already in that list — the mandatory set the configurator seeded is therefore excluded with no analysis.

### Judge relevance — offer only what fits the context

Do NOT offer the whole optional pool. For each optional candidate, read its `description` and decide whether it is genuinely relevant to `--context`. Keep only the relevant ones. A candidate whose essence has nothing to do with what this routine's writers produce is dropped silently — the operator is never asked about it.

If no optional candidate survives the relevance judgment, stop with outcome `no-relevant-candidates`.

### Ask the operator

`AskUserQuestion` with `multiSelect: true` — one option per relevant optional candidate: label = its `id`, description = its `description`. Frame the question as: these are optional protocols the `<routine>` writers may use; pick the ones to attach. The operator may pick none.

### Attach the chosen

For the chosen ids run:

```
Bash(lazycortex-core add-protocols --routine <routine> --ids "<comma-separated-chosen-ids>")
```

The CLI unions them into the routine's existing `protocols` list idempotently (already-present ids are no-ops) and writes `.claude/lazy.settings.json`. If the operator chose none, run nothing.

## Outcome

Return one line to the caller: `attached:<n>` (n ids unioned in) / `declined` (offered but none chosen) / `no-relevant-candidates` (nothing in the pool survived the relevance judgment) / `routine-absent` (the named routine is not registered, e.g. the daemon gate removed it).

## Failure modes

- **Nothing is offered though a candidate exists** — the candidate's `description` was judged irrelevant to `--context`, or it is already in the routine's `protocols`. Both are correct silent drops, not errors.
- **`add-protocols` reports `routine_absent`** — the `--routine` is not registered in `.claude/lazy.settings.json` → the caller should invoke this only after the routine is seeded (and only when it survives any daemon-gate unregister).
