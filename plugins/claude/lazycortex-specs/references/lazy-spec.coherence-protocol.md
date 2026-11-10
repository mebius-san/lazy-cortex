---
name: lazy-spec.coherence-protocol
version: 2
description: Coherence-check protocol for the spec.coherence-checker expert — the request, bucket and result contract of the one job `coherence-dispatch` queues after a spec document is approved, comparing it with its approved neighbours.
---
# lazy-spec.coherence-protocol v2

Canonical contract for jobs dispatched to `spec.coherence-checker` through lazycortex-core's expert runtime queue, where the consumer is the `lazycortex-specs` verb `coherence-dispatch` (or any other consumer producing coherence-shaped jobs). One job compares one approved document with its approved neighbours and returns the contradictions the checked document is a party to. The dispatch names this protocol as `lazycortex-specs:lazy-spec.coherence-protocol`. How the consumer picks the neighbours, and what it does with the result, is out of scope for this wire contract.

## Request shape (`request.json`)

```json
{
  "kind":       "check",
  "role":       "<free-form string transported from the expert's config>",
  "checked":    "<repo-relative path of the approved document>",
  "neighbours": ["<repo-relative path of an approved neighbour>", "..."],
  "source":     [{"path": "source/<basename of checked>"}],
  "result":     [{"path": "result/conflicts.json", "description": "the conflicts found, [] when none"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- The consumer writes no `request` prose: the three fields `kind`, `checked` and `neighbours` are the whole payload, and this contract is the whole instruction.
- `checked` — required string: the repo-relative path of the document whose approval triggered the job.
- `neighbours` — required non-empty list of strings: the repo-relative paths of the approved documents the checked one is compared with — the wiki's neighbours of the document united with its product hierarchy — sorted, never containing `checked`. The list holds only the neighbours that fit the check's text budget of 150 KB (153600 bytes, the size of each neighbour's file on disk at dispatch) — filled with the wiki's neighbours first, then the level documents of the document's own product, then those of its parent and nested products, stopping at the first document that would exceed it — so it can be shorter than the full neighbour set; every document listed is read whole. The neighbours left out are not named to the expert; the consumer records their count itself. The expert reads each listed neighbour from the working tree at that path, as the file stands when the job runs; the job dir holds no copy of it. A document with no neighbours, or none that fits the budget, is never dispatched, and a check already queued for an earlier text of it is cancelled.
- Every document the expert names in its result is one of `checked` or `neighbours`, spelled exactly as here.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. This protocol declares only its values:

- `outcome` takes the values in `## Outcome by kind` below;
- no extra fields beyond the envelope.

`outcome=error` is reserved across all protocols — no `kind` or non-error `outcome` value is named `error`.

## Kind enum

- `check` — compare the checked document with its neighbours and return every contradiction it is a party to.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `check` | `done`, `error` |

- `done` — `result/conflicts.json` is written and `result` lists it. An empty array is `done`, not a separate outcome.
- `error` — the job could not be completed; `error.category` per `## Error categories`.

## Per-kind contents

### `check`

- **source/** — the checked document. Manifest: `source_paths` declares `checked` as a file, so it lands as `source/<basename>`, copied when the pump claims the job.
- **context/** — empty; the job carries no copy of a neighbour. Each neighbour is read from the working tree at the repo-relative path `neighbours` lists, as it stands when the job runs. Neighbours sharing a basename need no renaming, since nothing is copied. The result always names the repo-relative path.
- **result/** — `result/conflicts.json`, below.

## Result format (`result/conflicts.json`)

```json
[
  {"inner": "<repo-relative path>", "with": ["<repo-relative path>", "..."], "essence": "<one short sentence>"}
]
```

- `inner` — the document the entry stands for: `checked` or one of `neighbours`, spelled exactly as in the request.
- `with` — one or more documents of the job that contradict `inner` on this point, each `checked` or one of `neighbours`; never `inner` itself.
- `essence` — one short sentence naming the contradiction, on one line.
- Only conflicts the checked document is a party to: `checked` is either `inner` or in `with` of every entry. A contradiction between two neighbours that the checked document takes no part in is not reported.
- One entry per inner document and per essence. `[]` when nothing contradicts.

## Side-effect rules

- The expert MAY write `result/conflicts.json` and `response.json` inside its job dir.
- The expert MUST NOT edit any file under `source/` or `context/`, or any tracked file in the working tree, and makes no commit.

## Attachments

This channel permits no attachments. The whole output is `result/conflicts.json`.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is unusable: `checked` or `neighbours` is absent or empty, the checked document is missing or empty in `source/`, or a neighbour the request names is missing or empty in the working tree. |
| `transient` | The Claude subprocess crashed or timed out — the runner should retry. |
| `technical` | not used |
