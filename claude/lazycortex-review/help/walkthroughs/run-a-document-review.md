---
chapter_type: walkthrough
summary: Opt a document into the review loop, track round-by-round approval state, and finalize it once every section is signed off.
last_regen: 2026-06-10
diagram_spec:
  anchor: "How the review loop flows"
  request: "Sequence diagram showing: operator runs /lazy-review.start → banner inserted + commit → daemon dispatches expert jobs per section → operator reads suggestions and ticks approve → operator checks status via /lazy-review.status → all sections approved → operator runs /lazy-review.finalize → finalized commit with Doc-Review-Phase: finalize trailer"
  kind_hint: sequence
source_skills:
  - lazy-review.start
  - lazy-review.status
  - lazy-review.finalize
---
# Run a document through the review loop

You have a markdown document — a spec, RFC, or design doc — that needs structured feedback from multiple expert lenses. This walkthrough takes you from the moment you opt that document in, through the round-by-round review cycle, to a clean finalized commit. `/lazy-review.start` opens the loop, `/lazy-review.status` tells you where things stand at any point, and `/lazy-review.finalize` seals the document when every section is approved.

## What you need

- `lazycortex-review` installed in the repo — run `/lazy-review.install` if you haven't yet.
- `lazycortex-core` installed and the expert runtime daemon running — experts are dispatched through its queue.
- At least one review class configured for your document's path — run `/lazy-review.configure` to set one up if this is a new repo or a new file location.
- A git repo with a clean working tree (or at least the target file committed) — each state transition is one commit.

## The journey

### Step 1 — Opt the document in

Run `/lazy-review.start <file>` with the path to your markdown document. The skill atomically writes `review_active: true`, `review_round: 1`, and `approved: false` into the document's frontmatter, inserts a Waiting banner above the first H1, and produces a single commit under your git identity.

If the document is already opted in, the command is a no-op — it exits cleanly without a new commit.

After this step the daemon sees a human commit and begins the first dispatch cycle: one expert job per section, routed according to your review class configuration.

### Step 2 — Wait for expert suggestions to land

The expert runtime processes jobs from the queue and splices suggestions back into the document. You do not need to do anything during this phase. When a section's expert has finished, an edit-annotation marker and an approve checkbox appear in that section.

You can check progress at any time — see Step 3.

### Step 3 — Check the current state

Run `/lazy-review.status <file>` at any point. The skill returns a one-line JSON object with:

- `review_active` — whether the loop is running.
- `review_round` — the current round number.
- `approved` — overall approval state.
- `banner` — the current banner text visible in the document.
- `owners[]` — each section with its assigned expert.

Use this to confirm which sections are still pending before you start reading.

### Step 4 — Read suggestions and tick approve

Open the document in your editor. For each section that has a suggestion from its expert, read the annotation, decide whether to accept it (you may edit the text directly), and tick the approve checkbox for that section.

Repeat for every section in the current round. The daemon monitors approve state; when all sections in a round are approved it automatically advances to the next round (bumping `review_round`) and dispatches the next set of expert jobs.

Run `/lazy-review.status <file>` again after ticking to confirm the state has been picked up.

### Step 5 — Repeat for subsequent rounds

Continue reading suggestions and approving sections across as many rounds as your review class defines. The round counter in the JSON from `/lazy-review.status` tells you exactly where you are. Each round transition is committed automatically by the daemon with a `Doc-Review-*` trailer, giving you a full audit trail in `git log`.

### Step 6 — Finalize the document

Once every section in the final round is approved, run `/lazy-review.finalize <file>`. The skill:

- Folds all edit-annotation markers into the final document text.
- Strips the Waiting banner, approve checkboxes, and system callouts.
- Preserves the `# History` section that the historian built across rounds.
- Sets `review_active: false` in frontmatter.
- Commits with the `Doc-Review-Phase: finalize` trailer.

After this commit the document looks like an ordinary markdown file with no review scaffolding. The `# History` section remains as a human-readable summary of what changed across rounds.

If `/lazy-review.finalize` reports `already finalized: <file>`, the document is already in its final state — no action needed.

## After you're done

The finalized document lives at the same path with no review scaffolding. The `# History` section records what the review cycle produced. The commit log has a `Doc-Review-Phase: finalize` entry as the terminal marker.

To resume a document later (e.g. a follow-up review pass), run `/lazy-review.start <file>` again — it re-opens the loop from `review_round: 1`. The old `# History` section is preserved; the historian appends new entries to it on the next round.

To pause the loop without losing round state, use `/lazy-review.stop <file>` — this sets `review_active: false` but keeps `review_round`, `approved`, and `# History` intact so a later `/lazy-review.start` resumes from where you left off.

## How the review loop flows

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant operator as Operator
  participant cli as lazy-review CLI
  participant daemon as Daemon
  participant experts as Expert Agents
  participant doc as Document

  operator->>cli: /lazy-review.start
  cli->>doc: insert review banner
  doc-->>cli: banner inserted
  cli->>cli: commit banner insertion
  Note over cli,daemon: review session initialised
  cli->>daemon: dispatch expert jobs per section
  daemon->>experts: assign section review job
  experts->>doc: read section content
  doc-->>experts: section text
  experts-->>daemon: suggestions for section
  daemon-->>cli: expert results ready
  cli-->>operator: suggestions available

  loop for each section
    operator->>cli: tick approve on section
    cli->>doc: mark section approved
    doc-->>cli: approval recorded
    cli-->>operator: section approved
  end

  operator->>cli: /lazy-review.status
  cli->>daemon: query approval state
  daemon-->>cli: all sections approved
  cli-->>operator: status — all sections approved

  operator->>cli: /lazy-review.finalize
  cli->>doc: apply finalized changes
  doc-->>cli: changes applied
  cli->>cli: commit with Doc-Review-Phase: finalize trailer
  cli-->>operator: finalized commit created
```
