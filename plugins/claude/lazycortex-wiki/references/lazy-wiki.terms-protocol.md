---
name: lazy-wiki.terms-protocol
version: 2
description: Terms-dictionary protocol for the wiki.terms-curator expert — payload/result contract for the per-batch curate job dispatched through lazycortex-core's expert runtime queue, whose operations change the dictionary directory and the term links of the job's documents, and for the scope-level report dispatch that carries no job dir.
---
# lazy-wiki.terms-protocol v2

Canonical contract for jobs dispatched to `wiki.terms-curator` (or any consumer producing terms-curator-shaped jobs). The dictionary is a directory per scope holding one markdown file per term: the file `<dir>/<stem>.md` carries the title line `# <term>`, a blank line, and the term's definition, with no frontmatter. The stem is derived from the term by the dictionary's one file-name rule; a document points at a term with the wikilink `[[<dir>/<stem>|<text>]]`, whose text is the word as the sentence uses it. The curator is a C-hybrid expert: it has Bash, decides the operations, and hands them to the deterministic `terms-write` verb, which writes the term files and the term links of the documents, commits both in one commit per call, and writes the job's response. Which documents a scope covers, and where its dictionary directory lives, is consumer configuration — out of scope for this wire contract.

## Request shape (`request.json`)

### `curate` request

```json
{
  "kind":           "curate",
  "role":           "terms-curator",
  "files":          ["<repo-relative path of a document>", "..."],
  "include_review": true
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `files` — the repo-relative paths of the documents the job covers. The curator reads each document at its path in the working tree; the same paths decide which scope the documents belong to, matched against the scope's globs.
- `include_review` — optional boolean. `true` lets `terms-write` edit a document whose frontmatter carries `review_active: true`; absent or `false`, such a document is left as it is. A sweep sends `true` only when it is told to, as the migration's sweep is; any other sweep and a watch over changed documents send nothing.
- **A request carries a batch, and one document is a batch of one.** A watch sends every document one tick observed as a single job; a sweep sends the documents of one directory, split into several jobs when they are too large for one. The singular key `file` remains legal for a consumer dispatching its own terms-curator-shaped jobs; a request carrying it is read as a batch of one, and a request carrying both forms uses the list.
- **The batch is answered in one file**: every operation the documents produce lands in one `result/terms.json`, and `terms-write` lands the term files and the documents its accepted operations edit in one commit. The single retry of `## Refused operations and the retry` lands its corrections in a second commit.
- The request names no result file: the result path is always `result/terms.json` (see `## Per-kind contents`). A sweep sends `role`; a watch sends only `kind` and `files`. The runtime adds keys of its own, such as `_dedup_key`, which the curator ignores. No other fields.

### `report` dispatch

`report` carries **no job dir**: there is no `request.json`, no `source/`, no `result/`, and no `response.json`. The dispatching skill names the real files and parameters directly in the prompt — the scope id, the dictionary directory, and the scope's covered-document globs plus its term-source exclusions — and the curator returns its findings as its reply. This mirrors the agentless dispatch form the wiki curator uses when a live session drives it instead of the daemon. It is a call from a live session, not a queued job: the pump never sees it, so the response envelope the expert-runtime contract requires of every job does not apply — the findings are the reply itself.

## Response shape (`response.json`)

The response envelope — `outcome`, `result`, `error` — belongs to the expert-runtime contract and already reaches every expert through its system prompt. Do NOT restate it here. Declare only what is yours:

- the values `outcome` takes — see `## Outcome by kind` below;
- two extra fields on every `curated` and `noop` answer `terms-write` writes once it has read the operations: `refused`, the list of the operations that call refused, in the shape `## Refused operations and the retry` gives, empty when it refused none; and `unsettled`, one `{file, line}` record per term line of a legacy `## Terms` section that still stands in a source document after the call, `line` as written, empty when none stands.

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

A `report` dispatch writes no `response.json` at all; its findings travel in the agent's reply.

## Kind enum

- `curate` — read the job's documents, decide which project entities they name that the dictionary lacks and which uses of dictionary terms still carry no link, and apply the resulting operations. Per-batch, one commit per `terms-write` call.
- `report` — read a whole scope and return the divergences between its documents and its dictionary. Scope-level, read-only, no job dir.

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `curate` | `curated`, `noop`, `error` |
| `report` | not applicable — no `response.json` |

