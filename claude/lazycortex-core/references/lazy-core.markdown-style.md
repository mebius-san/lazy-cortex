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
- Use prose body (no `- [ ]` rows) only when the question is genuinely open-ended and discrete options would mislead.

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

When a consumer dispatches an expert under one of these styles, the request payload carries `edit_marker_template` — a verbatim copy-paste example of the only accepted marker shape for that style. The expert MUST follow that template verbatim. The descriptive prose here is the human-facing source of truth; the per-request `edit_marker_template` is the machine-readable contract.

**No reflow-only markers.** Whitespace-only changes (unwrapping a hard-wrapped paragraph, collapsing blank lines, fixing trailing space) do not earn a marker — they are not a content mutation. Emit the paragraph in its target form raw, without a `` ```diff `` fence or any inline marker. Consumers also defensively strip whitespace-only diff fences before reassembly, so a stray fence is dropped silently — but the rule is "do not emit it in the first place". Touching only the prose you actually mean to change is the discipline; if a paragraph reads correctly as-is, leave its line wrapping alone.

**Tagged callouts are never wrapped in markers.** A callout carrying a tag in any `#<namespace>/<x>` form (`#review/<x>`, `#spec/<x>`, any future consumer's namespace) is consumer-owned scaffolding — the tag itself is the signal "this block is not yours to mark up". Regardless of what edit happens to it (insertion, retention, retirement) and regardless of the configured `edit_marker_style`, a tagged callout is never wrapped in a `` ```diff `` fence, never carries inline `~~del~~` / `{--del--}` / `<del>` markup, never gets any other edit-annotation applied to its block.

Concretely:

- **Inserting a new tagged callout** (e.g. a fresh `[!question] … #review/question` the expert is authoring this round) — written bare. The checkboxes render live, the tag is visible to the consumer's gating predicates, the operator can tick options inside.
- **Keeping an existing tagged callout** — the block stays byte-for-byte where it was. Don't touch.
- **Retiring a tagged callout** (e.g. a resolved `[!question]` whose answer was folded into prose) — the whole block is plain-deleted. No marker, no fence. The accompanying prose change that captured the answer goes through `edit_marker_style` markers as a normal body-prose mutation.

**Wholly new sections** (H1 / H2 headings added where nothing existed before) are also written bare — live content downstream needs to parse.

At finalize time the consumer strips all markers from the chosen style and the prose lands as final text.

## Hard-wraps in prose

Do not hard-wrap paragraph prose at any character width. One paragraph is one line. Obsidian (and every common markdown renderer) soft-wraps by viewport. Hard-wraps inside paragraphs do nothing useful and pollute diffs.

This applies to:
- Authored doc bodies (design.md, plan.md, tech.md, bug.md, request files, …).
- History entries.
- Callout bodies.
- Any other markdown prose the expert writes.

Lists, code blocks, frontmatter, and headings follow normal markdown rules (line breaks are syntactically meaningful there).

## Headings

- The doc's H1 is its title — at most one per file, at the top of the body (after frontmatter).
- Section headings use H2 (`##`); sub-sections H3; nesting deeper than H3 is allowed when the parent section's structure demands it.
- No trailing punctuation on headings.

## Links

Wikilinks (`[[target|display]]`) for vault-internal references — they survive moves. Regular markdown links (`[text](url)`) for external URLs.
