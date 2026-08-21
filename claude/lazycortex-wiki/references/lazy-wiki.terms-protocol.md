---
name: lazy-wiki.terms-protocol
version: 1
description: Terms-dictionary protocol for the wiki.terms-curator expert — payload/result contract for the per-document curate job dispatched through lazycortex-core's expert runtime queue, and for the scope-level report dispatch that carries no job dir.
---
# lazy-wiki.terms-protocol v1

Canonical contract for jobs dispatched to `wiki.terms-curator` (or any consumer producing terms-curator-shaped jobs). The dictionary is one markdown file per scope whose every `## <term>` section is a term and whose body is that term's definition. The curator is a C-hybrid expert: it has Bash, edits the dictionary file itself, and commits. Which documents a scope covers, and where its dictionary lives, is consumer configuration — out of scope for this wire contract.

## Request shape (`request.json`)

### `curate` request

```json
{
  "kind":    "curate",
  "role":    "terms-curator",
  "file":    "<repo-relative path of the document that changed>",
  "source":  [{"path": "source/document", "description": "current content of the changed document"}],
  "result":  [{"path": "result/terms.json", "description": "curator output: the dictionary operations it applied"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `file` — the repo-relative path of the document whose change triggered this job. The curator needs the real path, not only the staged copy, because the scope a document belongs to is decided by matching that path against the scope's globs.
- `source/document` — the full raw text of the changed document (frontmatter + body).
- No extra fields.

### `report` dispatch

`report` carries **no job dir**: there is no `request.json`, no `source/`, no `result/`, and no `response.json`. The dispatching skill names the real files and parameters directly in the prompt — the scope id, the dictionary path, and the scope's covered-document globs plus its term-source exclusions — and the curator returns its findings as its reply. This mirrors the agentless dispatch form the wiki curator uses when a live session drives it instead of the daemon.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. Do NOT restate it here. Declare only what is yours:

- the values `outcome` takes — see `## Outcome by kind` below;
- no extra fields beyond the envelope.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

A `report` dispatch writes no `response.json` at all; its findings travel in the agent's reply.

## Kind enum

- `curate` — read one changed document, decide whether it introduced a project entity the dictionary does not name, and apply the resulting dictionary operations. Per-document.
- `report` — read a whole scope and return the divergences between its documents and its dictionary. Scope-level, read-only, no job dir.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `curate` | `curated`, `noop`, `error` |
| `report` | not applicable — no `response.json` |

Outcome semantics:

- `curated` — the dictionary changed and the change is committed. `result` MUST list `result/terms.json`.
- `noop` — nothing to do: the document introduced no entity the dictionary lacks, or it is excluded as a term source. Nothing written, nothing committed, `result` omitted.
- `error` — the expert failed. `error.category` routes the consumer's response.

## Per-kind contents

### `curate`

- **source/** — `source/document`: the full raw text of the changed document.
- **context/** — none. The dictionary itself is a tracked file the curator reads and writes in place; staging a copy would only invite editing the copy.
- **result/** — `result/terms.json`: the operations the curator applied; see `## Result format` below.

### `report`

- No job dir. Inputs are named in the dispatch prompt; findings are the reply.

## Result format (`result/terms.json`)

```json
{
  "operations": [
    {"op": "add",    "term": "<term>",     "definition": "<definition>"},
    {"op": "extend", "term": "<term>",     "definition": "<rewritten definition>"},
    {"op": "split",  "term": "<new term>", "definition": "<definition naming the sibling term>",
     "sibling": "<existing term>", "sibling_definition": "<rewritten definition naming the new term>"}
  ]
}
```

Fields:

- `op` — one of `add` (a term the dictionary did not carry), `extend` (an existing term's definition widened to cover a new shade, name unchanged), `split` (the document introduced a neighbouring concept under a name already taken: a second term is added and both definitions are reworded so the difference is explicit).
- `term` — the section heading, written in the form the scope's documents use.
- `definition` — the section body. At most three physical lines.
- `sibling` / `sibling_definition` — present on `split` only: the existing term whose definition was reworded alongside the new one. Each of the two definitions names the other term, which is how a freshly split term is told apart from a dead one.

An empty `operations` array is not written — a curator with nothing to apply reports `noop` instead.

## Report format

A `report` dispatch returns findings as its reply, one entry per finding, each naming its category, the term or document it concerns, and the two sides of the divergence. Categories:

- `divergence` — a document names a concept with a word other than the dictionary's, including the case of two language forms of one concept;
- `missing` — a document introduces a project entity the dictionary does not carry;
- `duplicate` — two dictionary terms describe one concept;
- `dead` — a term appears in no document of the scope. Never reported for a term whose definition names a sibling term: that is a freshly split term, and its own document rename is already the `divergence` finding.

Format and configuration findings are the dispatching skill's own; the curator neither computes nor returns them.

## Side-effect rules

- The expert MAY edit the scope's dictionary file in place, and commit it under the git identity its environment carries.
- The expert MUST NOT edit the document that triggered the job, or any other document of the scope. A document naming a concept differently from the dictionary is a `report` finding, never a silent rewrite of someone else's text.
- The expert MUST NOT write back to `source/document` — it is a read-only staged copy.
- The expert MUST NOT touch any tracked file except the dictionary, and `.memory/<self>/` where the persona aspect grants it.
- On `report` the expert writes nothing at all.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed or unusable: `source/document` is empty, `file` is absent from the request, the document's path matches no scope, or the dictionary path in the scope's configuration names a file that does not exist. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | The dictionary is in a state the curator may not repair: the heading it would anchor an insertion to appears more than once. Log and skip; repairing duplicate headings belongs to the report side. |
