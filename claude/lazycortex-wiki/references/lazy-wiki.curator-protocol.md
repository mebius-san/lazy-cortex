---
name: lazy-wiki.curator-protocol
version: 4
description: Curation protocol for the wiki-curator expert — payload/result contract for per-node classify and link jobs, and the scope-level normalize-tags job, dispatched via lazycortex-core's expert runtime queue.
---
# lazy-wiki.curator-protocol v4

Canonical contract for jobs dispatched to `wiki-curator` by `lazycortex-wiki`'s dispatcher (or any consumer producing curator-shaped jobs). The dispatcher builds the bundle and queues it via `dispatch-job`; the curator (C-hybrid, has Bash) applies results by running a deterministic `lazycortex-wiki` primitive (`apply-node` for per-node kinds, `retag` for `normalize-tags`) and then commits. Consumer-side state machine, routine triggering, and `topics.md` aggregation are out of scope for this wire contract.

**Version 2** replaced the single `curate` kind with two kinds: `classify` and `link`. **Version 3** is a backward-compatible additive extension: the `classify` result gains an optional `connectors` array, and the `link` request gains an optional `context/candidates.json` input. **Version 4** is also additive: it adds the scope-level `normalize-tags` kind (judge a canonical axis-value set, emit an alias map, self-apply via `retag`), and an optional `context/existing_tags.json` input to `classify` (the values already in use per axis, so the curator reuses an existing value instead of coining a synonym). All defaults are empty — a v2/v3 dispatcher's bundles still validate, and a v2/v3 curator's outputs still apply.

## Request shape (`request.json`)

### `classify` request

```json
{
  "kind":     "classify",
  "role":     "curator",
  "source":   [{"path": "source/node", "description": "current content of the node being classified"}],
  "context":  [
    {"path": "context/tag_axes.json",      "description": "closed list of tag axis names for this scope"},
    {"path": "context/existing_tags.json", "description": "optional: values already in use per axis (anchor); empty/absent on cold-start"},
    {"path": "context/pins.json",          "description": "operator pin declarations for this node"}
  ],
  "result":   [{"path": "result/curation.json", "description": "curator output: wiki_summary and topics"}]
}
```

### `link` request

```json
{
  "kind":     "link",
  "role":     "curator",
  "source":   [{"path": "source/node", "description": "current content of the node being linked"}],
  "context":  [
    {"path": "context/topics.md",       "description": "scope topics index (wiki_role: topics-index); lists all classified nodes by topic"},
    {"path": "context/candidates.json", "description": "optional pre-filtered candidate link targets to verify; empty = none"},
    {"path": "context/pins.json",       "description": "operator pin declarations for this node"}
  ],
  "result":   [{"path": "result/curation.json", "description": "curator output: see_also lines"}]
}
```

### `normalize-tags` request

```json
{
  "kind":     "normalize-tags",
  "role":     "curator",
  "context":  [
    {"path": "context/collected_tags.json", "description": "per-axis distinct values with counts and example summaries (collect-tags output)"}
  ],
  "result":   [{"path": "result/alias_map.json", "description": "curator output: axis-value alias map ({axis: {old-value: new-value}})"}]
}
```

`normalize-tags` is **scope-level** — there is no `source/node`. The `scope_id` travels in `request.json` (the curator needs it to run `retag`).

Field notes:

