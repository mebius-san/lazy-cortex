---
description: How /lazy-diagram.draw and /lazy-diagram.fix split an anchor section into parts and draw one diagram per part when a drawer answers split-into-N.
---
# Section split

When a drawer agent answers `split-into-N: <seams>`, the skill that dispatched it (`/lazy-diagram.draw` or `/lazy-diagram.fix`) splits the anchor section into N parts and draws one diagram per part, in the same run. Nobody is asked: the drawer's density bound has already decided that one picture cannot hold the section, and the seam list says where it breaks.

## 1. Parts

The drawer's seam list gives the parts, in its order. Each part takes a short title naming what its seam covers, in the language of the document's own headings.

## 2. Headings

The anchor heading stays. N headings `<part title>`, one level below the anchor, are inserted directly under it in seam order, ahead of any subheading the section already holds.

## 3. Prose

The section's own body is the text between the anchor heading and the next heading of any level. Every paragraph, bullet and sentence of it moves into the part it describes, word for word:

- a bullet that describes two parts is cut at a sentence boundary, and each half goes to its part;
- a sentence that describes two parts at once stays in the first of them;
- a sentence whose subject was the other half of a cut bullet gets that subject spelled out, and is changed in no other way.

Nothing is reworded beyond that, nothing is dropped, and nothing is added. Text under headings below the section's own body is not touched.

## 4. Old fence

The diagram fence that stood under the anchor, if any, is removed.

## 5. One diagram per part

For each part heading, in order, the skill runs its own dispatch and placement steps again: `anchor_section` is the part heading, the request is the original request narrowed to that part, the facts are the part's prose, and the kind is the one already resolved. Each part ends with its own outcome word from the skill's closed set.

A part whose drawer answers `split-into-N` again is not split further: its outcome is `failed:split-not-converged`, and its prose stays without a diagram.

## 6. Outcome

The skill's own outcome word is `split-into-N`. Its report carries one line per part — the part heading and that part's outcome — and the run log names every part heading, so a caller's Verify step finds a logged seam for each part.
