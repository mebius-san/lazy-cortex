---
name: lazy-wiki.structure-protocol
version: 1
description: Structure-map protocol for the wiki.structure-curator expert — payload/result contract for the per-path curate and rename jobs dispatched through lazycortex-core's expert runtime queue, and for the report dispatch that carries no job dir.
---
# lazy-wiki.structure-protocol v1

Canonical contract for jobs dispatched to `wiki.structure-curator` (or any consumer producing structure-curator-shaped jobs). The structure map is one file per repository, `docs/structure.md` — a tree of `path — description` entries whose nesting mirrors the directory nesting. The curator is a C-hybrid expert: it has Bash, edits the map in place, and commits. Which path classes are described at which depth, and which paths are excluded, is consumer configuration the curator reads from the settings itself — out of scope for this wire contract.

## Request shape (`request.json`)

### `curate` request

```json
{
  "kind":    "curate",
  "role":    "structure-curator",
  "path":    "<repo-relative path that changed>",
  "status":  "<A|M|D>",
  "result":  [{"path": "result/structure.json", "description": "curator output: the map operations it applied"}]
}
```

### `rename` request

```json
{
  "kind":     "rename",
  "role":     "structure-curator",
  "old_path": "<repo-relative path before the rename>",
  "new_path": "<repo-relative path after the rename>",
  "result":   [{"path": "result/structure.json", "description": "curator output: the map operations it applied"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `path` / `status` — (`curate` only) the changed path and its git status letter. `A` and `M` arrive from a changed-files watch, `D` from a deleted-files watch; the two watches feed one kind because the curator's response differs only in direction (enter or update versus remove).
- `old_path` / `new_path` — (`rename` only) both sides of the rename. Both are required: removing the old entry needs the old name, and the two names travel in one request because a rename split into a delete and an add would touch the map twice for one event.
- There is no `source/` — the curator reads the real file (or notices its absence) in the working tree, because the description is derived from live content and a snapshot of one file cannot show the directory around it.
- No extra fields.

### `report` dispatch

`report` carries **no job dir**: no `request.json`, no `result/`, no `response.json`. The dispatching skill names the real things directly in the prompt — the map path, the configured depth profiles, and the exclusions — and the curator returns its findings as its reply. It writes nothing.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. Do NOT restate it here. Declare only what is yours:

- the values `outcome` takes — see `## Outcome by kind` below;
- no extra fields beyond the envelope.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

A `report` dispatch writes no `response.json` at all; its findings travel in the agent's reply.

## Kind enum

- `curate` — apply one path change to the map: enter or update the path's entry (and its directory's entry when the directory's role shifted) on `A`/`M`, remove it on `D`. Per-path.
- `rename` — move one path's entry: remove `old_path`'s entry, enter `new_path` at the depth its class prescribes. Per-rename.
- `report` — read the whole map against the tree and return the divergences. Repo-level, read-only, no job dir.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `curate` | `curated`, `noop`, `error` |
| `rename` | `curated`, `noop`, `error` |
| `report` | not applicable — no `response.json` |

Outcome semantics:

- `curated` — the map changed and the change is committed. `result` MUST list `result/structure.json`.
- `noop` — nothing to do: the path is excluded, or the change did not alter what the map says about it. Nothing written, nothing committed, `result` omitted.
- `error` — the expert failed. `error.category` routes the consumer's response.

## Per-kind contents

### `curate` / `rename`

- **source/** — none; the curator reads the live tree.
- **context/** — none; configuration comes from the settings the curator reads itself.
- **result/** — `result/structure.json`: the operations applied; see `## Result format` below.

### `report`

- No job dir. Inputs are named in the dispatch prompt; findings are the reply.

## Result format (`result/structure.json`)

```json
{
  "operations": [
    {"op": "enter",  "path": "<path>", "description": "<one line>"},
    {"op": "update", "path": "<path>", "description": "<one line>"},
    {"op": "remove", "path": "<path>"}
  ]
}
```

- `op` — `enter` (a path the map did not carry), `update` (an existing entry's description no longer matched), `remove` (the path left the tree, or its entry moved under a rename — a `rename` job produces one `remove` and one `enter`).
- `path` — repo-relative, as it appears in the map.
- `description` — the entry's one-line description; absent on `remove`.

An empty `operations` array is not written — a curator with nothing to apply reports `noop` instead.

## Report format

A `report` dispatch returns findings as its reply, one entry per finding, each naming its category, the path, and both sides where two sides exist:

- `missing-dir` — a directory exists on disk and is absent from the map;
- `missing-file` — a load-bearing file is absent from the map (load-bearing is the curator's judgement, which is why this finding is not deterministic);
- `dead-entry` — the map carries an entry whose path is not on disk;
- `divergence` — an entry's description no longer matches what the path holds;
- `depth` — a path is described at a different depth than its class prescribes.

Configuration findings (exclusions, routine wiring, profile overlaps) are the dispatching skill's own; the curator neither computes nor returns them.

## Side-effect rules

- The expert MAY edit the repository's structure map in place, and commit it under the git identity its environment carries.
- The expert MUST NOT edit any other tracked file — the paths it describes are read-only material, and a missing docstring or README is never "fixed" to improve a description.
- The expert MUST NOT create the map when it is missing: the full build belongs to the rebuild mode of the structure skill, and an incremental job against a missing map is an `error`, not an invitation.
- The expert MUST NOT touch anything outside the job dir except the map, and `.memory/<self>/` where the persona aspect grants it.
- On `report` the expert writes nothing at all.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed or unusable: `path` (or `old_path` / `new_path`) absent from the request, `status` outside `A`/`M`/`D`, or the map file does not exist. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | The map is in a state the curator may not repair: the entry it would anchor an edit to appears more than once. Log and skip; structural repair belongs to the rebuild mode. |
