---
name: lazy-wiki.terms
description: "Use when an expert or a live session is about to name a concept in a document, or to link a document's uses of terms, and needs the agreed word and its link target — the research skill that answers 'what do we call this here?' from the scope's terms dictionary. It looks up one term, checks a name about to be coined, or lists the scope's terms with their targets."
research: true
allowed-tools: Read, Grep, Agent
execution-discipline-waiver: "nested-from-agent — invoked from a writing expert's body mid-document; a numbered step list here would re-anchor the caller and drop its own remaining steps"
---
# lazy-wiki.terms

The terms dictionary is a directory per scope with one markdown file per term: the file's `# <term>` title line is a term the project has agreed on, and the text under it is the definition. A document points at a term with the wikilink `[[<dir>/<stem>|<text>]]`, where `<dir>/<stem>` is the term file's path without `.md` and `<text>` is the word as the sentence uses it. This skill is how a writer consults the dictionary and how it learns the link target of a term. The point of the dictionary is that one concept never grows a second name, so consulting it before coining a word is the whole discipline — after the document ships, a synonym can no longer be recalled.

Definitions do not enter the caller's context wholesale. The titles come first; only the files of the terms that turned out to be candidates are read after.

## Process

**1. Find the scope.** The document's path arrives as the invocation argument — the writer knows where it is writing, this skill does not. `Read` `.claude/lazy.settings.json` and, when present, `.claude/lazy.settings.local.json`, and resolve the scope by the rule `terms-resolve` applies — the merged settings layers, then the first scope in key order that names a `dir`, carries no `legacy_file`, and whose `paths` globs match the document. Unlike `terms-resolve`, this step skips the `source_exclude` check: a document excluded as a term source is still served by the dictionary, so it gets its answer here. A document matching one of the scope's `link_exclude` globs — an operator's request is the usual case — keeps its text verbatim: answer its writer with words and definitions only, return no link target in any mode, and say why; its writer places no term link. No argument, no `terms` section, no scope matching the path, or a matching scope that still carries `legacy_file` (its dictionary has not been migrated to a directory yet) — say so out loud, say that no dictionary serves this document so it gets no term links, and stop. A silent nothing reads as "the dictionary had no answer", which is a different and misleading fact. A caller that finds no `/lazy-wiki.terms` skill at all, or an older one that names no `dir`, places no term links either.

**2. Read the titles.** `Grep` the scope's `dir` for `^# ` with `output_mode: content`. Each match is one term file and its title; the link target of that term is `<dir>/<file name without .md>` — the scope's `dir` as the settings write it, without a trailing `/`, plus the file's name, never the absolute path `Grep` prints, which the code does not recognise as a term link. The term is the title as spelled there, never the file name: the file name is derived from the title and may differ from it. No match at all, or no directory at all — the dictionary is empty: git keeps no empty directory, so a scope without terms yet has none. Go on with no titles: every lookup answers that the term is absent, every name checked is new and gets its link target from the file-name rule, and a list is empty. Never create anything: the dictionary is not yours to edit.

**3a. Look up a term.** Find the requested term among the titles, ignoring letter case, then `Read` its file and return the definition and the link target `<dir>/<file name without .md>`. The term is absent — say the dictionary does not carry it. That is an answer, not an error; an empty dictionary answers this way to everything.

**3b. Check a name before using it.** This is the mode that keeps synonyms out.

- Pick the candidates among the titles from step 2: a title spelled similarly to the name you are about to use, or one whose wording suggests it names the same concept. There is no threshold to apply here; the judgement is semantic and a script cannot make it.
- `Read` just those candidates' files for their definitions.
- Decide against the definitions you read:
  - **no candidate names your concept** — it is new. Use your own word and keep writing; the curator enters it in the dictionary later, reading the finished document. Its link target does not exist yet; build it with the file-name rule below, under `<dir>`.
  - **a candidate names the same concept** — take the existing term exactly as written, even when your word feels better, with its link target. The better word is a second name for the same thing, which is what the dictionary exists to prevent.
  - **a candidate is the qualified name of the concept you were about to call by its bare head word** (`input field` when you were about to write `field`) — the same concept: take the qualified term. The bare word is the everyday word the term was qualified to escape, not a shorter synonym.
  - **a candidate is a bare common word standing for a project entity** — a title a reader could take for its everyday meaning — write the qualified form in your document and give it the link target the file-name rule builds for the qualified form; the bare title is not named anywhere in your document. The curator renames the bare title to the qualified one, and the link resolves; the dictionary is not yours to edit.
  - **a candidate names a neighbouring concept** — pick a different word for yours, and make the difference readable from your text. Two concepts sharing one name is the same failure from the other side.

**3c. List the terms of a document.** Given a document path, return every title from step 2 with its link target — the whole list of the scope that serves the document, not a matched slice. A writer uses it to bring every use of a term in the document up to a link, including text it did not change.

**The file-name rule** turns a term into the `<stem>` of its file, for a term the dictionary does not carry yet: bring the term to its composed Unicode form; replace each of `/ \ : * ? " < > | # ^ [ ]` and each control character from U+0000 to U+0008 and from U+000E to U+001B, together with the whitespace around it, by one hyphen (tab, line breaks and U+001C to U+001F count as whitespace, U+007F is kept); shrink each whitespace run to one space; cut dots, hyphens and spaces from both ends; when the part before the first dot is a Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, any letter case), append `-term` to that part. The target is `<dir>/<stem>`. A link to a file that does not exist yet stays unresolved until the curator adds the term, and that is the mark that it has not passed yet.

**4. When it is genuinely ambiguous, take the existing term.** A dispatched expert has no operator to ask. Two definitions that drifted apart can be merged by the curator afterwards; a new synonym, once spread across documents, cannot be recalled from them.

## The dictionary is not yours to edit

Whatever the answer, this skill and its caller only choose a word and its link for the text being written. Entering a term, widening a definition, renaming or splitting a term belongs to the terms curator, which reads the finished document. A writer editing the dictionary mid-sentence decides for the whole repository from inside one paragraph.

When the dictionary and the upstream document a job carries disagree on a name, the dictionary wins — it covers the repository, the upstream chain covers one lineage, and following the chain is exactly how lineages drift apart. Your document carries no note about it: a reader of your document has no use for another document's word, and the curator's report mode finds the upstream document on its own.
