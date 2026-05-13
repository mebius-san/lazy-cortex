---
name: lazy-diagram.draw
description: "Diagram dispatcher — picks (kind, format) for a free-form request, dispatches the per-format drawer agent, byte-compares against the existing fence under the anchor, and writes (or skips) one fenced diagram. Outcome vocabulary: created / replaced / unchanged / skipped-below-threshold / failed:<reason> / split-into-N. Use when you want a NEW diagram inserted under a named heading; for migrating an existing fence to current standards see /lazy-diagram.fix."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList, Agent
---
# lazy-diagram.draw

Decide which drawer agent to call, dispatch it, and place the returned fence under the anchor in `target_file`. The skill knows ZERO about how diagrams are drawn — it owns selection (kind, format), I/O, and idempotence only. All drawing-time invariants (init directives, sanity checks, density bounds) live inside the per-format drawer agents.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Discover available kinds`
   - `Step 3 — Resolve kind and format`
   - `Step 4 — Resolve scheme path`
   - `Step 5 — Format-compatibility check`
   - `Step 6 — Dispatch drawer agent`
   - `Step 7 — Byte-compare and place block`
   - `Step 8 — Report and log`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome line for it". No-ops count only if they produced an explicit outcome word (e.g. `unchanged`, `skipped-below-threshold`, `failed:format-not-supported-for-kind`, `n/a (ascii)`).
3. **Do not reach Step 8 (Report and log) until `TaskList` shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one outcome line per step above. A missing line is a bug; do not render the report with gaps.

## Caller contract

A skill or agent that invokes `/lazy-diagram.draw` is the SEAM AUTHOR. Every calling skill MUST satisfy these four clauses:

### 1. Numbered substep, not trailing sentence

Each invocation is its own numbered substep within the calling skill's Process — never a trailing one-liner. Wrong: "After the prose is written, invoke `/lazy-diagram.draw` ...". Right: a `### Step Xb. Draw <anchor>` substep.

### 2. TaskCreate per seam

The calling skill's preamble MUST include one task per declared invocation, with title of the form `draw-diagram <file>:<anchor>:<kind|auto>`. The task's outcome word is this skill's return value: `created` / `replaced` / `unchanged` / `skipped-below-threshold` / `failed:<reason>` / `split-into-N`.

### 3. Verify section diffs declared seams against run logs

The calling skill MUST include a `## Verify` section that diffs the declared seam set against the seams actually logged to `./.logs/claude/lazy-diagram.draw/`. Any non-empty difference is a verify failure.

### 4. No alternative visual-authoring instructions

A section that has a declared draw seam MUST NOT carry any other visual-authoring template (no "ASCII sketch of the layout", no boxed-text diagrams). The seam invocation IS the artifact.

## Input

The dispatcher provides as keyword=value pairs:

- **`target_file`** *(required)* — absolute path of the markdown file the diagram lands in.
- **`anchor_section`** *(required)* — H2 or H3 heading text the fence anchors under (e.g. `## User Flow`). The heading must already exist in `target_file` — the skill never invents headings.
- **`request`** *(required)* — free-form description of what the diagram should depict. May include a bullet `facts:` list for terminology-parity backstop.
- **`kind`** *(optional)* — pin to one of the available kinds. When unset, Step 3 picks via the inline heuristic.
- **`format`** *(optional)* — `mermaid` | `ascii`. When unset, the inline heuristic decides; defaults to `mermaid` when both formats fit.
- **`scheme`** *(optional)* — colour scheme name. Resolves to `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<scheme>.json`. Defaults to `default`. Ignored for `format=ascii` (ASCII has no palette concept).

## Process

### Step 1: Validate inputs

- Parse the dispatch prompt into the keyword inputs above. Apply defaults.
- `target_file` must exist (`Read` it; `[FAIL] target_file not found` otherwise).
- `anchor_section` must appear verbatim as an H2 or H3 heading in `target_file` (`Grep` for `^#{2,3} <anchor>`; `[FAIL] anchor not found in target_file` otherwise).
- `request` must be non-empty (`[FAIL] empty request` otherwise).
- If `kind` is provided, hold for Step 5 compatibility check.
- If `format` is provided and is not `mermaid` or `ascii`, `[FAIL] unsupported format=<format>`.

Outcome: `validated` (with parsed inputs echoed in Report) or `[FAIL]`.

### Step 2: Discover available kinds

- `Glob: ${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/diagram-*.md` → `available_kinds_mermaid`.
- `Glob: ${CLAUDE_PLUGIN_ROOT}/templates/diagram.ascii/diagram-*.md` → `available_kinds_ascii`.
- Strip prefix `diagram-` and suffix `.md` from each match to get the kind.

Outcome: `discovered (mermaid=<count>, ascii=<count>)`.

### Step 3: Resolve kind and format

