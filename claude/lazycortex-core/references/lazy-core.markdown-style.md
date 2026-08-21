---
description: Markdown output conventions every expert follows when editing a target file, authoring a new doc, or composing a callout — callout shapes, edit-annotation markers, recommendation markers, hard-wrap rules.
routine_protocol_candidate: true
---
# Markdown style

Conventions for any markdown content an expert produces — when it edits a target file, writes a new authored doc, or composes a callout.

## Callouts

Obsidian callouts have a fixed shape:

```
> [!type] Single-line title
> Body line one.
> Body line two if needed.
```

- The first line is ONLY `> [!type] <title>` (optionally followed by a `#tag` cluster). Nothing else on it.
- The title is one line. Never wrap a title across two `>`-prefixed lines — the renderer treats the first `>` line as the title and a wrapped continuation renders inconsistently across viewers.
- The title is a short stub (≤120 chars). The framing prose lives in the body, never in the title.
- Body prose goes on subsequent `>`-prefixed lines, one paragraph per `>`-line.
- Blank line above and below the whole callout block.

Wrong (everything stuffed into the title):

```
> [!question] What drives the choice of defaults — specifically, why are broadcasts off by default while direct messages and mentions are on? The premise establishes... #review/question
```

Wrong (title hard-wrapped across two `>` lines):

```
> [!info] Multi-select. Tick all targets that apply. If empty at
> finalize, the request is rejected.
```

Right:

```
> [!question] What drives the choice of defaults? #review/question
>
> The premise establishes both noise complaints but does not name the
> primary cost direction. Pick the cost the defaults should avoid:
>
> - [ ] ★ Optimise against miss-cost (broadcasts ON by default).
> - [ ] Optimise against noise-cost (broadcasts OFF by default).
```

## Question callouts with discrete answers

When a callout asks the operator a question with a closed answer-set, list candidate answers as `- [ ]` checkbox rows inside the callout body. The operator answers by ticking. This applies to any callout type when the framing is "pick one of these" / "tick all that apply", regardless of `[!type]` (typically `[!question]` with `#review/question`).

Structure:

```
> [!question] <short stub> #review/question
>
> <framing prose, 1–3 short lines>
>
> - [ ] <option A>
> - [ ] <option B>
> - [ ] <option C>
```

Rules:

- One option per `- [ ]` row. Don't pack multiple options into one row with "and / or".
- Options are mutually exclusive unless framing explicitly names multi-select.
- The author never pre-ticks. The operator owns every tick.
- A `- [ ]` row is the only answer signal a consumer can detect — a callout with no options row has no way to be marked answered and blocks silently forever. When the question is genuinely open-ended and discrete options would mislead, ask as plain body prose instead of a callout, never as a callout with no `- [ ]` rows.

## Command callouts

`[!todo] #review/command` is the operator's free-text channel into the review loop — the reverse direction of a question callout: the operator telling the coordinator to act, not the coordinator asking the operator something. Wire form:

```
> [!todo] <short imperative, or blank> #review/command
> free-text instruction from the operator to the coordinator
```

Deliberately not a checkbox: `- [ ]` is reserved for an ask-the-operator gesture, and this callout is the opposite direction.

On waking to a non-empty command, the coordinator unfolds it into a numbered mini-plan written into the **same callout**, so the operator sees the plan before execution starts and can intervene between steps:

```
> [!todo] <short imperative, or blank> #review/command
> free-text instruction from the operator to the coordinator
>
> 1. ✓ <step already done>
> 2. → <step in progress>
> 3. · <step not started>
```

- Progress is a prefix mark at the start of each numbered line — Unicode symbols, never markdown checkboxes (those read as gestures, not progress): `✓` done, `→` in progress, `·` not started.
- A step failing partway stops the whole chain; lock the block with an outcome line naming where it stopped, e.g. `reached step 2, failed at <what failed>`.
- Once every step reads `✓`, or the chain has locked on a failure, the whole block — plan, marks, outcome — moves as one unit into `# History` and the callout is removed, leaving the channel empty again for the next command.