- `kind` — `classify` or `link`; see `## Kind enum` below.
- `role` — always `curator`; see `## Role vocabulary` below.
- `source/node` — the full current content of the node being processed. For markdown nodes this is the raw file text (frontmatter + body).
- `context/tag_axes.json` — (`classify` only) JSON array of axis name strings from `wiki.scopes[<id>].tag_axes`, e.g. `["domain", "kind", "layer"]`. The curator must only assign topics whose axis appears in this list.
- `context/existing_tags.json` — (`classify` only, optional) the values already in use per axis across the scope, as a JSON object `{<axis>: ["<value>", ...]}` (or the richer `collect-tags` shape, from which the curator reads the value lists). The curator treats it as an **anchor**: when an existing value fits the node, reuse it verbatim rather than coining a synonym. Empty / absent on cold-start (nothing classified yet), in which case the curator chooses freely and a later `normalize-tags` pass consolidates. How it gets populated is the dispatcher's concern, out of scope for this wire contract.
- `context/collected_tags.json` — (`normalize-tags` only) the per-axis distinct values currently in use, each with its node count and a couple of example summaries (the `collect-tags` output). The judgement input the curator consolidates into an alias map.
- `context/topics.md` — (`link` only) the scope's `topics.md` file; gives the curator a full catalog of classified nodes and their summaries, organized by topic axis. The curator uses this to select See-also candidates and copy their summaries as glosses. Exists only after at least one `classify` pass has completed and `build-index` has run.
- `context/candidates.json` — (`link` only, optional) JSON array of repo-relative candidate link-target paths the curator should verify and judge for relevance. When the array is **non-empty**, the curator prioritizes verifying those candidates (still glossing each from `topics.md`); when **empty** (`[]`) or absent, the curator falls back to selecting candidates from `context/topics.md` by content judgment — the v2 behavior. How candidates get populated is the dispatcher's concern, out of scope for this wire contract.
- `context/pins.json` — JSON object with four optional arrays: `pinned_topics`, `unrelated_topics`, `pinned_links`, `unrelated_links`. Values are the raw strings from `wiki_pinned_topics` / `wiki_unrelated_topics` / `wiki_pinned_links` / `wiki_unrelated_links` frontmatter. For `classify`, only `pinned_topics` and `unrelated_topics` are relevant. For `link`, only `pinned_links` and `unrelated_links` are relevant. Empty arrays when no pins are set.

## Response shape (`response.json`)

```json
{
  "outcome": "curated | empty | error",
  "result":  ["result/curation.json"],
  "error":   {"category": "logical | transient | technical", "message": "..."}
}
```

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

No extra protocol-specific response fields.

## Kind enum

- `classify` — classify a single wiki node: produce its one-line summary and topic tags. Does NOT produce See-also links (those require the topics catalog, built after classify-all).
- `link` — build the See-also section for a node using the scope's topics catalog. Does NOT modify summary or topics (those are locked by `classify`).
- `normalize-tags` — scope-level: judge a canonical axis-value set from the values currently in use and emit an alias map that merges synonyms / nests subtypes; self-applied via `retag`. Does NOT touch summaries or See-also. Per-node, not run.

## Role vocabulary

- `curator` — the expert acts as wiki curator for the node: reads the node content and scope context, applies judgment to produce curation output, respects operator pins as vetoes.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `classify` | `curated`, `empty`, `error` |
| `link` | `curated`, `empty`, `error` |
| `normalize-tags` | `curated`, `empty`, `error` |

Outcome semantics:

- `curated` — the expert wrote `result/curation.json` with the node's curation output. `result` MUST list `result/curation.json`.
- `empty` — the expert determined no curation is needed (node content and context did not change in a way that affects output). `result` is omitted. Rare; the dispatcher does not filter before dispatching.
- `error` — the expert failed. `error.category` routes the consumer's response: `logical` (bad input — log and skip); `transient` (claude crash — runner retries); `technical` (schema violation — log and halt).

## Per-kind contents

### `classify`

- **source/node** — full raw text of the node (markdown).
- **context/tag_axes.json** — JSON array of axis name strings.
- **context/pins.json** — JSON object with four arrays: `pinned_topics`, `unrelated_topics`, `pinned_links`, `unrelated_links`. Only `pinned_topics` and `unrelated_topics` are relevant for classify.
- **result/curation.json** — output the curator writes; see `## Result format` below.

### `link`

- **source/node** — full raw text of the node (markdown).
- **context/topics.md** — scope topics index; lists all classified nodes with their summaries organized by topic axis.
- **context/candidates.json** — optional JSON array of repo-relative candidate target paths to verify; empty (`[]`) means none, in which case the curator selects from `topics.md` by judgment.
- **context/pins.json** — JSON object with four arrays. Only `pinned_links` and `unrelated_links` are relevant for link.
- **result/curation.json** — output the curator writes; see `## Result format` below.

### `normalize-tags`

- **context/collected_tags.json** — per-axis distinct values currently in use, with counts and example summaries.
- **result/alias_map.json** — output the curator writes: the axis-value alias map; see `## Result format` below.

## Result format (`result/curation.json`)

The result shape differs by kind.

### `classify` result

```json
{
  "wiki_summary": "<one-line summary of the node>",
  "topics": ["wiki/<axis>/<value>", ...],
  "connectors": ["<short linkable-facet phrase>", ...]
}
```

Fields:

