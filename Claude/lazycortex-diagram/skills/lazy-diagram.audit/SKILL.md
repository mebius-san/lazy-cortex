---
name: lazy-diagram.audit
description: "Audit the lazycortex-diagram plugin: verify template well-formedness, exemplar conformance against the authoring rule, and role + init-block coverage in styles-*.json schemes. Parallel-scan coordinator dispatching 3 read-only Explore agents (A2, A3, A5). Read-first; presents findings, asks before fixing. Severity: PASS / WARN / FAIL / INFO. TODO: re-add fixture-related scans (A1, A4) when the final dev-vs-shipped split is decided."
allowed-tools: Read, Glob, Grep, Bash, TaskCreate, TaskUpdate, TaskList, Agent, AskUserQuestion, Edit, Write
---
# lazy-diagram.audit

Audit the `lazycortex-diagram` plugin for template well-formedness and contract conformance on exemplars. Read-first; nothing is mutated until the user approves.

This skill is a **parallel-scan coordinator** per `lazy-core.skill-writing § 5`. Phase 1 dispatches Explore agents in a single message; Phase 2+ merges their structured reports.

> TODO: fixture-side scans (A1 fixture-template coverage, A4 fixture freshness) were removed because the dev-vs-shipped split for `tests/diagram/` is still unsettled. Re-add when that split is finalized.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executor MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Pre-flight`
   - `Step 2 — Dispatch A2–A3 + A5 in parallel`
   - `Step 3 — Merge structured reports`
   - `Step 4 — Present unified report`
   - `Step 5 — Ask which to fix`
   - `Step 6 — Apply confirmed fixes`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it".
3. **Do not reach Step 4 (Present unified report) until `TaskList` shows steps 1–3 `completed`.** Reports without merge are a bug.
4. **The Step 4 report is a structural verifier.** Its output MUST contain one section per A2 / A3 / A5 finding plus a summary line.

## Step 1: Pre-flight

- Confirm the plugin's installPath via `~/.claude/plugins/installed_plugins.json`. If absent → `[FAIL] plugin not installed`. Stop.
- Capture `${CLAUDE_PLUGIN_ROOT}` for the dispatch prompts in Step 2.

Outcome: `asserted (root=<path>)` or `[FAIL]`.

## Step 2: Dispatch A2–A3 + A5 in parallel

In a SINGLE assistant message, dispatch three `Agent` calls with `subagent_type: "Explore"` and `mode: "dontAsk"`. Each agent's prompt embeds the structured-report contract from `claude/lazycortex-core/references/lazy-core.parallel-scan.md`. Word budget: under 300 words per agent.

### A2 — Template well-formedness

> Scope: `<root>/templates/diagram.*/diagram-*.md`.
>
> For each template, verify (a) frontmatter parses and contains `kind:` + `purpose:`, (b) body has `## Idioms` H2, (c) for mermaid templates only: body has `## Roles` H2 and `## Color binding` H2, (d) body has `## Exemplar` H2, (e) `## Exemplar` contains exactly one fenced code block, (f) the code block's info-string matches the format folder (`mermaid` for `templates/diagram.mermaid/`, `text` for `templates/diagram.ascii/`).
>
> Missing section or info-string mismatch → `FAIL`. Frontmatter parse error → `FAIL`. Multiple fences in `## Exemplar` → `WARN`.
>
> Return the structured `## scan: A2-template-wellformedness` block.

### A3 — Contract conformance on exemplars