Full behavioural detail (triggers, escalation, how a command runs on an otherwise stuck document) lives in `lazy-review.coordination-playbook.md` Chapter 5; this section owns the shape only.

## Callout and tag registry

Every markup shape an expert or the runtime writes into a document — a callout, a marker, a bare tag — belongs to exactly one **role**: a name protocols, rules, and playbooks reference instead of restating the concrete markup. This registry is the single place that maps each role to its concrete type + tag form, who authors it, and what the block must carry. A protocol or rule names the role; this registry draws it.

Grouped by the surface that writes it. Author is one of the closed set `dispatcher` (a runtime primitive, or the coordinator acting through its closed verb set), `expert` (a writer dispatched against a document), `operator` (a human editing the file by hand).

### Specs

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| Decision statement | `[!decision] #spec/decision` | expert (review writer) | thesis-line title; `**Why.**` line; `**Rejected.**` line; optional `**Supersedes.**` line |
| Decision candidate | `[!decision-candidate]` | expert | one-line thesis naming the call taken; accept/reject `- [ ]` pair |
| Gate flip record | `[!gate]` (flip form) | dispatcher | gate key, `— flipped <date> (<reason>)` |
| Launch checkbox | `[!gate]` (checkbox form) | dispatcher | one label from a closed set; a `- [ ]` / `- [x]` line |
| Halt notice | `[!failure]` | dispatcher | `asset halted: <reason>` |
| Stage mirror tag | `#spec/<stage>` | dispatcher | — |

`[!gate]` carries two forms under one type, not two roles: a flip-record callout the gate primitive appends on every flip, and a launch-checkbox block a human ticks to request the next expert job. The two never collide — a flip record's head line names the gate plus `— flipped …`; a checkbox block's head line is the bare closed-set label, nothing else.

### Requests

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| Waiting banner | `[!hint] #review/in-process` | dispatcher | title line |
| Accepted notice | `[!success] #status/accepted` | dispatcher | — |
| Rejected notice | `[!warning] #status/rejected` | dispatcher | — |
| Request mirror tags | `#request/draft`, `#request/accepted`, `#request/rejected` | dispatcher | — |

### Review — dispatcher banners

State blocks the dispatcher repaints on every wake; never authored by a writer.

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| State block: in process | `[!hint] #review/in-process` | dispatcher | title line |
| State block: finalizing | `[!hint] #review/finalizing` | dispatcher | — |
| State block: action needed | `[!caution] #review/action-needed` | dispatcher | — |
| State block: ready to approve | `[!success] #review/ready` | dispatcher | — |
| State block: outstanding concerns | `[!warning] #review/concerns-decision` | dispatcher | — |

### Review — author-written

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| Operator question with answer options | `[!question] #review/question` | expert | at least one `- [ ]` option row |
| Open concern | `[!attention] #review/concern` | expert | — |
| Non-system commentary | `[!note]`, `[!info]` | expert | — |

### Review — other dispatcher blocks

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| No-concerns marker | `[!check]` | dispatcher | — |
| Error block (dispatcher) | `[!error]` | dispatcher | — |

### Coordinator

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| Operator question with answer options | `[!question]` with `- [ ]` options | dispatcher (coordinator) | attribution line as the block's last quoted line |
| Regression failure notice | `[!attention]` | dispatcher (coordinator) | target name, link to the raised bug |
| Status / rules / commands sections | `# Status brief`, `# Coordinator rules`, `# Coordinator commands` | dispatcher (coordinator) | — |
| Mini-plan progress marks | `✓` / `→` / `·` prefix on numbered lines | dispatcher (coordinator) | never markdown checkboxes |

### Memory

Inventory found no live authored use of `[!recommendation]` — the sole match under `claude/` is an illustrative quote inside `lazy-memory.persona-aspect.md`'s prose, not a writer emitting the shape. No role registered.

### Section ownership

