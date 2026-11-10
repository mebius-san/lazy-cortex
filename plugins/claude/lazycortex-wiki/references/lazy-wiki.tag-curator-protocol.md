---
name: lazy-wiki.tag-curator-protocol
version: 1
description: Tag-canon protocol for the wiki.tag-curator expert — payload/result contract for the surface-level normalize-tags job, dispatched via lazycortex-core's expert runtime queue.
---
# lazy-wiki.tag-curator-protocol v1

`<wiki-cli>` stands for the wiki plugin's `bin/lazycortex-wiki` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-wiki/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-wiki/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

Canonical contract for jobs dispatched to `wiki.tag-curator` by `lazycortex-wiki`'s `tag-tick` dispatcher (or any consumer producing tag-curator-shaped jobs). The dispatcher builds the bundle and queues it via `dispatch-job`; the tag curator (C-hybrid, has Bash) hands its judgement to the deterministic `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> tag-apply` verb, which retags the surface, brings the advisory tag-values dictionary in line, commits, and writes the job's response. Which surfaces exist, how often they are ticked, and how the dictionary path is configured are the consumer's concern, out of scope for this wire contract.

**Version 1** carries the `normalize-tags` kind that the `wiki.curator` expert once owned. The kind moved here unchanged in substance; what is new is that a job names a **surface** rather than a scope (a configured wiki scope, or the generated domain-doc tree) and that the advisory dictionary is a second output of the job.

## Request shape (`request.json`)

```json
{
  "kind":           "normalize-tags",
  "surface":        "<surface id>",
  "tag_dictionary": "<repo-relative path of the advisory tag-values dictionary>"
}
```

Field notes:

- `kind` — always `normalize-tags`; see `## Kind enum` below.
- `surface` — the id of the one surface this job canonises: a configured wiki scope id, or the reserved id naming the generated domain-doc tree. The expert passes it verbatim to `tag-apply`, so a surface the verb does not know is a `technical` failure.
- `tag_dictionary` — repo-relative path of the advisory tag-values dictionary `tag-apply` rewrites after the retag. The file is advisory and may not exist yet; the verb creates it in that case.

A job is **surface-level** — nothing is staged in `source/`.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches the expert through its system prompt. This protocol declares only the values `outcome` takes; see `## Outcome by kind` below.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

No extra fields.

## Kind enum

- `normalize-tags` — surface-level: judge a canonical axis-value set from the values currently in use plus those the dictionary already records, emit an alias map that merges synonyms and nests subtypes, and hand it to `tag-apply`, which retags the surface and rewrites the dictionary to the resulting canon. Does NOT touch summaries, connectors, or See-also.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `normalize-tags` | `curated`, `empty`, `error` |

Outcome semantics:

- `curated` — the expert wrote `result/alias_map.json` and applied it. `result` MUST list `result/alias_map.json`.
- `empty` — the census needed no consolidation and the dictionary needed no change. `result` is omitted.
- `error` — the expert failed. `error.category` routes the consumer's response: `logical` (bad input — log and skip); `transient` (claude crash — runner retries); `technical` (schema violation — log and halt).

## Per-kind contents

### `normalize-tags`

- **source/** — nothing; the job is surface-level, not per-node.
- **context/collected_tags.json** — the surface's tag census: per-axis distinct values currently in use, each with its node count and a couple of example node summaries (the `collect-tags` output). The judgement input the expert consolidates into an alias map. Shape: `{"scope": "<surface id>", "axes": {"<axis>": [{"value": "…", "count": N, "examples": ["…"]}, …]}}`.
- **result/alias_map.json** — the expert's canon; see `## Result format` below.
- **result/tag_glosses.json** — the expert's glosses for the values the dictionary does not yet record: `{"<axis>": {"<value>": "<gloss>"}}`, written in the repository's resolved language. A value the alias map renames keeps the gloss of the name it replaces and needs none here; an empty object is valid.

## Result format (`result/alias_map.json`)

```json
{
  "<axis>": {"<old-value>": "<new-value>", ...},
  ...
}
```

The map gives each in-use value its canonical form per axis: merge a synonym (`"food": "coffee"`), nest a subtype (`"espresso": "coffee/espresso"`), or omit a value to leave it unchanged. Values not listed are kept as-is. An empty object (`{}`) is valid — nothing to consolidate. The file is consumed directly by `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> tag-apply <surface> --from result/alias_map.json --glosses result/tag_glosses.json`.

## Side-effect rules

The tag curator is a C-hybrid expert: it has Bash access and is expected to apply its own result. The sequence is:

1. The expert writes `result/alias_map.json` and `result/tag_glosses.json`.
2. It runs `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> tag-apply <surface> --from result/alias_map.json --glosses result/tag_glosses.json --job-dir <job-dir> --repo <repo-root>`. The verb refuses before writing anything when a value the surface will carry has neither a dictionary entry nor a gloss.
3. The verb owns the rest of the sequence: the retag (skipped for an empty map), the dictionary rewrite — its layout and which entries it keeps — the index rebuild for a scope surface, and one commit under the git identity the job's environment carries, so the commit names exactly the files the job wrote.
4. The verb writes `response.json` at the job dir root on every outcome, its refusals included; the expert reads its success from the verb's `"status"`.

- The expert MUST NOT hand-edit node tags or the dictionary — `tag-apply` is the only permitted write path for both.
- The expert MUST NOT touch any other file outside its job dir.
- The expert MUST NOT write back into `context/` — it holds read-only staged copies.

## Attachments

This channel permits no attachments. The curator's whole output is the file it owns plus the
deterministic apply call that writes it; there is nothing to place beside anything.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed: `collected_tags.json` is not a JSON object, or the request names no surface. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | Schema violation in the expert's own output: an alias map that is not `{axis: {old-value: new-value}}`, or a `tag-apply` call refused because the surface id is unknown or a new value has no gloss. |
