---
name: lazy-wiki.terms
description: "Use when an expert or a live session is about to name a concept in a document and needs the repository's agreed word for it — the research skill that answers 'what do we call this here?' from the scope's terms dictionary. Two modes: look up one term's definition, or check a name you are about to coin against the terms already taken. Returns only the matching entries, never the whole dictionary; it never writes to the dictionary."
research: true
allowed-tools: Read, Grep, Agent
execution-discipline-waiver: "nested-from-agent — invoked from a writing expert's body mid-document; a numbered step list here would re-anchor the caller and drop its own remaining steps"
logging-waiver: "read-only lookup with no mutations and no decisions — a run log would record only that a word was looked up"
---
# lazy-wiki.terms

The terms dictionary is one markdown file per scope: every `## <term>` section is a term the project has agreed on, and its body is the definition. This skill is how a writer consults it. The point of the dictionary is that one concept never grows a second name, so consulting it before coining a word is the whole discipline — after the document ships, a synonym can no longer be recalled.

Definitions do not enter the caller's context wholesale. The headings come first; only the definitions of the headings that turned out to be candidates are read after.

## Process

**1. Find the scope.** The document's path arrives as the invocation argument — the writer knows where it is writing, this skill does not. `Read` `.claude/lazy.settings.json` and, when present, `.claude/lazy.settings.local.json`, merged the way the runtime merges them: a scalar in the local file replaces the tracked one, arrays are the union. Take the `terms` section's `scopes` map and match the document path against each scope's `paths` globs; the first scope in key order whose globs match wins. No argument, no `terms` section, no scopes, or no scope matching the path — say so out loud and stop. A silent nothing reads as "the dictionary had no answer", which is a different and misleading fact.

**2. Check the file.** The winning scope's `file` key names the dictionary. It does not exist — say so, point the operator at `/lazy-wiki.configure terms`, and stop. Never create it: a quiet recreation hides the loss of every term it held.

**3a. Look up a term.** `Grep` the dictionary for the requested heading and the lines that follow it, and return the definition. The term is absent — say the dictionary does not carry it. That is an answer, not an error; an empty dictionary answers this way to everything.

**3b. Check a name before using it.** This is the mode that keeps synonyms out.

- `Grep` the dictionary for `^## ` with `output_mode: content` — the headings only.
- Pick the candidates: a heading spelled similarly to the name you are about to use, or one whose wording suggests it names the same concept. There is no threshold to apply here; the judgement is semantic and a script cannot make it.
- Pull just those candidates' definitions with a second `Grep`, using `-A` to capture the lines after each heading. **Escape the heading before substituting it into the pattern** — `Grep` has no fixed-string mode, and terms here are dotted and namespaced, so a bare `.` matches any character and a bare bracket either over-matches or fails to compile. Put a backslash before each of `[ ] ( ) { } * + ? | ^ $ \ .`
- Decide against the definitions you read:
  - **no candidate names your concept** — it is new. Use your own word and keep writing; the curator enters it in the dictionary later, reading the finished document.
  - **a candidate names the same concept** — take the existing term exactly as written, even when your word feels better. The better word is a second name for the same thing, which is what the dictionary exists to prevent.
  - **a candidate names a neighbouring concept** — pick a different word for yours, and make the difference readable from your text. Two concepts sharing one name is the same failure from the other side.

**4. When it is genuinely ambiguous, take the existing term.** A dispatched expert has no operator to ask. Two definitions that drifted apart can be merged by the curator afterwards; a new synonym, once spread across documents, cannot be recalled from them.

## The dictionary is not yours to edit

Whatever the answer, this skill and its caller only choose a word for the text being written. Entering a term, widening a definition, or splitting a name in two belongs to the terms curator, which reads the finished document. A writer editing the dictionary mid-sentence decides for the whole repository from inside one paragraph.

When the dictionary and the upstream document a job carries disagree on a name, the dictionary wins — it covers the repository, the upstream chain covers one lineage, and following the chain is exactly how lineages drift apart. Say in your own document that the two disagree; do not resolve it silently.
