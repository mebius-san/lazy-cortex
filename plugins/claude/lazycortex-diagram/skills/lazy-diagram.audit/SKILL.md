---
name: lazy-diagram.audit
description: "Run when the operator asks to audit the lazycortex-diagram plugin itself — after authoring or editing a template under `templates/diagram.*/` or a `styles-*.json` scheme, or when drawn diagrams come out with unbound roles, a missing init block, or an exemplar that no longer matches the authoring rule. Delegated from `lazy-core.doctor` Phase 3. Audits the plugin's own shipped templates and schemes, never a diagram in your docs — a stale fence in a document is `/lazy-diagram.fix`. Read-only: it reports `PASS` / `INFO` / `WARN` / `FAIL` with the repair route named per finding and writes nothing."
allowed-tools: Read, Glob, Grep, Bash, Agent, Write
---
# lazy-diagram.audit

Audit the `lazycortex-diagram` plugin for template well-formedness and contract conformance on exemplars. Read-only: it reports and names the repair route per finding, and repairs nothing — the routes are separate runs the operator starts.

This skill follows the shared audit form in `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md` — `references/lazy-core.audit-contract.md` inside the installed `lazycortex-core`: read-only, the four severity words `PASS` / `INFO` / `WARN` / `FAIL` and no others, the repair route standing in the finding line itself, and no estimate of what a repair would save. The one file it writes is its own run log under `./.logs/claude/lazy-diagram.audit/`, which `lazy-log.logging` mandates for every run.

This skill is a **parallel-scan coordinator** per `lazy-core.skill-writing § 5`. Phase 1 dispatches Explore agents in a single message; Phase 2+ merges their structured reports.

> TODO: fixture-side scans (A1 fixture-template coverage, A4 fixture freshness) were removed because the dev-vs-shipped split for `tests/diagram/` is still unsettled. Re-add when that split is finalized.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executor MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Pre-flight`
   - `Step 2 — Dispatch A2–A3 + A5 in parallel`
   - `Step 3 — Merge structured reports`
   - `Step 4 — Present unified report`
   - `Step 5 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it".
3. **Do not reach Step 4 (Present unified report) until the ledger shows steps 1–3 `completed`.** Reports without merge are a bug.
4. **The Step 4 report is a structural verifier.** Its output MUST contain one section per A2 / A3 / A5 finding plus a summary line.

## Step 1: Pre-flight

- Resolve the plugin root as what `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-diagram` prints — the authoring repo's `plugins/claude/lazycortex-diagram/` when this checkout ships the plugin, else the exported or newest cached copy. `<core-cli>` is the core plugin's `bin/lazycortex-core` file: when this repo authors the plugin itself (`plugins/claude/lazycortex-core/.claude-plugin/plugin.json` exists) that is `<repo-root>/plugins/claude/lazycortex-core/bin/lazycortex-core`; otherwise `Read` `$HOME/.claude/plugins/installed_plugins.json` and take `<installPath>/bin/lazycortex-core` from the last `lazycortex-core@lazycortex` record. Every verb runs through the interpreter because the file carries no exec bit. If the primitive exits non-zero → `[FAIL] plugin not installed — fix: /plugin install lazycortex/lazycortex-diagram, then restart Claude Code and re-run`. Stop.
- Capture `${CLAUDE_PLUGIN_ROOT}` for the dispatch prompts in Step 2.

Outcome: `asserted (root=<path>)` or `[FAIL]`.

## Step 2: Dispatch A2–A3 + A5 in parallel

In a SINGLE assistant message, dispatch three `Agent` calls with `subagent_type: "Explore"` and `mode: "dontAsk"`. Each agent's prompt embeds the structured-report contract from `lazycortex-core`'s `references/lazy-core.parallel-scan.md`. Word budget: under 300 words per agent.

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
> For each mermaid exemplar fence, verify the structural sanity-check items the drawer agent enforces (see `${CLAUDE_PLUGIN_ROOT}/agents/lazy-diagram.draw-mermaid.md` § sanity checks). Init directive content is not applicable in templates — templates ship structure-only and the drawer composes the directive from the scheme; the init check runs at fixture time, not template time. Items checked:
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
- Apply waivers from `.guard-public.json` if present (none expected for this plugin in v1).

Outcome: `merged (<n> findings)`.

## Step 4: Present unified report

Every finding line carries its own repair route — the run ends here, and nothing is applied. Routes by finding class:

- **A2 missing section** → author the missing section in the named template, per `lazy-diagram.authoring`.
- **A2 / A3 frontmatter or fence-count finding** → correct the named template's frontmatter or `## Exemplar` fence so exactly one fence of the folder's format remains.
- **A3 clause violation** (single-letter ID, unlabelled edge, init literal, style literal, `classDef` / `class` / `style` line in the exemplar) → `/lazy-diagram.fix` against the offending file.
- **A5 missing role** → add the hex entry for the named role under `roles{}` (or `textConstants{}` for a text token) in the named `styles-*.json`.
- **A5 missing init block** → author the `blocks.init.<kind>` entry for the named kind in the named `styles-*.json`.
- **A5 init-block sanity violation** → correct the named `blocks.init.<kind>` entry so it wraps in `%%{init: … }%%`, carries `'useMaxWidth':true`, and carries neither `'theme':'base'` nor `'darkMode':true`.
- **A5 declared-but-unused role** → delete the unused `## Roles` line, or extend the template's `## Color binding` to reference it.

Render to the user:

```
# lazy-diagram.audit report

## A2 — Template well-formedness
[<sev>] <title> | <path> — fix: <route>
...

## A3 — Contract conformance on exemplars
...

## A5 — Role + init-block coverage in styles-*.json
...

## Summary
pass: <n>  warn: <n>  fail: <n>  info: <n>
audit: <LEVEL> (<n> findings)
```

`<LEVEL>` is the highest severity present, with `INFO` counted as `PASS`, per the contract's summary line.

There is no recommendations section after the summary, and no line states what a repair would save.

Outcome: `presented`.

## Failure modes

- **`/lazy-diagram.audit` aborts: "[FAIL] plugin not installed"** — `lazycortex-diagram` is not found in `~/.claude/plugins/installed_plugins.json` → install the plugin via `/lazy-core.install`, restart Claude Code, then re-run.

## Step 5: Log the run

Two separate calls:

1. `Bash: mkdir -p ./.logs/claude/lazy-diagram.audit`
2. `Write: ./.logs/claude/lazy-diagram.audit/<UTC-timestamp>.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`) and the unified report from Step 4. This is the only file the skill writes.

Outcome: `logged`.
