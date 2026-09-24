---
description: How a document-authoring expert adds a diagram to the document it is writing — when a diagram earns its place, how to request one through the lazy-diagram.draw engine, and how to react to each outcome. Companion to lazy-core.markdown-style (prose shape) for the visual half of the document.
routine_protocol_candidate: true
---
# Diagram authoring (for writers)

Guidance for an expert that authors or revises a markdown document and may want a diagram in it. It does NOT describe how diagrams are drawn — the `lazycortex-diagram:lazy-diagram.draw` engine owns every drawing-time invariant (init directives, density bounds, sanity checks, colour scheme). This reference covers only the writer's side: deciding a section deserves a diagram, requesting one, and folding the result into the document.

## When a diagram earns its place

Add a diagram only when a section's content is inherently *structural* and a picture carries the structure better than a paragraph: a control/decision flow, a message exchange between actors, a state lifecycle, an entity-relation model, a system/architecture topology, a UI layout or navigation map, a directory tree. Prose stays the primary artifact — a diagram supplements a section that already explains itself in words; it never replaces the explanation.

Do NOT force a diagram onto thin content. If a section names fewer elements than the kind's lower bound (e.g. a "flow" with one decision point, an "architecture" with two components), the engine will return `skipped-below-threshold` and write nothing — that is the correct outcome, not a failure to work around. One or two boxes are better said in a sentence.

A document section carries at most one diagram. If a section needs two distinct pictures, split it into two subsections, each with its own heading, and request one diagram per subsection.

## How to request one

Invoke the engine through the `Skill` tool — never hand-author a ```mermaid``` or ```text``` fence. Hand-drawn fences miss the engine's theme directive, density bounds, and sanity rules, and drift from every other diagram in the vault.

```
Skill(skill: "lazycortex-diagram:lazy-diagram.draw", args:
  "target_file=<absolute path to the document you are writing>
   anchor_section=<an H2 or H3 heading text that ALREADY exists in the document>
   request=<one or two sentences describing what the diagram depicts> facts: <bullet list of the exact actors / steps / states named in the prose>
   kind=<optional: flow|sequence|state|erd|class|architecture|layout|nav|tree|fs-tree|timeline|gantt|journey|mindmap|screen-scheme|controls-scheme|decision-tree>
   format=<optional: mermaid|ascii — omit to let the engine choose; defaults to mermaid>")
```

Required inputs and their constraints:

- **`target_file`** — the document under authorship, as an absolute path.
- **`anchor_section`** — the heading the fence anchors under. It MUST already exist in the document as an H2 or H3 heading; the engine never invents headings. So write the section heading (and its prose) first, then draw under it.
- **`request`** — free-form description of what to depict, optionally followed by a `facts:` bullet list. Omitting `kind` lets the engine pick from the request via its own heuristic; pin `kind` only when you are sure.

## Terminology parity (the one rule that makes the diagram match the prose)

The `facts:` bullets are the terminology backstop: list the actors, steps, and states using the *same words* the surrounding prose uses. A diagram whose node labels diverge from the body text reads as a different document. If the prose says "intake queue" and "validator", the facts say "intake queue" and "validator" — not "input buffer" and "checker".

## Reading the outcome

The skill returns exactly one outcome word. React, do not retry blindly:

- **`created` / `replaced` / `unchanged`** — the fence is in the document. Done. The engine wrote it in place via `Edit`; treat that write as part of your own work and include it in your commit (sub-skill writes are your writes, per the expert-runtime contract).
- **`skipped-below-threshold`** — the section was too thin for the kind. Leave the prose as the artifact; do not coerce a diagram.
- **`split-into-N`** — the request spanned several logical diagrams. The engine wrote nothing and returned a suggested seam list. Restructure the section into N subsections and call the skill once per seam — never paste a multi-diagram blob by hand.
- **`failed:<reason>`** — the draw could not complete (no kind fits the request, scheme missing, request too sparse, template error). Leave the section as prose. Do NOT hand-draw a substitute fence to "fix" it; surface the reason if the failure is unexpected.

## Side effects and boundaries

The engine edits only the one fence under the named anchor in `target_file`. It does not touch frontmatter, other sections, or any protected section. It is idempotent: re-requesting the same diagram under the same anchor returns `unchanged`. Everything else in the document — prose, callouts, protected regions owned by other plugins — remains the writer's and other owners' responsibility, untouched by the draw.