- `wiki_summary` — one-line string, no newlines. The single authoritative description of the node; used verbatim as the gloss when another node links to this one in See-also.
- `topics` — array of tag strings each in the form `wiki/<axis>/<value>` where `<axis>` must be one of the values in `context/tag_axes.json`. One topic per applicable axis (not all axes are mandatory — the curator assigns only axes that apply to this node). `pinned_topics` from `pins.json` must appear; `unrelated_topics` must not appear even if the curator would otherwise include them.
- `connectors` — (optional, default empty) array of short free-text phrases generated from the node's content that expose linkable facets BEYOND the one-line `wiki_summary` — key concepts, entities, or relationships a related node might match on. They are *not* axis-constrained like `topics` and *not* a second summary: where the summary answers "what is this node", a connector answers "what could a reader arrive here FROM". May be empty (`[]`) when the node has no facets worth surfacing beyond its summary. `apply-node` writes them to the `wiki_connectors` frontmatter block (markdown) or the `connectors:` line of the `<wiki>` block (code).

`see_also` MUST NOT appear in a `classify` result.

### `link` result

```json
{
  "see_also": ["- [text](path) — gloss", ...]
}
```

Fields:

- `see_also` — array of ready-to-graft markdown list-item strings. Each string is a complete, valid markdown list item of the form `- [<link-text>](<path>) — <gloss>`. For same-repo targets `<path>` is a repo-relative POSIX path. For cross-repo targets `<path>` uses the `@<repo-key>/path` qualifier. The gloss is the target node's `wiki_summary` as listed in `context/topics.md` (copy verbatim — do not paraphrase). `pinned_links` from `pins.json` must appear; `unrelated_links` must not appear. An empty array is valid when no related nodes are found.

`wiki_summary` and `topics` MUST NOT appear in a `link` result.

### `normalize-tags` result (`result/alias_map.json`)

```json
{
  "<axis>": {"<old-value>": "<new-value>", ...},
  ...
}
```

The map gives each in-use value its canonical form per axis: merge a synonym (`"food": "coffee"`), nest a subtype (`"espresso": "coffee/espresso"`), or omit a value to leave it unchanged. Values not listed are kept as-is. An empty object (`{}`) is valid — nothing to consolidate. The file is consumed directly by `lazycortex-wiki retag <scope> --from result/alias_map.json`.

## Side-effect rules

The curator is a C-hybrid expert: it has Bash access and is expected to apply its result by calling `lazycortex-wiki apply-node` and then committing. The sequence is:

1. The expert writes `result/curation.json` with the appropriate kind-specific fields.
2. The expert runs `lazycortex-wiki apply-node <real-node-path> --from result/curation.json` to apply the result to the node file via the deterministic apply code. `apply-node` writes only the fields present in the JSON (classify fields → `wiki_summary` + `wiki/*` tags + `wiki_connectors`; link fields → See-also section). A missing `connectors` key leaves the node's existing connectors block untouched; an empty array clears it. This call must succeed (exit 0) before the expert proceeds.
3. The expert commits the modified node file with a short, kind-qualified commit message, e.g. `wiki(classify): <node-basename>` or `wiki(link): <node-basename>`.

**For `normalize-tags`** the apply primitive is `retag`, not `apply-node`: the expert writes `result/alias_map.json`, runs `lazycortex-wiki retag <scope_id> --from result/alias_map.json` (which rewrites the aliased `wiki/*` tags across the scope's nodes through the deterministic apply path), then commits, e.g. `wiki(normalize-tags): <scope_id>`. An empty alias map is a no-op — the expert skips the `retag` call and reports `empty`.

The expert MUST NOT hand-edit the node file directly — the `apply-node` call (per-node kinds) and `retag` (normalize-tags) are the only permitted write paths for node content outside the job dir.

- The expert MUST NOT touch any file outside its job dir except via `apply-node` as described above, and via `.memory/<self>/` (granted by the persona aspect).
- The expert MUST NOT write back to `source/node` directly — it is a read-only staged copy.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed: `tag_axes.json` is not a JSON array, `pins.json` is not a JSON object, `source/node` is empty, or the node content is not recognizable as markdown. For `link`: `topics.md` is absent or empty. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | Schema violation in the curator's own output (e.g. `topics` contains an entry whose axis is not in `tag_axes`, or a `link` result contains `wiki_summary`). Log and skip; do not retry. |