| Role | Type + tag | Author | Mandatory elements |
|---|---|---|---|
| Persistent cross-plugin section | `#protected/<owner>/<region>` as the first content line of an owned H1 | dispatcher (owning plugin) | — |
| Cycle-scoped review section | `#expert/<flat>/<section-id>` as the first content line of an owned H1 | expert (the section's own writer) | — |

### Decision statement shape

```markdown
> [!decision] Short thesis line #spec/decision
> **Why.** Reason the decision follows from.
> **Rejected.** Option X — because Y.
```

A decision that supersedes an earlier one adds a `**Supersedes.**` line naming the prior record by link:

```markdown
> **Supersedes.** [[<path>/decisions#D-007 — thesis|D-007]]
```

The tag makes the block consumer-owned scaffolding: per the edit-annotation rules above, a tagged callout is never wrapped in marker syntax, and is retired by plain deletion, never rewritten in place.

### The `[!asset-proposal]` callout

The single mechanism for proposing a new asset. Any expert may drop one in any document it owns — an architect proposing a child feature in `architecture.md`, a tester proposing a bug in `test-report.md`, a designer proposing a follow-on feature in `design.md`. No expert ever creates an asset directly (`lazy-spec.expert-signals-protocol.md` § Hard prohibitions).

Three forms, selected by the callout's own qualifier:

```
> [!asset-proposal] create
> category: bug
> slug: csv-export-crash
> description: Exporting more than 10k rows crashes with a stack trace in the CSV writer.
```

```
> [!asset-proposal] link
> category: bug
> target: bugs/csv-export-crash
> description: Same stack trace already tracked here — this run reproduces it again.
```

```
> [!asset-proposal] reopen
> category: bug
> target: bugs/csv-export-crash
> description: Regression — the crash returned after yesterday's release.
```

Fields:

- `category` — the target product's declared category (any `products[<key>].asset_types` key, or a built-in `feature` / `change` / `bug`). Open set, not closed to bugs.
- `slug` — only on `create`. A proposed slug; the coordinator may adjust it at materialization time to avoid a collision.
- `target` — only on `link` / `reopen`. The existing asset's `<category>/<slug>` token.
- `description` — a short seed draft in every form. On `create`, this becomes the materialized asset's initial draft content.

**The three-way choice is mandatory for bugs.** A tester proposing a bug searches existing bug assets first and picks `create` (genuinely new), `link` (duplicate — points at an existing open bug), or `reopen` (regression — points at a closed one). Every other category only ever uses `create`, with one exception: an architect decomposing an asset in `architecture.md` may use `link` for any category when an existing asset already covers that part of the decomposition — `target` names the covering asset, `description` states the covering evidence. `reopen` stays bug-only.

**Materialization timing.** The coordinator acts on a proposal only after the CONTAINING document is accepted — ordinary review approval for a living doc (`design.md`, `architecture.md`), the acceptance cycle (`lazy-spec.coordination-playbook.md` Chapter 6) for a report (`code-report.md`, `test-report.md`). A proposal in a document that gets rejected is never materialized — there is nothing to clean up. Once materialized, the coordinator replaces the callout in place with a `[[<path>|<display>]]` wikilink to the resulting (or linked, or reopened) asset.

### The `[!question]` callout (expert-authored)

An expert's own question is a DIFFERENT signal from the coordinator's `[!question]` (which the coordinator drops directly on a folder-note per the playbook's own § 9 — that one is the coordinator talking to the operator). An expert's question lands INSIDE the document it is writing — never on a folder-note, never in a sibling doc — when it hits a gap it cannot resolve on its own (a planner missing a decision, a designer facing an ambiguous requirement).

**The sibling-doc prohibition stays absolute for every expert; it does not apply to the coordinator.** An agent whose own frontmatter carries a `sibling-doc-waiver` field (per the `logging-waiver` naming precedent) is exempt from this "never in a sibling doc" clause, for exactly the act that waiver names — today, only `agents/lazy-spec.coordinator.md` carries one, naming the single act of carrying a planner/architect's question from its own doc into the source doc it concerns and re-submitting that doc (`lazy-spec.coordination-playbook.md` Chapter 11). No expert ever carries this waiver; an audit checking this prohibition may treat a waivered agent's matching act as compliant rather than a violation.

```
> [!question] Should CSV export cap at 10k rows or stream past it?
> - [ ] Cap at 10k, return a truncation notice
> - [ ] Stream unbounded, accept the memory cost
```

The `- [ ]` options are mandatory — Markdown canon reserves an unchecked checkbox for an ask-the-operator gesture, and this callout IS one. After writing the question, the expert re-submits the SAME document into review (the ordinary review conveyor, not a side channel) so the operator receives the question through the normal per-finding review flow and answers it there.

### The `[!decision-candidate]` callout

Marks a call the expert made that its job was never told to make ("used X instead of Y") — a candidate for a decision that REQUIRES the operator's explicit verdict. This is the deliberate inverse of a written `[!decision]`: a decision stands until someone objects, a candidate does not stand until someone accepts it. The two accept/reject checkboxes are mandatory; an unanswered candidate blocks the document's Ready state exactly as an unanswered `[!question]` does. Rejecting with prose written under the callout hands the writer the operator's own decision to fold in. Where it may appear and how the coordinator reacts belong to `lazy-spec.expert-signals-protocol.md` and the coordination playbook; this section owns only the shape.

```
> [!decision-candidate] Used a streaming CSV writer instead of buffering the full export in memory.
> - [ ] accept
> - [ ] reject — I will decide otherwise (my decision in prose below)
```

## Checkbox rows are operator-facing only

A `- [ ]` row is an ask addressed to the operator. It is legal in exactly three places: inside a question callout (above), inside a decision-candidate callout (above), and inside an operator-facing tick-list under its own heading (see the `★` section below). Everywhere else — enumerating alternatives in prose, listing steps, sketching what could be done — use plain bullets.

The vault indexes every checkbox row as a task, so a `- [ ]` written as decoration surfaces in the operator's global task queries alongside real asks, and there is no way to tell them apart after the fact.

## Bare `#` tokens

Any `#` followed by letters, digits, `_`, `-`, or `/` is indexed as a tag by the vault and appears in its tag pane. Write incidental ones in backticks — hex colours (`` `#93c5fd` ``), issue and commit numbers (`` `#5` ``), a tag literal quoted inside prose (`` `#review/ready` ``), reference codes. A run of consecutive numbers is wrapped whole (`` `#10/#11/#12` ``), not one by one — per-token backticks shred the line. Markdown headings and `#` inside fences are unaffected.

Angle-bracket placeholders go in backticks for the same reason: markdown passes raw HTML through, so `<slug>` or `<test name>` written bare is read as an opening tag — the text disappears in reading view and renders as markup in the editor. Inside fenced blocks it is already inert.

An intentional tag is written bare. This rule is about accidental tokens — a `#` that reached the text as part of a number, a colour, a code, a quotation. When the author does mean a tag in that spot, they write it as is and it indexes. Backticks say "this is not a tag"; their absence says "this is one".

## Recommendation markers (`★`)

Whenever the author lists discrete options for the operator to choose from, the author MUST mark at least one option as their recommendation by prefixing it with `★` (Unicode black star, U+2605) placed right after the `- [ ]` checkbox:

```
> - [ ] Option without recommendation
> - [ ] ★ Recommended option
```

This is the author's vote, never a pre-approval — the operator's tick is still the only signal that counts. Zero recommendations is wrong: if the author truly cannot pick, the question is malformed and should be rewritten or dropped.

How many to mark depends on the framing:

| Framing intent | Marker count |
|---|---|
| Single-select ("Pick one", "Which X" with a single noun, "or" between alternatives) | exactly one `★` |
| Multi-select ("Tick all that apply", "Which X apply") | one or more `★` (every option the author would tick themselves) |

When framing is ambiguous, default to single-select.

## Recommendation markers in operator-facing tick-lists outside callouts

The same `★` discipline applies to `- [ ]` lists the author writes OUTSIDE callouts (e.g. a `## Routing` section's checkbox rows): every operator-facing tick-list carries at least one `★`. Lists that are NOT operator-facing tick-lists (plain bullets, prose enumeration) do not use `★`.

## Edit-annotation markers for prose mutations

When an expert revises existing body prose — typo fix, clause swap, paragraph rewrite — the change is rendered with edit-annotation markup so the operator sees what changed before finalize. The consumer chooses the style and passes its name to the expert via a configuration field (e.g. `edit_marker_style`). Four styles are recognised:

```
simple        ~~del~~        ==add==        %%note%%
diff          fenced ```diff``` blocks with line prefixes -  +  !  (two-space context)
criticmarkup  {++add++}      {--del--}      {~~old~>new~~}    {>>note<<}    {==hi==}
html          <ins>…</ins>   <del>…</del>   <mark>…</mark>    <!-- note -->
```

Markers apply to **mutations of existing body prose** only. Plain unmarked replacement of body prose is a protocol violation regardless of size.

**Per-style hard contract.** Each style has exactly one accepted marker shape. Bare changes outside that shape are INVALID — the consumer's finalize-time strip targets the shape verbatim and any drift leaves the markers in the final document.

- `simple` — inline `~~del~~`, `==add==`, `%%note%%` only. No fenced blocks.
- `diff` — every mutation MUST live inside a fenced block:

  ```diff
  - old line
  + new line
  ```

  Bare `-` or `+` lines at the start of a body line OUTSIDE a `` ```diff `` fence are INVALID — they render as list items in the rendered view and survive finalize unchanged.
- `criticmarkup` — inline `{++add++}`, `{--del--}`, `{~~old~>new~~}`, `{>>note<<}`, `{==hi==}` only.
- `html` — inline `<ins>`, `<del>`, `<mark>`, `<!-- note -->` only.

When a consumer dispatches an expert under one of these styles, the expert reads its `edit_marker_style` from `request.json` and locates the matching block above (the `simple` / `diff` / `criticmarkup` / `html` description). This file is the single source of truth for marker shape — no per-request template duplicates it. The expert MUST follow the rules of the named block verbatim.

**No reflow-only markers.** Whitespace-only changes (unwrapping a hard-wrapped paragraph, collapsing blank lines, fixing trailing space) do not earn a marker — they are not a content mutation. Emit the paragraph in its target form raw, without a `` ```diff `` fence or any inline marker. Consumers also defensively strip whitespace-only diff fences before reassembly, so a stray fence is dropped silently — but the rule is "do not emit it in the first place". Touching only the prose you actually mean to change is the discipline; if a paragraph reads correctly as-is, leave its line wrapping alone.

**Tagged callouts are never wrapped in markers.** A callout carrying a tag in any `#<namespace>/<x>` form (`#review/<x>`, `#spec/<x>`, any future consumer's namespace) is consumer-owned scaffolding — the tag itself is the signal "this block is not yours to mark up". Regardless of what edit happens to it (insertion, retention, retirement) and regardless of the configured `edit_marker_style`, a tagged callout is never wrapped in a `` ```diff `` fence, never carries inline `~~del~~` / `{--del--}` / `<del>` markup, never gets any other edit-annotation applied to its block.

Concretely:

- **Inserting a new tagged callout** (e.g. a fresh `[!question] … #review/question` the expert is authoring this round) — written bare. The checkboxes render live, the tag is visible to the consumer's gating predicates, the operator can tick options inside.
- **Keeping an existing tagged callout** — the block stays byte-for-byte where it was. Don't touch.
- **Retiring a tagged callout** (e.g. a resolved `[!question]` whose answer was folded into prose) — the whole block is plain-deleted. No marker, no fence. The accompanying prose change that captured the answer goes through `edit_marker_style` markers as a normal body-prose mutation.

**Wholly new sections** (H1 / H2 headings added where nothing existed before) are also written bare — live content downstream needs to parse.

At finalize time the consumer strips all markers from the chosen style and the prose lands as final text.

### Revising or retiring a marker across rounds

A marker a prior round emitted persists until the operator, or a later round replacing it (cross-fence cancellation below), changes it — silently collapsing an old marker into clean prose is a violation regardless of how the result reads. Per-style shapes for a rejection or revision:

- `diff` — overwrite the `+` line(s) with the desired final text, or delete the fence entirely (drops the proposed change). Re-emitting the fence in a later round MUST NOT regenerate a dropped proposal.
- `simple` / `criticmarkup` / `html` — modify the marker's payload (e.g. change `==add==` to `==revised==`) or delete the span outright. Same re-emission rule.

### Cross-fence `+` / `-` cancellation (`diff` style)

When a later round wants to **replace** prose a prior round introduced with a `+` line, it emits a NEW `diff` fence pairing `- <prior-content>` with `+ <revision>` rather than editing the prior fence in place. The `- <prior-content>` line MUST be byte-for-byte equal to the prior `+` content — no rewrap, no whitespace tidy — exact match is the only cancellation key a consumer's finalize-time resolution recognises. Matching is exact-content only: a writer revising prose whose wording is also slightly reflowed MUST copy the prior content verbatim into its `-` line, or accept that both versions ship as near-duplicates. Matching is also one-shot per `-` line — retracting two prior insertions of the same line takes two separate `-` entries, not one.

## Hard-wraps in prose

Do not hard-wrap paragraph prose at any character width. One paragraph is one line. Obsidian (and every common markdown renderer) soft-wraps by viewport. Hard-wraps inside paragraphs do nothing useful and pollute diffs.

This applies to:
- Authored doc bodies (design.md, plan.md, tech.md, bug.md, request files, …).
- History entries.
- Callout bodies.
- Any other markdown prose the expert writes.

Lists, code blocks, frontmatter, and headings follow normal markdown rules (line breaks are syntactically meaningful there).

## Figures

How a diagram gets into a markdown document — one mechanism for every writer, human-driven skill or dispatched expert. The judgement of WHEN a section deserves a picture belongs to whoever writes it; this section owns only the HOW.

- **Drawing goes through `lazycortex-diagram:lazy-diagram.draw`** (the `Skill` tool), never by composing a mermaid or ASCII fence by hand. Required parameters: `target_file` (the document being written — for a dispatched expert that writes into `result/`, that result copy is the target; the applied file arrives with the fence), `anchor_section` (an EXISTING `##`/`###` heading — the drawer never invents headings), `kind`, `format="mermaid"`, and `request=` one sentence of what the picture depicts followed by `facts:` naming the actors, steps, and decision points the host section's prose just established. Terminology parity with the host section is the only content contract.
- **Re-conforming an existing fence** is `lazycortex-diagram:lazy-diagram.fix`, not a redraw and never a hand edit. A drawer fence is recognisable by the init directive on its first line; a fence without one was composed by hand and should be redrawn through the skill.
- **When to draw at all** — a picture earns its place when the prose carries what a reader reconstructs worse than sees: three or more participants with relations between them, branching with real decision points, or a sequence of exchanges. One or two entities in linear order never earn one.
- **When the skill is absent** (the diagram plugin is not installed, or the drawing skill is not in the listing): write prose and say nothing about it — the absence is a configuration fact for install/doctor tooling, never something a document reports or works around by hand-drawing a fence.

## Formulas

Mathematical formulas in markdown documents are written in Obsidian-compatible LaTeX — `$...$` inline, `$$...$$` for display blocks (e.g. `$P = 1 / (1 + \exp(-x))$`, `$r \in [-1, 1]$`). Plain-text math in prose is the fallback only where a formula is a passing mention, not the content. This is the markdown-side half of a split convention: source code bans LaTeX in docstrings and comments outright — plain prose with backticked identifiers there; the markdown layer is where math renders, so it is where math markup belongs.

## Headings

- The doc's H1 is its title — at most one per file, at the top of the body (after frontmatter).
- Section headings use H2 (`##`); sub-sections H3; nesting deeper than H3 is allowed when the parent section's structure demands it.
- No trailing punctuation on headings.

## Links

Wikilinks (`[[target|display]]`) for vault-internal references — they survive moves. Regular markdown links (`[text](url)`) for external URLs.