Outcome semantics:

- `curated` — a term file or a document changed and the change is committed, by this call of `terms-write` or by the earlier call of the same job. `result` MUST list `result/terms.json`, and also `result/terms.1.json` once the job kept its first batch there.
- `noop` — neither the dictionary nor any document changed in any call of the job: the documents belong to no dictionary, every one of them is excluded as a term source, or the batch left every file as it was, refused operations included. Nothing committed, `result` omitted.
- `error` — the expert failed. `error.category` routes the consumer's response.

## Per-kind contents

### `curate`

- **source/** — none. The documents are tracked files the curator reads at the request's `files` paths in the working tree.
- **context/** — none. The dictionary directory is tracked; the curator reads its term files in place, and a bundled copy would only invite editing the copy.
- **result/** — `result/terms.json`: the operations the curator applied; see `## Result format` below. An absent file is an empty batch.
- **Scope resolution.** `terms-resolve` prints `{"status": "noop"}` when the documents belong to no dictionary, or one object with these keys:
  - `scope` — the scope id;
  - `dictionary` — the dictionary directory, repo-relative;
  - `sources` — the request's documents that remain term sources; only these are judged, and only these may be named by an operation;
  - `dangling` — one `{file, target, renamed_to}` record per link of a source document into the dictionary directory whose term file does not exist, standing where `terms-write` edits links (a link in a region it leaves alone is not listed): `target` is the link target as written, anchor excluded; `renamed_to` is the stem the term's file carries now when the dictionary's history shows the file was renamed, otherwise `null`;
  - `link_excluded` — the source documents whose text is never edited. They are read for terms; no `relink` or `retarget` names them. One that names only such documents is accepted, edits nothing, and comes back in `terms-write`'s `unmatched` list, the list of `relink` and `retarget` operations that reached no occurrence, and of `relink` operations whose `skip` a document they name could not honour.
- **A title is cased by the term's language.** The rule is the `term` field's in `## Result format`; a dictionary written before the rule is brought to it by the `terms-recase` verb, which recases each title and renames each term file whose name breaks it, moving the links to it with their display text kept. A case-only rename git does not see on a case-insensitive checkout is undone: that file keeps its name and its links.
- **The terms are read from the title lines.** A term is spelled as its file's `# ` line spells it; the file name is a derived stem and may differ from the term.
- **A term enters as a name, not a common word.** When the word has an everyday or a second technical meaning in the scope's language, the title carries a qualifying noun taken from the definition; a bare word in the source enters under the qualified title, and an existing bare title is renamed. The form the documents use governs spelling and language only.
- **Every use of a term carries a link.** Each occurrence of a dictionary term in a source document's prose that has no link yet is named by a `relink` operation; the code places no link by matching the dictionary on its own.
- **A legacy `## Terms` section is closed line by line.** A document written before the dictionary directory may still carry a `## Terms` section of term lines: `term — definition`, the word bold or plain, with or without a list marker, the dash an em dash, an en dash or a hyphen, with spaces around it when the word is plain. A line in another form, a definition after a colon or a table row, is not a term line. Each term line names a candidate with the definition the document gives, and the rest of the body is read for terms the section omitted. `terms-write` removes a term line once the dictionary holds its term, once the line's word is rejected, once an accepted `relink` names that word as its `from` in the document, whether or not an occurrence got a link, or once the batch renames a term away from that word; a section left empty goes with its heading. A term line none of these settles stays, and `terms-write` names it under `unsettled`.

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
     "sibling": "<existing term>", "sibling_definition": "<rewritten definition naming the new term>"},
    {"op": "relink",   "term": "<term>", "from": "<word as it stands in the text>", "files": ["<document>"],
     "skip": ["<fragment of one line holding the word>"]},
    {"op": "retarget", "term": "<term>", "target": "<link target as written>",      "files": ["<document>"]},
    {"op": "reject",   "term": "<word>"}
  ]
}
```

Operations apply in order; a later operation sees the dictionary as the earlier accepted ones left it, so a `relink` may name a term an `add` before it in the same batch created, and is refused in turn when that `add` was refused.

Fields:

- `op` — one of:
  - `add` — a term the dictionary did not carry;
  - `extend` — an existing term's definition widened to cover a new shade, or rewritten to the meaning an approved document now gives the term, name unchanged; a definition may describe a mechanism when that is what the thing is;
  - `rename` — an existing bare title rewritten as the qualified name of the same concept, definition kept or tightened; links to the old term file follow it in every document of the scope `terms-write` may edit, and a link without text takes the words it showed as its text;
  - `split` — the document introduced a neighbouring concept under a name already taken: a second term is added and both definitions are reworded so the difference is explicit;
  - `relink` — every occurrence of the word `from` in the named documents that carries no link becomes a link to the term's file, except an occurrence standing inside a place a `skip` fragment matches;
  - `retarget` — every link in the named documents whose target names the same term file as `target` is pointed at the term's file, its text kept; a link without text takes the words it showed as its text;
  - `reject` — the word does not earn a term: every link to its would-be term file in the job's documents, except a link a `retarget` of the same batch moves, gives way to its text (for a link without text, the last segment of its target, followed by its heading anchor when it has one), and its line in a legacy `## Terms` section is removed.
- `term` — for `add`, `extend`, `rename`, `split`: the title, written in the spelling and the language the scope's documents use and as a name: a qualifying noun whenever the bare word has an everyday or a second meaning. Its letter case follows the term's language, never the sentence it was found in: a term holding a Cyrillic letter is Russian and starts with a capital in its first word only, every proper name inside it keeping its own capital (`Автор раздела`, `Бакет обмена Keystone`); any other term is English and starts every word with a capital (`Quest Board`, `Back-channel`). A token that is no plain word — one holding a character other than a letter, a hyphen or an apostrophe, or a capital after its first letter (`change_gate`, `lazy-diagram.fix`, `iOS`) — keeps its spelling. `terms-write` raises the first letters this rule asks for on every title an `add`, `rename` or `split` writes, so the file name derived from the title carries the same case; it never lowers a letter, so the curator writes the other words of a Russian title in lower case itself. A link to the term keeps the display text its sentence needs; only its target follows the file name. For `relink` and `retarget`: a term the dictionary holds. For `reject`: the word, which must not be a term of the dictionary, nor name one when read as a link target is read — for a word standing as a link, the name the link's target gives (the part of the target after the dictionary directory and its `/`, as `dangling` records it), never the link's display text — a name ending in `.md` also stands for the name without that ending, as a link target written that way does, so the `reject` reaches the links written either way, while a link that names a term of the dictionary is never unwrapped; for a legacy `## Terms` line, the line's bold word. The code compares the word's file name with each link target's, so a `reject` named by an inflected display text removes nothing and is not reported under `unmatched`.
- `from` — on `rename`: the bare title the term carried before. On `relink`: the word exactly as it stands in the text, inflected form included; one operation per form. Matching ignores letter case and requires the word to stand whole on one line; an occurrence broken across a line break is not linked.
- `skip` — on `relink` only, optional: fragments of the documents' text, each standing on one line and holding the word `from` as the operation matches it. An occurrence of `from` inside a place where a fragment matches stays without a link, and a fragment found in several places excludes each of them. A fragment is matched exactly and with letter case, within one line, against the line's source text as written, link markup included. Fragments match the document as it stood before the batch, so a link another operation of the batch renames, retargets or places on the same line never breaks a fragment copied from the file. The text a `reject` of the same batch frees from a link is ordinary prose: an occurrence of `from` in it counts like any other, so a fragment around it keeps it plain, and a fragment that ends inside such a link keeps plain only the part of the freed text it holds. A fragment with no place holding an occurrence the operation would otherwise link — misspelled, gone from the document, or standing only where no link is placed, such as inside a link that stays — keeps that operation off that document: no occurrence of its word is linked there, the batch's other operations still edit the document, and the operation comes back under `unmatched` with that document listed under its `skip_unmatched` key. Such an entry is the curator's error, corrected in the retry like a refused operation; an `unmatched` entry without `skip_unmatched`, a word or target that stands nowhere, is no error. An empty list is the same as no `skip`.
- `target` — on `retarget` only: the link target as the document writes it, as `dangling` names it.
- `files` — on `relink` and `retarget` only: the documents the operation edits, each one of the job's `sources`.
- `definition` — the term file's body. `terms-write` refuses the operation when its form check does not admit the definition, so a definition stays readable at a glance.
- `sibling` / `sibling_definition` — present on `split` only: the existing term whose definition was reworded alongside the new one. `terms-write` refuses a split whose two definitions do not name each other, because that mark is how a freshly split term is told apart from a dead one.

**Two terms whose names give one file name are one term.** An `add` or a `rename` landing on a file name another term already takes is applied as an `extend` of that term: the title standing there stays, the definition sent replaces its definition, and `terms-write` names the joined term in its answer.

An empty `operations` array is a valid batch: `terms-write` still removes legacy `## Terms` lines the dictionary settles and normalises the targets of the term links already standing in the job's documents (a link without text whose target changes takes the words it showed as its text), and answers `noop` when that changes nothing.

## Refused operations and the retry

`terms-write` judges each operation on its own. An operation that breaks a rule of the result format is refused: an unknown `op` or a missing or malformed key (a `files` that is present but not a list of document paths is malformed, not missing), a `definition` or `sibling_definition` over the line limit, a split whose definitions do not name each other or that names itself as its sibling, an operation on a term the dictionary does not hold at that point of the batch, a `reject` of a dictionary term or of a name that names one when read as a link target, a `relink` or `retarget` naming a document outside the job's `sources` (a document is compared in its plain repo-relative form, so `./specs/a.md` is the source `specs/a.md`, and only a path whose plain form is no source is refused), a `skip` on an operation other than `relink`, a `skip` that is not a list of non-empty strings, a fragment that does not hold the word `from` or that carries a line break, a term that gives no file name. The other operations of the batch are applied and committed. A refused operation leaves the dictionary exactly as it was before it, and nothing downstream of the dictionary sees it: the link edits, the operation count, the commit subject, `merged`, and the links that follow a renamed term come from the accepted operations only.

Two or more `relink` operations whose `from` is the same word, letter case and runs of whitespace aside, that name the same document are all refused, each with a reason naming the document; order never picks one sense of a word.

Each refused operation is reported as `{"index": <zero-based position in the submitted operations>, "operation": <the operation as submitted>, "reason": "<why>"}` in the `refused` list of `response.json` and of the verb's outcome line. A batch whose operations are all refused and that changes nothing answers `noop` with its `refused` list; that alone is no error of the job.

The curator corrects its own errors once, inside the same job:

- A call hands back its refused operations, its `unmatched` entries that carry `skip_unmatched`, its `unsettled` lines, and a `result/terms.json` it cannot use at all — unreadable, not a JSON object, or with an `operations` value that is not a list of objects, answered as an `error` of category `technical` with nothing written.
- The first call that hands anything back copies the submitted file to `result/terms.1.json`, records in the marker `terms-retry.json` at the job dir root that the retry is open, and says `"retry": "open"` in its outcome line. Each operation it refused and each `skip_unmatched` entry it left is recorded at once in the lazycortex-core error ledger as a `plugin_error` with the cause `terms-operation-refused`, under one incident per scope and document of the job: an operation under each document it names that is one of the job's documents, an operation that names none of them under every document of the job, and a `skip_unmatched` entry under each document it lists. Each `unsettled` line is a failure of its own: it is recorded the same way, with the cause `terms-legacy-line-unsettled`, under the incident of its scope and the document it stands in, apart from the incident of refused operations. A document is compared in its plain repo-relative form, so `./specs/a.md` is `specs/a.md`, and a named document outside the job gets no incident. A retry that never comes thus stays visible there. The marker, the copy, `response.json` and the outcome line are written before anything reaches the ledger. A report the ledger does not take never changes the call's answer, and once one report of a call runs out of time the call sends no further report. The curator then writes a `result/terms.json` holding only its corrections and calls `terms-write` once more. The first call has already placed links and rewritten link targets, so a correction is made from the documents as they stand after it: a `skip` fragment, a `reject` name or a `retarget` target copied from the earlier reading may no longer match.
- A call that finds the retry recorded as open in the marker is final, whichever run of the job makes it, and says `"retry": "final"`. Nothing it refuses is handed back again: each operation it still refuses, each `skip_unmatched` entry and each `unsettled` line it still leaves is recorded the same way, each under its own cause, and those incidents stay open. A final call whose `unsettled` list is not empty does not end the job as `curated`: the curator replaces `response.json` with an `error` of category `logical` that names each line still standing, and the commits already landed stay.
- Every call closes the incident of each of its documents under which it records nothing, each cause on its own: a document under which it refuses nothing and leaves no `skip_unmatched` entry has its refused-operation incident closed, and a document in which it leaves no `unsettled` line has its unsettled-line incident closed. A call that leaves none of them, a final one included, closes the incidents of all its documents. A call never closes the incident of a document that is not its own.
- The marker records two facts of the job, apart from each other: whether its retry is open, and whether any of its calls committed. Every call that commits records the commit, whether or not a retry is open, so a job the runtime runs again after a commit still answers as one that committed, and a refused operation on such a run opens the retry only when none was opened before.
- Once a call of the job has committed, the verb's answer stays `curated`, and only the curator's `error` for `unsettled` lines after a final call replaces it: a later call that changes nothing writes `curated` into `response.json`, while its own outcome line still reports `noop`, and a later call refused as a whole for any reason other than a `transient` one also answers `curated`, since the commit stands, and records its refusal in the error ledger as a `plugin_error` with its own cause `terms-batch-refused`, under one incident per scope and document of the job, which a later call over that document that refuses nothing closes. A call that fails before its documents resolve to a scope, and a `transient` refusal, still answer `error`; the runtime records the first and runs the job again after the second.
- A whole-batch `transient` refusal records nothing in the marker and spends no retry; a job the runtime runs again after one keeps the marker it already has.

## Report format

A `report` dispatch returns findings as its reply, one entry per finding, each naming its category, the term or document it concerns, and the two sides of the divergence. Categories:

- `divergence` — a document names a concept with a word other than the dictionary's, including the case of two language forms of one concept and the case of a document using the bare head word of a qualified term;
- `missing` — a document introduces a project entity the dictionary does not carry;
- `duplicate` — two dictionary terms describe one concept;
- `dead` — no document of the scope links to the term's file and none of them uses its word. Never reported for a term whose definition names a sibling term: that is a freshly split term, and its own document rename is already the `divergence` finding.

Format and configuration findings are the dispatching skill's own; the curator neither computes nor returns them.

## Side-effect rules

- The expert changes the dictionary and the documents only through `terms-write`: the term files, the term links, the removal of legacy `## Terms` lines, the checks behind a refused operation, and the commit are the verb's, and the commit carries the git identity the job's environment holds, so the change is attributed to the curator and to nothing else.
- `terms-write` edits the job's source documents, and other documents of the scope only to make links follow a renamed or joined term. It never edits a document listed in `link_excluded`, a mirror document, a folder note, a document inside a dictionary directory or the generated domain tree, a document with uncommitted changes, or, without `include_review`, a document under an open review round. Inside a document it leaves alone the frontmatter, fenced blocks, foreign protected sections, heading lines, callout titles, checkbox lines, HTML comments, inline code, markdown links, other wikilinks, and bare web addresses (from `http://` or `https://` to the next whitespace). It never links a part of a hyphenated compound: a hyphen in any of its forms, a soft hyphen included, directly beside the word on either side keeps it plain; a dash (en dash, em dash, minus sign), beside the word or with spaces around it, is not a join; and a term whose own name carries a hyphen is linked whole.
- The expert MUST NOT edit a document or a term file itself. A document naming a concept differently from the dictionary is a `report` finding, never a silent rewrite of someone else's text.
- The expert MUST NOT touch any other tracked file.
- On `report` the expert writes nothing at all.

## Attachments

This channel permits no attachments. The curator's whole output is its operations plus the
deterministic apply call that writes them; there is nothing to place beside anything.

## Error categories

| Category | Used when |
|---|---|
| `logical` | Input is malformed or unusable: the document at a path in `files` is missing or empty, `files` is absent from the request — the legacy singular `file` remains legal and fails the same way when nothing names a document. A dictionary directory that does not exist is no error: it is an empty dictionary, and the first term file written creates it. |
| `transient` | Claude subprocess crashed or timed out, a term file the batch would write carries uncommitted changes, or a write or the commit failed and was rolled back in full — the runner should retry. |
| `technical` | The batch is refused as a whole and nothing is written: `result/terms.json` unreadable, not a JSON object, or with an `operations` value that is not a list of objects (handed back once, see `## Refused operations and the retry`), a repository with no commit yet, or a rollback that could not restore every path. After an earlier call of the same job committed, such a refusal of a call whose documents resolved to a scope answers `curated` and is recorded in the error ledger instead. An error of a single operation, such as a missing key or a `files` that is not a list of document paths, is no error of the job: that operation is refused and the rest are applied. Log and skip. |
