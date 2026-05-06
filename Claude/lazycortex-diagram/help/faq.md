---
chapter_type: faq
summary: Answers to common questions about kind/format selection, scheme palettes, draw vs fix, ASCII vs mermaid, density bounds, and split behaviour.
last_regen: 2026-05-05
no_diagram: true
source_skills:
  - lazy-diagram.draw
  - lazy-diagram.fix
---
# Frequently asked questions

## How does the dispatcher decide what kind of diagram to produce?

`/lazy-diagram.draw` applies a keyword heuristic to your `request` text. It scans for signal words — actors exchanging messages picks `sequence`; states and lifecycle transitions picks `state`; services and data stores picks `architecture`; UI regions or page sections picks `layout`; and so on. The first matching row in the heuristic wins. If two kinds tie, the dispatcher surfaces both as candidates via a single question and waits for your choice. If no row matches at all, the run ends with `failed:no-kind-fits-request` and you can either rephrase the request or pin `kind=` explicitly.

---

## How does the dispatcher choose mermaid vs ASCII?

The dispatcher defaults to mermaid. ASCII is chosen only when the kind is one that the ASCII writer supports (`flow`, `fs-tree`, `layout`) AND your request explicitly uses a signal word like "ASCII", "plain text", "terminal", or asks for a directory tree. If the kind exists in only one format's template library, that format wins regardless of any hint.

---

## When should I use `/lazy-diagram.draw` vs `/lazy-diagram.fix`?

Use `/lazy-diagram.draw` when the heading has no diagram yet — the skill inserts a new fence under the anchor. Use `/lazy-diagram.fix` when a fence already exists and has drifted from current standards (old palette, missing theme directive, stale labels). Fix reads the existing fence to infer `(kind, format)`, extracts the surrounding prose as the re-render request, and replaces the fence in place only when the body has actually changed. Fix will abort with `[FAIL] no fence under anchor` if there is nothing there to conform — that is the signal to use draw instead.

---

## What is a "scheme" and how do I pass a non-default one?

A scheme is a named JSON file that ships with the plugin and governs the colour palette, init directive, and layout config for every mermaid kind. To use a non-default scheme, pass `scheme=<name>` when calling `/lazy-diagram.draw` or `/lazy-diagram.fix`. The dispatcher resolves the file as `templates/diagram.mermaid/styles-<name>.json`; if the file does not exist the run aborts with `failed:scheme-not-found:<name>`. The available schemes are the ones shipped by the plugin — consumers do not author new scheme files in normal use.

---

## What happens when the dispatcher says "split-into-N"?

The drawer agent returns `split-into-N` when the request would produce a diagram that exceeds the kind's upper-bound density (for example, more than 12 distinct nodes in a flow diagram, or more than 6 participants in a sequence). When this happens, the dispatcher surfaces the suggested seam list and stops — it does not emit multiple fences in a single call. You then run `/lazy-diagram.draw` once per seam, each targeting its own sub-section heading. The seam list in the output tells you where the natural split points are.

---

## What does "skipped-below-threshold" mean?

It means the request is too thin for the chosen kind's minimum requirements. Each kind has a lower bound — for example, a flow diagram needs at least 2 decision points or 4 distinct nodes; a sequence diagram needs at least 2 distinct participants. When the request falls below that threshold the drawer returns `skipped-below-threshold` instead of a fence, and no diagram is written. Either rephrase the request to add more substance, or accept that prose alone is the right artifact for that section.

---

## The drawer returned "failed:format-not-supported-for-kind". What does that mean?

Not every kind is available in both formats. Mermaid supports a wide set of kinds (`flow`, `sequence`, `state`, `erd`, `class`, `architecture`, `layout`, `nav`, `tree`, `controls-scheme`, `decision-tree`, `screen-scheme`, `journey`, `mindmap`, `gantt`, `timeline`). ASCII supports only `flow`, `fs-tree`, and `layout`. If you pin a combination that has no template file — for example `kind=sequence format=ascii` — the dispatcher fails fast at Step 5 before dispatching any agent. Switch to a supported format for the kind, or omit `format=` and let the dispatcher choose.

---

## Why did `/lazy-diagram.fix` abort with "cannot infer kind from fence syntax"?

Several mermaid syntax markers are ambiguous. A `flowchart` body could represent a `flow`, `nav`, `tree`, `decision-tree`, `controls-scheme`, or `screen-scheme` diagram — the syntax is the same; only the intent differs. When fix cannot disambiguate, it lists the candidate kinds and stops. Re-run with `kind=<one>` pinned to the correct value from that list.

---

## Can I embed a diagram inside another skill I am writing?

Yes. Follow the Caller contract in the `lazy-diagram.draw` SKILL.md: declare one TaskCreate task per invocation with a title of the form `draw-diagram <file>:<anchor>:<kind|auto>`, place the invocation as its own numbered substep (not a trailing sentence), and add a Verify section that diffs your declared seams against the run logs written by the dispatcher. A section with a declared draw seam must not carry any other visual placeholder — the seam invocation is the artifact.
