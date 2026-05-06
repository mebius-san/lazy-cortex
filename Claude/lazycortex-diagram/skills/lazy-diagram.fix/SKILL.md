---
name: lazy-diagram.fix
description: "Take an existing diagram fence and re-conform it to the current drawer-agent standards. Reads the host section's prose as the request, infers (kind, format) from the existing fence's syntax marker, dispatches the per-format drawer agent, and replaces the fence in place when the body differs. Outcome vocabulary: replaced / unchanged / failed:<reason>. Use when an old diagram drifted from the contract (palette removed, theme directive missing, terminology changed); for inserting a NEW fence under a heading see /lazy-diagram.draw."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList, Agent
---
# lazy-diagram.fix

Recompose an existing diagram fence so it satisfies the current drawer-agent contract. Behaves like `/lazy-diagram.draw`, except a fence MUST already exist under the anchor; `(kind, format)` are inferred from the fence's syntax marker when not pinned. The host section's prose IS the request the drawer re-renders against.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs and locate fence`
   - `Step 2 — Infer kind and format`
   - `Step 3 — Extract host-section prose as request`
   - `Step 4 — Resolve scheme path`
   - `Step 5 — Dispatch drawer agent`
   - `Step 6 — Byte-compare and replace`
   - `Step 7 — Report`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome line for it".
3. **Do not reach Step 7 (Report) until `TaskList` shows every prior task `completed`.**
4. **The Report step is a structural verifier.** Output one line per task — gaps are a bug.

## Input

- **`target_file`** *(required)* — absolute path of the file containing the diagram.
- **`anchor_section`** *(required)* — H2/H3 heading the fence sits under.
- **`kind`** *(optional)* — pin if the existing fence is malformed enough that inference fails.
- **`format`** *(optional)* — pin in the same case as kind.
- **`scheme`** *(optional)* — colour scheme name. Resolves to `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<scheme>.json`. Defaults to `default`. Ignored for `format=ascii`.

## Process

### Step 1: Validate inputs and locate fence

- Read `target_file`. `Grep` for `<anchor_section>` (H2 or H3). Within the section's body, locate the FIRST code fence — `` ```mermaid `` or `` ```text `` — and capture its body (between the fences) and the `info-string` (`mermaid` / `text`).
- If no fence is found → `[FAIL] no fence under anchor`. Short-circuit to Step 7.

Outcome: `located fence at line <N>` or `[FAIL]`.

### Step 2: Infer kind and format

- `format`: `mermaid` if info-string is `mermaid`; `ascii` if info-string is `text`. If neither, `[FAIL] cannot infer format from info-string=<X>` (caller must pin).
- `kind`: scan the fence body for a syntax marker:
  - `flowchart` → `flow` (default; if the body contains a `subgraph` block AND the host-section heading mentions architecture/services/components, prefer `architecture`. When ambiguous, default to `flow`).
  - `sequenceDiagram` → `sequence`.
  - `stateDiagram-v2` → `state`.
  - `erDiagram` → `erd`.
  - `classDiagram` → `class`.
  - `block-beta` → `layout`.
  - `gantt` → `gantt`.
  - `journey` → `journey`.
  - `mindmap` → `mindmap`.
  - `timeline` → `timeline`.
  - `architecture-beta` → `architecture`.
  - For ASCII: top-level `<dir>/` line at column 0 → `fs-tree`; box-and-arrow → `flow`; box-only-no-arrow → `layout`.
- Caller-pinned `kind` overrides inference. When inference cannot disambiguate (e.g. `flowchart` body that could be any of `flow|nav|tree|decision-tree|controls-scheme|screen-scheme`), `[FAIL] cannot infer kind from fence syntax — pin kind=<one>` with the candidate list.

Outcome: `inferred kind=<kind> format=<format>` or `[FAIL]`.

### Step 3: Extract host-section prose as request

- The host section's prose (paragraphs between the anchor heading and the existing fence, plus any prose immediately after the fence within the same H2/H3 block) IS the request the drawer should re-render against. Extract it verbatim.
- If the section contains only the fence and no prose, fall back to using the fence's existing node labels and edge labels as the request — `[WARN] no host-section prose; using fence labels as request`.

Outcome: `extracted (<chars>)` or `warned`.

### Step 4: Resolve scheme path

- For `format=mermaid`: resolve `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<scheme|default>.json`. If the file does not exist → `failed:scheme-not-found:<name>`. Short-circuit.
- For `format=ascii`: skip — ASCII drawers do not consume scheme files.

Outcome: `resolved scheme=<name>` (mermaid) / `n/a (ascii)` / `failed:scheme-not-found:<name>`.

### Step 5: Dispatch drawer agent

- Compose the dispatch prompt: `kind=<kind> request=<verbatim host-section prose> scheme=<resolved-scheme-name> facts=none`. For `format=ascii`, omit the `scheme=` token.
- Dispatch the per-format drawer:
  - `format=mermaid` → `Agent(subagent_type: "lazycortex-diagram:lazy-diagram.draw-mermaid", prompt: "<above>")`.
  - `format=ascii` → `Agent(subagent_type: "lazycortex-diagram:lazy-diagram.draw-ascii", prompt: "<above>")`.
- The agent returns the fence body (without surrounding triple-backticks) OR a `failed:` / `split-into-N:` / `skipped-below-threshold` outcome line. Propagate outcomes; on `failed:` or `split-into-N:` short-circuit to Step 7.

Outcome: `drawn (<bytes> bytes)` or `failed:<reason>` or `split-into-N` or `skipped-below-threshold`.

### Step 6: Byte-compare and replace

- Compose the full fence text (with appropriate info-string: `` ```mermaid `` or `` ```text ``).
- Byte-compare against the existing fence body:
  - **Bytes match** → no-op. Outcome: `unchanged`.
  - **Bytes differ** → replace the existing fence in place using `Edit`. Outcome: `replaced`.

Outcome: `unchanged` / `replaced`.

### Step 7: Report

Render a markdown report. Format mirrors `/lazy-diagram.draw` Step 8 with one line per task. The summary line:

```
target_file=<path> anchor=<anchor> kind=<kind> format=<format> outcome=<unchanged|replaced|failed:<reason>>
```

Outcome: `reported`.

### Step 8: Log the run

Per `./.claude/rules/lazy-log.logging.md`:

1. `Bash: mkdir -p ./.logs/claude/lazy-diagram.fix`
2. `Write: ./.logs/claude/lazy-diagram.fix/<UTC-timestamp>.md` with frontmatter and report body.

Outcome: `logged`.

## Failure modes

- **`/lazy-diagram.fix` aborts: "[FAIL] no fence under anchor"** — the anchor section exists in `target_file` but contains no `` ```mermaid `` or `` ```text `` fence → use `/lazy-diagram.draw` instead to create the initial diagram, then re-run fix if drift develops later.
- **`/lazy-diagram.fix` aborts: "[FAIL] cannot infer format from info-string=<X>"** — the existing fence has an unrecognised info-string (not `mermaid` or `text`) → pin `format=mermaid` or `format=ascii` explicitly when calling fix.
- **`/lazy-diagram.fix` aborts: "[FAIL] cannot infer kind from fence syntax"** — the fence's syntax marker matches multiple kinds (e.g. plain `flowchart` could be `flow`, `nav`, `tree`, etc.) → pin `kind=<one>` from the candidate list in the failure message.
- **Step 4 aborts: "failed:scheme-not-found:<name>"** — the named scheme file (`styles-<name>.json`) does not exist → omit `scheme=` to use the default, or check `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-*.json` for valid names.
- **Step 5 aborts: "failed:<reason>"** — the drawer agent returned a failure (e.g. request too sparse, `missing-in-style:<role>`, template malformed) → check the reason string; re-run with a richer host-section prose, or fix the named scheme/template field.
- **Step 5 returns: "split-into-N"** — the host-section prose now spans multiple logical diagrams; fix does NOT split fences in v1 → manually split the section into sub-sections, each with its own fence, and re-run fix per sub-section.
- **Step 5 returns: "skipped-below-threshold"** — the host-section prose is too thin for the inferred kind's lower bound → either expand the prose, or remove the fence (prose alone may be the better artifact).

## Notes

- The fix skill never CREATES a new fence — `/lazy-diagram.draw` is the entry point for that. Fix only touches an already-present fence.
- Use this when bulk-conforming legacy diagrams (e.g. removing palette artifacts from older spec docs that pre-date the current scheme files).