- If `kind` AND `format` were pinned by the caller → `pinned-by-caller`. Skip the heuristic.
- Else apply the inline kind heuristic below over `request`. Pick the highest-ranked candidate whose kind appears in the format's available list.

#### Kind heuristic (read top-to-bottom, first match wins)

| Request mentions | Prefer kind | Skip if |
|---|---|---|
| user clicks/submits, validation, decision branches, "if X then Y" | `flow` | <2 decision points AND <4 distinct nodes |
| services / actors exchanging messages, "calls", "responds", "sends" | `sequence` | <2 distinct participants |
| states, lifecycle, "transitions to", "becomes", "enters … state" | `state` | no transition verbs in the request |
| entities + relations + cardinality, persisted records, foreign keys | `erd` | <2 distinct entities |
| classes, interfaces, inheritance, methods, fields | `class` | <2 distinct classes |
| services + data stores + wires, system shape, deployment topology | `architecture` | <3 distinct components |
| UI regions, page sections, "header/sidebar/main" | `layout` | <2 named regions |
| filesystem / directory tree, "folder structure" | `fs-tree` (ascii) | <2 entries |
| navigation hierarchy, screen-to-screen links, sitemap | `nav` | <2 screens |
| timeline of events with absolute dates | `timeline` | <3 events |
| Gantt-style scheduled tasks with start/end | `gantt` | <2 scheduled tasks |
| user journey with phases and emotional beats | `journey` | <2 phases |
| central concept with branching sub-topics | `mindmap` | <3 branches |
| screen-by-screen UI walk-through with annotations | `screen-scheme` | <2 screens |
| controls inventory for a single screen (buttons, inputs, gates) | `controls-scheme` | <3 controls |
| decision tree with branching outcomes | `decision-tree` | <2 branches |
| generic hierarchy / outline / category tree | `tree` | <3 nodes |

When two kinds compete (e.g. "flow vs state machine"), prefer the kind whose **upper bound** the request fits into without splitting. A 6-state lifecycle is a `state` diagram; a 14-step pipeline is two `flow` fences (the drawer will return `split-into-N`).

#### Format heuristic

- `format=ascii` only when the kind is in `available_kinds_ascii` AND the request explicitly says "ASCII", "plain text", "terminal", or asks for a directory tree (`kind=fs-tree`).
- Otherwise `format=mermaid` when the kind is in `available_kinds_mermaid`.
- If the kind is in only one format's list, that format wins regardless of hint.

#### Confirmation

- If the heuristic produces a single confident pick (no tie), use it directly.
- If two kinds tie within the heuristic, OR the user pinned only one of `(kind, format)` and the unpinned axis has multiple plausible values, surface candidates via `AskUserQuestion` (single question, one option per candidate; the first option carries `(Recommended)`).
- If no row in the heuristic matches the request → `failed:no-kind-fits-request`. Short-circuit to Step 8.

Outcome: `resolved kind=<kind> format=<format> source=<pinned-by-caller|heuristic-top|user-confirmed>` or `failed:no-kind-fits-request`.

### Step 4: Resolve scheme path

- For `format=mermaid`: resolve `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<scheme|default>.json`. If the file does not exist → propagate `failed:scheme-not-found:<name>` and short-circuit. The skill does not parse the JSON itself; the drawer agent does. The skill only verifies presence so a missing scheme fails fast at the dispatcher rather than inside the agent.
- For `format=ascii`: skip — ASCII drawers do not consume scheme files.

Outcome: `resolved scheme=<name>` (mermaid) / `n/a (ascii)` / `failed:scheme-not-found:<name>`.

### Step 5: Format-compatibility check

- Verify `${CLAUDE_PLUGIN_ROOT}/templates/diagram.<format>/diagram-<kind>.md` exists. If not → `failed:format-not-supported-for-kind=<kind> in format=<format>`. Hard fail; do NOT silently switch format. Short-circuit to Step 8.

Outcome: `compatible` or `failed:format-not-supported-for-kind`.

### Step 6: Dispatch drawer agent

- Compose the dispatch prompt: `kind=<kind> request=<verbatim request> scheme=<resolved-scheme-name> facts=<extracted bullet list or "none">`. For `format=ascii`, omit the `scheme=` token (ASCII drawers ignore it).
- Dispatch the per-format drawer:
  - `format=mermaid` → `Agent(subagent_type: "lazycortex-diagram:lazy-diagram.draw-mermaid", prompt: "<above>")`.
  - `format=ascii` → `Agent(subagent_type: "lazycortex-diagram:lazy-diagram.draw-ascii", prompt: "<above>")`.
- The agent returns the fence body (without surrounding triple-backticks) OR a `failed:` / `split-into-N:` / `skipped-below-threshold` outcome line.
- If `failed:` → propagate and short-circuit.
- If `split-into-N:` → propagate as the skill's outcome and surface the suggested seam list to the caller; the skill does NOT itself emit multiple fences in v1. Short-circuit.
- If `skipped-below-threshold` → propagate and short-circuit; no fence is written.

