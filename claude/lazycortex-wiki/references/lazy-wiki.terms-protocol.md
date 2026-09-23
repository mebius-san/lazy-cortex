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
  "files":   ["<repo-relative path of a document that changed>", "..."],
  "result":  [{"path": "result/terms.json", "description": "curator output: the dictionary operations it applied"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `files` — the repo-relative paths of the documents whose change triggered this job. The curator reads each document at its path in the working tree; the same paths decide which scope the documents belong to, matched against the scope's globs.
- **A request carries a batch, and one document is a batch of one.** A watch groups the documents of one directory into a single job, because a directory's documents describe one subject and their terms are decided against each other rather than one at a time. The singular key `file` remains legal for a consumer dispatching its own terms-curator-shaped jobs; a request carrying it is read as a batch of one, and a request carrying both forms uses the list.
- **The batch is answered as a whole**: every operation the documents produce lands in one `result/terms.json`, followed by one commit of the dictionary. A batch whose documents introduce nothing is a `noop` for the whole batch.
- No extra fields.

### `report` dispatch

`report` carries **no job dir**: there is no `request.json`, no `source/`, no `result/`, and no `response.json`. The dispatching skill names the real files and parameters directly in the prompt — the scope id, the dictionary path, and the scope's covered-document globs plus its term-source exclusions — and the curator returns its findings as its reply. This mirrors the agentless dispatch form the wiki curator uses when a live session drives it instead of the daemon. It is a call from a live session, not a queued job: the pump never sees it, so the response envelope the expert-runtime contract requires of every job does not apply — the findings are the reply itself.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. Do NOT restate it here. Declare only what is yours:

- the values `outcome` takes — see `## Outcome by kind` below;
- no extra fields beyond the envelope.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

A `report` dispatch writes no `response.json` at all; its findings travel in the agent's reply.

## Kind enum

- `curate` — read the changed documents, decide whether they introduced project entities the dictionary does not name, and apply the resulting dictionary operations. Per-batch, one commit.
- `report` — read a whole scope and return the divergences between its documents and its dictionary. Scope-level, read-only, no job dir.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `curate` | `curated`, `noop`, `error` |
| `report` | not applicable — no `response.json` |

Outcome semantics:

- `curated` — the dictionary changed and the change is committed. `result` MUST list `result/terms.json`.
- `noop` — nothing to do: no document in the batch introduced an entity the dictionary lacks, or every one of them is excluded as a term source. Nothing written, nothing committed, `result` omitted.
- `error` — the expert failed. `error.category` routes the consumer's response.

## Per-kind contents

### `curate`

- **source/** — none. The changed document is a tracked file the curator reads at the request's `file` path in the working tree.
- **context/** — none. The dictionary itself is a tracked file the curator reads and writes in place; a bundled copy would only invite editing the copy.
- **result/** — `result/terms.json`: the operations the curator applied; see `## Result format` below.
- **A term enters as a name, not a common word.** When the word has an everyday or a second technical meaning in the scope's language, the heading carries a qualifying noun taken from the definition; a bare word in the source enters under the qualified heading, and an existing bare heading is renamed. The form the documents use governs spelling and language only.
- **The document's `## Terms` section, when it carries one, is read first.** Each `**term** — definition` line there names a candidate outright, with the definition the document gives: a term the dictionary lacks is an `add` candidate, a line whose definition disagrees with the dictionary's is a divergence to record. The rest of the body is read for terms the section omitted.

### `report`

- No job dir. Inputs are named in the dispatch prompt; findings are the reply.

## Result format (`result/terms.json`)

```json
{
  "operations": [
    {"op": "add",    "term": "<term>",     "definition": "<definition>"},
    {"op": "extend", "term": "<term>",     "definition": "<rewritten definition>"},
    {"op": "rename", "term": "<qualified term>", "from": "<bare heading>", "definition": "<definition>"},
    {"op": "split",  "term": "<new term>", "definition": "<definition naming the sibling term>",
     "sibling": "<existing term>", "sibling_definition": "<rewritten definition naming the new term>"}
  ]
}
```

Fields:

- `op` — one of `add` (a term the dictionary did not carry), `extend` (an existing term's definition widened to cover a new shade, name unchanged), `rename` (an existing bare heading rewritten as the qualified name of the same concept, definition kept or tightened), `split` (the document introduced a neighbouring concept under a name already taken: a second term is added and both definitions are reworded so the difference is explicit).
- `term` — the section heading, written in the form the scope's documents use and as a name: a qualifying noun whenever the bare word has an everyday or a second meaning.
- `from` — present on `rename` only: the bare heading the section carried before.
- `definition` — the section body. At most three physical lines.
- `sibling` / `sibling_definition` — present on `split` only: the existing term whose definition was reworded alongside the new one. Each of the two definitions names the other term, which is how a freshly split term is told apart from a dead one.

An empty `operations` array is not written — a curator with nothing to apply reports `noop` instead.

## Report format

A `report` dispatch returns findings as its reply, one entry per finding, each naming its category, the term or document it concerns, and the two sides of the divergence. Categories:

- `divergence` — a document names a concept with a word other than the dictionary's, including the case of two language forms of one concept and the case of a document using the bare head word of a qualified term;
- `missing` — a document introduces a project entity the dictionary does not carry;
- `duplicate` — two dictionary terms describe one concept;
- `dead` — a term appears in no document of the scope. Never reported for a term whose definition names a sibling term: that is a freshly split term, and its own document rename is already the `divergence` finding.

Format and configuration findings are the dispatching skill's own; the curator neither computes nor returns them.

`<wiki-cli>` stands for the wiki plugin's `bin/lazycortex-wiki` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-wiki/<version>/`, or `claude/lazycortex-wiki/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

## Language

Before writing any prose — a `wiki_summary`, a See-also gloss, a term definition, a directory description, a tag gloss — resolve the language the vault stores its notes in: run `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> resolve-language --repo <repo-root>` and write every line in the code the verb returns. The language never arrives in the job payload and is never inferred from the prose already around you: settings are the source of truth, and the verb is how a writer reads them.

The obligation covers shipped boilerplate. A template heading, a seeded stub, or any English scaffolding you keep in the file you write is translated into the resolved language when it differs. When editing prose that already exists, keep its language — never retranslate.

Never translated, in any language: frontmatter keys and values, `wiki/<axis>/<value>` tags and axis names, canonical section headings (`# Topics`, `# Domains`, `# See also`, `# History`), identifiers, file paths, and link targets. A link's display text may be translated; the path before `|` never is.

## Side-effect rules

- The expert MAY edit the scope's dictionary file in place, and commit it under the git identity its environment carries.
- The expert MUST NOT edit the document that triggered the job, or any other document of the scope. A document naming a concept differently from the dictionary is a `report` finding, never a silent rewrite of someone else's text.
- The expert MUST NOT touch any tracked file except the dictionary.
- On `report` the expert writes nothing at all.

## Attachments

This channel permits no attachments. The curator's whole output is the file it owns plus the
deterministic apply call that writes it; there is nothing to place beside anything.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed or unusable: the document at a path in `files` is missing or empty, `files` is absent from the request — the legacy singular `file` remains legal and fails the same way when nothing names a document — the document's path matches no scope, or the dictionary path in the scope's configuration names a file that does not exist. |
| `transient` | Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | The dictionary is in a state the curator may not repair: the heading it would anchor an insertion to appears more than once. Log and skip; repairing duplicate headings belongs to the report side. |