> Scope: `<root>/templates/diagram.*/diagram-*.md`.
>
> For each mermaid exemplar fence, verify the structural sanity-check items the drawer agent enforces (see `claude/lazycortex-diagram/agents/lazy-diagram.draw-mermaid.md` § sanity checks). Init directive content is not applicable in templates — templates ship structure-only and the drawer composes the directive from the scheme; the init check runs at fixture time, not template time. Items checked:
>
> - **No single-letter IDs**: every node, participant, state, entity, class, region ID is camelCase / PascalCase domain vocabulary.
> - **Every edge labelled**: no unlabelled edges (bare `-->`, bare `->>`, etc.).
>
> Additionally for mermaid templates:
>
> - The `## Exemplar` fence's first non-blank line MUST be the literal `<<init>>` sentinel. Any other init literal (a `%%{init:` line, a `themeVariables` block, etc.) anywhere in the file → `FAIL` — init lines must live in `styles-*.json:blocks.init.<kind>` only.
> - Any literal style value anywhere in the template → `FAIL` — literals must live in `styles-*.json` only. Detection regexes:
>   - Hex colours: `#[0-9a-fA-F]{3,8}\b` (covers `#fff`, `#ffffff`, `#ffffff80`).
>   - Pixel sizes: `\b\d+(\.\d+)?px\b`.
>   - Raw `themeCSS`-shaped strings: any `themeCSS` token anywhere in the file body.
>   - Mermaid layout-config keys quoted as literal values: any of `'?diagramPadding'?\s*:\s*\d`, `'?padding'?\s*:\s*\d`, `'?diagramMarginX'?\s*:\s*\d`, `'?diagramMarginY'?\s*:\s*\d`, `'?topPadding'?\s*:\s*\d`, `'?leftPadding'?\s*:\s*\d`, `'?rightPadding'?\s*:\s*\d`, `'?leftMargin'?\s*:\s*\d`, `'?fontSize'?\s*:\s*\d`. (These are scheme-owned; templates must not pin them.)
>   - Literal `'theme':\s*'base'` anywhere in the file → `FAIL` (forbidden by the drawer agent's OUTPUT CONTRACT and sanity check 8; must not leak into template prose either).
> - Any `classDef` / `class <id> <role>` / per-element `style <id>` line in the `## Exemplar` fence → `WARN` — exemplars are structure-only.
>
> False-positive guard: hex/CSS regex matches inside fenced code blocks marked `\`\`\`json` are part of an example/illustrative scheme snippet, not a template literal — exempt those matches from FAIL but emit `INFO` so an author can verify the snippet is genuinely illustrative and not a smuggled scheme.
>
> Each violation → severity above with file:line.
>
> Return the structured `## scan: A3-exemplar-conformance` block.

### A5 — Role + init-block coverage in styles-*.json

> Scope: `<root>/templates/diagram.mermaid/styles-*.json` and every `<root>/templates/diagram.mermaid/diagram-*.md` (frontmatter `kind:` + `## Color binding` + `## Roles` sections).
>
> For each styles-*.json, parse the JSON. Three sub-checks:
>
> 1. **Role coverage.** For each role name referenced in any template's `## Color binding` (the right-hand side after `←`, before any `.fill`/`.stroke`/`.strokeWidth` accessor), verify it has a hex entry under `roles` (or under `textConstants` for text tokens like `textOnPlate`, `textOnCanvas`, `loopText`, `lineOnCanvas`). Missing entry → `FAIL` with `<scheme-file> missing role <role>`.
> 2. **Init-block coverage.** For every kind referenced by a template (collect from `templates/diagram.mermaid/diagram-*.md` frontmatter `kind:`), verify the scheme's `blocks.init.<kind>` entry exists and is a non-empty string. Missing or empty → `FAIL` with `<scheme-file> missing blocks.init.<kind>`.
> 3. **Init-block sanity per kind.** Each `blocks.init.<kind>` value MUST: (a) start with `%%{init:` and end with `}%%`; (b) contain `'useMaxWidth':true` (per drawer agent sanity check 10 — layout config); (c) NOT contain the literal `'theme':'base'`; (d) NOT contain `'darkMode':true`. Any failure → `FAIL` with `<scheme-file> blocks.init.<kind>: <which check>`.
>
> Also verify: every role listed in any template's `## Roles` section is referenced by that template's `## Color binding`. Declared-but-unused → `WARN`.
>
> Return the structured `## scan: A5-coverage` block.

Outcome: `dispatched (3 agents)`.

## Step 3: Merge structured reports

- Parse each returned block. Split on `## scan:` headings.
- Deduplicate findings across A2 / A3 / A5 (same `<path>:<line>` + title = one).
- Apply waivers from `.guard-waivers.json` if present (none expected for this plugin in v1).

Outcome: `merged (<n> findings)`.

## Step 4: Present unified report

Render to the user:

```
# lazy-diagram.audit report

## A2 — Template well-formedness
[<sev>] <title> | <path>
...

## A3 — Contract conformance on exemplars
...

## A5 — Role + init-block coverage in styles-*.json
...

## Summary
pass: <n>  warn: <n>  fail: <n>  info: <n>
```

Outcome: `presented`.

## Step 5: Ask which to fix

- If `fail + warn == 0` → `nothing-to-fix`. Skip to Step 7.
- Else, use `AskUserQuestion` (single multi-select) listing each `WARN`/`FAIL` finding as an option. Capture the user's selection.

Outcome: `confirmed (<n> selected)` or `nothing-to-fix`.

## Step 6: Apply confirmed fixes

For each selected finding, the coordinator (this session, not the agents) applies the fix. Fix vocabulary:

- A2 missing section → cannot auto-fix; surface the file path and ask the user to author the missing section.
- A3 clause violation → offer to invoke `lazy-diagram.fix` against the offending file.
- A5 missing-role-in-scheme → surface the scheme file path and missing role; ask the user to add the hex entry under `roles{}` or `textConstants{}`.
- A5 missing-init-block → surface the scheme file path and missing kind; ask the user to author the `blocks.init.<kind>` entry (the project-local `dev.diagram-style` skill is the dedicated authoring path).
- A5 init-block sanity violation → surface the scheme file, kind, and which sanity check failed (`useMaxWidth` missing, `theme:base` present, `darkMode:true` present, malformed wrapper); ask the user to fix the scheme entry.
- A5 declared-but-unused role → surface the template path and unused role; offer to delete the unused `## Roles` line or extend `## Color binding` to reference it.

Outcome: per-finding fix-outcome word (`fixed` / `deferred` / `skipped-per-user-choice`).

## Failure modes

- **`/lazy-diagram.audit` aborts: "[FAIL] plugin not installed"** — `lazycortex-diagram` is not found in `~/.claude/plugins/installed_plugins.json` → install the plugin via `/lazy-core.install`, restart Claude Code, then re-run.

## Step 7: Log the run

Two separate calls:

1. `Bash: mkdir -p ./.logs/claude/lazy-diagram.audit`
2. `Write: ./.logs/claude/lazy-diagram.audit/<UTC-timestamp>.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`) and the unified report from Step 4 plus the fix outcomes from Step 6.

Outcome: `logged`.