Outcome: `drawn (<bytes> bytes)` or `failed:<reason>` or `split-into-N` or `skipped-below-threshold`.

### Step 7: Byte-compare and place block

- `Read: <target_file>`. Locate the `<anchor_section>` heading.
- Compose the *full* fence text:
  - For mermaid: `` ```mermaid\n<body>\n``` ``
  - For ASCII: `` ```text\n<body>\n``` ``
- Look for an existing fence under the anchor matching the resolved `format` (`mermaid` or `text`):
  - **No prior fence** → insert the new fence as the FIRST content block under the anchor heading. Outcome: `created`.
  - **Prior fence, body bytes match** → no-op. Outcome: `unchanged`.
  - **Prior fence, body bytes differ** → replace in place. Outcome: `replaced`.
  - The skill writes one fence per anchor in v1; multi-fence-per-anchor is out of scope. If the host section needs distinct diagrams, the caller splits them into separate subsections.
- Use the `Edit` tool, never overwrite the whole file.

Outcome: `created` / `replaced` / `unchanged`.

### Step 8: Report and log

Render a markdown report. Format:

```
## scan: lazy-diagram.draw

### findings

[INFO] Step 1 — Validate inputs | <outcome>
[INFO] Step 2 — Discover available kinds | <outcome>
[INFO] Step 3 — Resolve kind and format | <outcome>
[INFO] Step 4 — Resolve scheme path | <outcome>
[INFO] Step 5 — Format-compatibility check | <outcome>
[INFO] Step 6 — Dispatch drawer agent | <outcome>
[INFO] Step 7 — Byte-compare and place block | <outcome>

### summary

target_file=<path> anchor=<anchor> kind=<kind> format=<format> outcome=<final-outcome-word>
```

`<final-outcome-word>` is the value the caller's TaskCreate task records: `created` / `replaced` / `unchanged` / `skipped-below-threshold` / `failed:<reason>` / `split-into-N`.

Then write the run log per `./.claude/rules/lazy-log.logging.md`:

1. `Bash: mkdir -p ./.logs/claude/lazy-diagram.draw`
2. `Write: ./.logs/claude/lazy-diagram.draw/<UTC-timestamp>.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input` = the verbatim dispatch prompt) and the report body.

Outcome: `reported-and-logged`.

## Failure modes

- **`/lazy-diagram.draw` aborts: "[FAIL] target_file not found"** — the path passed as `target_file` does not exist on disk → verify the absolute path and create the file before invoking the skill.
- **`/lazy-diagram.draw` aborts: "[FAIL] anchor not found in target_file"** — `anchor_section` does not appear as an H2 or H3 heading in `target_file` → add the heading to the file first, or correct the spelling to match exactly.
- **`/lazy-diagram.draw` aborts: "[FAIL] empty request"** — the `request` parameter was omitted or blank → provide a non-empty description of what the diagram should depict.
- **`/lazy-diagram.draw` aborts: "[FAIL] unsupported format=<format>"** — `format` was pinned to a value other than `mermaid` or `ascii` → use `format=mermaid` or `format=ascii`.
- **Step 3 aborts: "failed:no-kind-fits-request"** — no row in the kind heuristic matched the request → broaden or rephrase the request, or pin `kind=` explicitly.
- **Step 4 aborts: "failed:scheme-not-found:<name>"** — the named scheme file (`styles-<name>.json`) does not exist in the plugin templates → omit `scheme=` to use the default, or verify the scheme name against `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-*.json`.
- **Step 5 aborts: "failed:format-not-supported-for-kind=<kind>"** — no template exists for the requested `(kind, format)` combination → check `${CLAUDE_PLUGIN_ROOT}/templates/diagram.<format>/` for available kinds, or switch format.
- **Step 6 aborts: "failed:<reason>"** — the drawer agent returned a failure (e.g. `missing-in-style:<role>`, request too sparse, template malformed) → check the reason string and re-run with a more detailed request, or fix the named style/template field.
- **Step 6 returns: "split-into-N"** — the request spans multiple logical diagrams; the skill surfaces the suggested seam list but does not emit multiple fences in v1 → split the request into N separate `/lazy-diagram.draw` calls, one per seam.
- **Step 6 returns: "skipped-below-threshold"** — the request is too thin for the kind's lower bound (e.g. `<2` decision points for `flow`) → either rephrase to add more substance, or accept that prose is the better artifact for this section.

## Verify

After Step 8, the calling skill is responsible (per Caller contract clause 3) for diffing its declared seam set against `./.logs/claude/lazy-diagram.draw/<this-run>.md`. The skill itself does not run that diff — it only emits the log entry the caller's verify step will read.
