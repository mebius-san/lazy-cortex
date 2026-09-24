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
  "paths":   ["<repo-relative path that changed>", "..."],
  "status":  "<A|M|D>",
  "result":  [{"path": "result/structure.json", "description": "curator output: the map operations it applied"}]
}
```

### `rename` request

```json
{
  "kind":       "rename",
  "role":       "structure-curator",
  "old_paths":  ["<repo-relative path before the rename>", "..."],
  "new_paths":  ["<repo-relative path after the rename>", "..."],
  "result":     [{"path": "result/structure.json", "description": "curator output: the map operations it applied"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `paths` / `status` — (`curate` only) the changed paths and the git status letter they share. `A` arrives from a new-files watch, `D` from a deleted-files watch; the watches feed one kind because the curator's response differs only in direction (enter or update versus remove). `M` stays a legal value for a consumer that dispatches curator-shaped jobs from its own changed-files watch, but no shipped routine sends it — the map describes the tree's shape, and a content edit never changes that.
- `old_paths` / `new_paths` — (`rename` only) both sides of every rename in the batch, the same length and aligned index by index. Both lists are required: removing the old entry needs the old name, and the two names travel in one request because a rename split into a delete and an add would touch the map twice for one event.
- **A request carries a batch, and one path is a batch of one.** A watch hands every path of one tick to a single job, so the curator is dispatched once per tick rather than once per file — the map's unit of change is the batch, and forty files moved together are one change to it. The singular keys `path`, `old_path` and `new_path` remain legal for a consumer dispatching its own curator-shaped jobs; a request carrying one is read as a batch of one, and a request carrying both forms uses the list.
- **Every path in one request shares one status and one commit.** The batch is applied as a whole: the curator judges each member, folds every resulting operation into one `result/structure.json`, and lands one commit for the map. A member that changes nothing contributes no operation; a request whose members all change nothing is a `noop` for the whole batch.
- There is no `source/` — the curator reads the real file (or notices its absence) in the working tree, because the description is derived from live content and a snapshot of one file cannot show the directory around it.
- No extra fields.

### `report` dispatch

`report` carries **no job dir**: no `request.json`, no `result/`, no `response.json`. The dispatching skill names the real things directly in the prompt — the map path, the configured depth profiles, and the exclusions — and the curator returns its findings as its reply. It writes nothing. It is a call from a live session, not a queued job: the pump never sees it, so the response envelope the expert-runtime contract requires of every job does not apply — the findings are the reply itself.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. Do NOT restate it here. Declare only what is yours:

- the values `outcome` takes — see `## Outcome by kind` below;
- no extra fields beyond the envelope.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

A `report` dispatch writes no `response.json` at all; its findings travel in the agent's reply.

## Kind enum

- `curate` — apply a batch of path changes to the map: enter or update each path's entry (and its directory's entry when the directory's role shifted) on `A`/`M`, remove it on `D`. Per-batch, one commit.
- `rename` — move a batch of entries: remove each old path's entry, enter each new path at the depth its class prescribes. Per-batch, one commit.
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

- `op` — `enter` (a path the map did not carry), `update` (an existing entry's description no longer matched), `remove` (the path left the tree, or its entry moved under a rename — a `rename` job produces one `remove` and one `enter` per renamed path that earned an entry).
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

`<wiki-cli>` stands for the wiki plugin's `bin/lazycortex-wiki` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-wiki/<version>/`, or `plugins/claude/lazycortex-wiki/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

## Language

Before writing any prose — a `wiki_summary`, a See-also gloss, a term definition, a directory description, a tag gloss — resolve the language the vault stores its notes in: run `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> resolve-language --repo <repo-root>` and write every line in the code the verb returns. The language never arrives in the job payload and is never inferred from the prose already around you: settings are the source of truth, and the verb is how a writer reads them.

The obligation covers shipped boilerplate. A template heading, a seeded stub, or any English scaffolding you keep in the file you write is translated into the resolved language when it differs. When editing prose that already exists, keep its language — never retranslate.

Never translated, in any language: frontmatter keys and values, `wiki/<axis>/<value>` tags and axis names, canonical section headings (`# Topics`, `# Domains`, `# See also`, `# History`), identifiers, file paths, and link targets. A link's display text may be translated; the path before `|` never is.

## Side-effect rules

- The expert MAY edit the repository's structure map in place, and commit it under the git identity its environment carries.
- The expert MUST NOT edit any other tracked file — the paths it describes are read-only material, and a missing docstring or README is never "fixed" to improve a description.
- The expert MUST NOT create the map when it is missing: the full build belongs to the rebuild mode of the structure skill, and an incremental job against a missing map is an `error`, not an invitation.
- The expert MUST NOT touch anything outside the job dir except the map.
- On `report` the expert writes nothing at all.

## Attachments

This channel permits no attachments. The curator's whole output is the file it owns plus the
deterministic apply call that writes it; there is nothing to place beside anything.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed or unusable: `paths` (or `old_paths` / `new_paths`) absent from the request — the legacy singular forms `path` / `old_path` / `new_path` remain legal and fail the same way when nothing names a path — `status` outside `A`/`M`/`D`, or the map file does not exist. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | The map is in a state the curator may not repair: the entry it would anchor an edit to appears more than once. Log and skip; structural repair belongs to the rebuild mode. |
