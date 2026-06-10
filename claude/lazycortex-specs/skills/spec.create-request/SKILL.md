---
name: spec.create-request
description: Capture a raw user idea into the vault-wide requests/ inbox as a body-only markdown file. Asks 3-5 wizard questions to clarify before writing. Frontmatter (spec_role, request_status, request_class, status-mirror tags) is added by the spec.request-open routine on the next md-scan tick — this skill writes the body only.
---
# Create Request

Capture a raw user idea into the vault-wide `requests/` inbox. The output is a body-only markdown file at `<vault-root>/requests/<slug>.md` — no frontmatter. The `spec.request-open` routine adds frontmatter on the next md-scan tick (per the new contract in `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md` → "Lifecycle invariants" — the request-handling subsystem is the sole writer of frontmatter).

This skill is the human-facing intake helper. It wraps a 3–5 question wizard around the raw input so the saved body is clearer than the user's first phrasing. The agent then takes over (classify, find candidates, route via either clear-path action or ambiguous-path review cycle).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical list:
   - `Step 0 — Confirm intent + collect raw idea`
   - `Step 1 — Resolve slug`
   - `Step 2 — Wizard refinement (3-5 questions)`
   - `Step 3 — Write body-only file`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not finalise until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**

## Input

The user provides:

- **Raw idea text** — one or more sentences describing what they want. May be vague.
- **Optional title hint** — short label they want as the H1.

## Process

### 0. Confirm intent + collect raw idea

If the raw idea was not supplied with the invocation, ask via `AskUserQuestion`:

> What is the request? Briefly state the idea in your own words.

Use the "Other" input. Accept whatever the user types as the seed input — including vague text. Refinement happens in Step 2.

### 1. Resolve slug

Generate a kebab-case slug from the raw idea (3–6 words, lowercase, hyphen-separated). Confirm with the user via `AskUserQuestion` offering: the generated slug, a shorter variant, a longer variant, and "let me type one" (Other).

If the confirmed slug already exists at `<vault-root>/requests/<slug>.md`, append `-2`, `-3`, … until unique. Slug is the file's identity.

### 2. Wizard refinement (3–5 questions)

Ask 3–5 targeted questions via `AskUserQuestion` (one tool call per question, never batched, per global wizard rule). Pick from the question pool below per relevance to the raw idea — do NOT ask all of them mechanically:

- **Scope**: which part of the system / product does this touch?
- **Outcome**: what will the user see or be able to do that they cannot today?
- **Trigger**: when does this matter — what user action / system event raises the need?
- **Known constraints**: any compatibility / data-migration / timing / dependency concerns?
- **Existing work**: is this related to / extending an existing feature/change/bug? (free text — the agent's `find-candidates` primitive will search regardless)
- **Class hint** (optional): "Is this a feature / change / bug / task / plan / spec?" Skip this question if the raw idea makes the class obvious — the agent's classifier is authoritative.

Each answer is appended to the body as a short prose paragraph. Keep it tight — this is intake, not full design.

### 3. Write the body-only file

Write `<vault-root>/requests/<slug>.md` with the following body shape (NO frontmatter — the agent owns frontmatter):

```markdown
# <title>

<original raw idea text, verbatim>

## Clarified

<one short paragraph per wizard answer, in narrative form>
```

If the user gave structured content (e.g. pasted a complete design doc, a `superpowers:writing-plans` output, a bug report with repro steps), preserve the structure as-is — the agent's body-distribution rules use whole-doc detection (per `spec.request-protocol.md` → "Body distribution rules") and benefit from preserved sections like `## Plan`, `## Design`, `## Repro`. Do NOT flatten or paraphrase structured content into prose paragraphs.

### 4. Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.create-request/<timestamp>.md`. Record:

- Final slug
- Number of wizard questions asked
- Whether the body retained structured content (whole-doc preserved) or was prose-only

## Failure modes

- **`<vault-root>/requests/` does not exist** — create it. The vault-wide inbox is the agent's only location convention.
- **No raw idea provided AND user provides no input** — abort with a clear message; cannot create an empty request.

## Key Rules

- **Body-only output.** This skill writes NO frontmatter. The request-handling subsystem (`spec.request-open` routine at open; `spec.request-apply` at apply) is the sole writer of `spec_role`, `request_status`, `request_class`, and the `request/<value>` mirror tag. (`spec.request-router` runs during the review loop but writes only the body of its routing section, never frontmatter.) Adding frontmatter here would create a write-conflict.
- **Vault-wide inbox.** Files live at `<vault-root>/requests/`, NOT per-product `<spec_path>/requests/`. A request may target multiple products and per-product placement would require duplication.
- **One `AskUserQuestion` per decision.** Slug confirmation and each wizard question are separate calls.
- **Preserve structure.** When the user pastes structured content (plan / design / bug report), keep it intact — the agent's whole-doc detection benefits from it.
- **Never classify.** This skill never sets `request_class`. The `spec.request-classify` primitive runs during the review loop (consumed in memory by `spec.request-router`); the apply gate writes the field to frontmatter post-finalize, derived from the routing section the router settled.
- **Never call `lazy-review.start`.** That is the agent's choice during the ambiguous path. This skill just writes the file and exits.
