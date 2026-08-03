---
chapter_type: walkthrough
summary: Register a project docstring section in pyproject.toml and a coding-guideline clause in the overlay, then confirm both the docstring writer and the code reviewer honor them.
last_regen: 2026-08-03
diagram_spec:
  anchor: "How the overlay and pyproject.toml layers combine"
  request: "Sequence diagram showing two parallel flows that both start from the same project overlay. Flow 1 (docstrings): user registers an extra_docstring_sections entry (name/style/anchor/ref_exempt) plus optional d2_exempt_marker_attrs / private_name_allowlist in pyproject.toml [tool.pcf], writes the section's content rules in docs/guidelines/documenting_guidelines.md, dispatches lazy-python.docstring-writer; the agent reads the plugin canon, then the overlay (override-on-conflict), then CLAUDE.md's Documenting section if present, then applies the merged ruleset plus the pyproject.toml registrations to the target file and runs chk-py to verify. Flow 2 (code review): user writes a project-specific clause in docs/guidelines/coding_guidelines.md, runs chk-py review, which resolves the changed-file scope, collects every guideline layer (canon, overlay, .claude/rules, project notes) into a manifest, and names the lazy-python.code-reviewer agent; the agent reads the manifest and every listed layer, reviews the code against its ten-point checklist (including the overlay-specific clause), writes findings JSON, and the user renders them with chk-py review --render. Show both flows sharing the overlay directory as their common source of truth but feeding two different agents and two different verification commands."
source_skills:
  - lazy-python.install
  - lazy-python.docstring-writer
  - lazy-python.code-reviewer
  - review.py
---
# Add project-specific overlay rules and confirm both agents honor them

Your project has conventions the plugin's canon doesn't cover — a docstring section unique to your domain, or a coding rule specific to how your codebase is organized. `lazycortex-python` gives you two independent overlay files for this, `docs/guidelines/documenting_guidelines.md` and `docs/guidelines/coding_guidelines.md`, and two agents that read them: `lazy-python.docstring-writer` picks up the documenting overlay (plus whatever you register in `pyproject.toml` `[tool.pcf]`) on every docstring dispatch, and `lazy-python.code-reviewer` picks up the coding overlay (among other guideline layers) on every `chk-py review` pass. Neither plugin code nor a Claude Code restart is involved — both agents re-read their layers on every dispatch.

This walkthrough takes you from install-created overlay stubs to a verified project-specific docstring section (checked by the writer) and a verified project-specific coding clause (checked by the reviewer) — the two halves of the same overlay convention, exercised end to end.

## Outcome

After completing this walkthrough you have:

- At least one project-registered docstring section declared in `pyproject.toml` `[tool.pcf] extra_docstring_sections`, with its content rules written in `docs/guidelines/documenting_guidelines.md`, confirmed in a docstring `lazy-python.docstring-writer` generates.
- At least one project-specific clause written in `docs/guidelines/coding_guidelines.md`, confirmed in a finding (or a confirmed absence of one) that `lazy-python.code-reviewer` reports through `chk-py review`.
- A working understanding of which overlay file each agent reads, so you know where to add the next rule as your project's conventions grow.

## What you need

- `lazycortex-python` installed in your repo — Step 1 below confirms `/lazy-python.install` has scaffolded the `[tool.pcf]` block in `pyproject.toml` and all four `docs/guidelines/*.md` overlay stubs, and re-runs the install if either is missing.
- At least one Python class in your project that needs the new docstring section, and at least one file you can commit a small, deliberate change to for the review half of this walkthrough.

## The journey

### Step 1 — Confirm the overlay stubs are scaffolded

`/lazy-python.install` Phase 4 is what bootstraps the `[tool.pcf]` block in `pyproject.toml`, and Phase 5 is what creates the four overlay stubs under `docs/guidelines/`, including the two this walkthrough edits (`documenting_guidelines.md` and `coding_guidelines.md`). If you already ran `/lazy-python.install` when you first set up the plugin, both are already in place — check that `pyproject.toml` has a `[tool.pcf]` section and that `docs/guidelines/coding_guidelines.md` and `documenting_guidelines.md` exist and still carry their canonical `# Project additions to <topic>` header.

If either is missing, re-run:

```
/lazy-python.install
```

The install is idempotent and quiet: Phase 4 appends only the missing `pyproject.toml` sections, Phase 5 creates only the missing stub files, and neither step touches an overlay you've already started editing — safe to run again mid-project without losing prior work.

### Step 2 — Understand which agent reads which overlay

Both agents follow the same "canon first, then overlay" precedence, but they read different files and different numbers of layers:

- **`lazy-python.docstring-writer`** reads three layers on every dispatch: the plugin's `lazy-python.documenting-guidelines.md` canon, then `docs/guidelines/documenting_guidelines.md`, then the `## Documenting` section of `CLAUDE.md` if present. It also honors whatever is registered in `pyproject.toml` `[tool.pcf]` — the section list, order anchors, and attribute exemptions — independently of the three-layer read.
- **`lazy-python.code-reviewer`** reads four layers, weakest to strongest: the plugin's `lazy-python.*-guidelines.md` canon, every file under `docs/guidelines/*.md` (so `coding_guidelines.md` and `documenting_guidelines.md` both count), `.claude/rules/*.md` files scoped to Python, and `CLAUDE.md` / `.claude/CLAUDE.md`. A later layer overrides an earlier one on conflict. It is dispatched by `chk-py review`, the seventh step of the `chk-py all` gate, against a manifest that lists exactly these layers plus the files under review.

Because the reviewer's overlay layer is the whole `docs/guidelines/` directory, a clause you write in `coding_guidelines.md` reaches it even though the reviewer isn't a docstring tool — checklist item 10, "Overlay-specific clauses", exists precisely for rules only your project declares.

### Step 3 — Register a docstring section in pyproject.toml

Open `pyproject.toml` and find the `[tool.pcf]` section installed by `/lazy-python.install`. Uncomment and fill in an `extra_docstring_sections` entry:

```toml
[[tool.pcf.extra_docstring_sections]]
name = "Field Semantics"
style = "definition"
after = "Guarantees"
ref_exempt = true
```

- `name` — the section heading exactly as it should appear in the docstring.
- `style` — `"bulleted"` (hyphen-prefixed list, like `Responsibilities`), `"definition"` (`name: description` lines, like `Attributes`), or `"plain"` (free prose, like `Notes`).
- `after` / `before` — an order anchor naming a built-in section or a previously declared entry. An anchor that doesn't resolve appends the section at the end of the order instead of failing.
- `ref_exempt` — set `true` only if this section's body carries `# REF:` lines your own tooling consumes; it shields those lines from the narrative checks.

You can register more than one section — each gets its own `[[tool.pcf.extra_docstring_sections]]` block.

### Step 4 — Write the docstring section's content rules

`pyproject.toml` only told the checker the section exists, its style, and its position — it says nothing about what belongs inside it. Open `docs/guidelines/documenting_guidelines.md` and add that:

```markdown
# Project additions to documentation

## Field Semantics section

  Classes that model a persisted record use a `Field Semantics:` section (registered
  in pyproject.toml, positioned after Guarantees) to document validation rules that
  don't fit `Attributes:` — for example cross-field constraints or units that apply
  to a group of fields rather than one.

  - One bullet per constraint, `name: description` in definition style.
  - Reference the fields it constrains by name; do not repeat their individual
    descriptions from Attributes.
```

Write it as prose the agent can interpret — not a machine-readable schema. Optionally, if a private field genuinely needs to appear in a docstring's `Attributes:` section, declare the escape hatch in the same `[tool.pcf]` block: `d2_exempt_marker_attrs = ["_dataset_schema"]` for `Attributes:` entries, or `private_name_allowlist = ["_dataset_schema"]` for narrative mentions in Summary/Scope/Notes. A name can need one, the other, or both.

### Step 5 — Dispatch lazy-python.docstring-writer and confirm

Pick a Python file with a class or method that should use your new section, then invoke the agent:

```
Use the lazy-python.docstring-writer agent to write docstrings for src/mymodule/dataset.py
```

The agent's Step 1 reads the canon, the overlay, and `CLAUDE.md`'s `## Documenting` section; its Step 6 runs `chk-py all <file>.py -q`, which enforces your `pyproject.toml` registrations. Look at the generated docstring: the new section should appear at the position you anchored it to, in the style you declared, with content following the rules you wrote — not invented content, and not a section you never registered. If it doesn't, check that the `[[tool.pcf.extra_docstring_sections]]` block is valid uncommented TOML and that the overlay actually has prose for the section.

### Step 6 — Write a project-specific clause in the coding overlay

Now switch files. Open `docs/guidelines/coding_guidelines.md` and add a clause the canon doesn't carry — something specific to how your codebase is organized. For example:

```markdown
# Project additions to coding

## Repository-layer naming

  Classes that own a persistence boundary (query + write access to one table or
  collection) are named `<Entity>Store`, never `<Entity>Repository` or `<Entity>DAO`.
  This applies to every class under `src/storage/`.
```

This is exactly the kind of rule `lazy-python.code-reviewer` checklist item 10 exists for — the canon has no opinion on your module layout or naming scheme, so without this clause a reviewer has nothing to check a `<Entity>Repository` class against.

### Step 7 — Run chk-py review and dispatch lazy-python.code-reviewer

Make (or pick) a small change that violates or satisfies your new clause — for instance, add a class under `src/storage/` named against the convention you just wrote — then run:

```
chk-py review
```

`chk-py review` is a thin wrapper around `review.py`, the seventh gate step's implementation — it never calls an LLM itself. If the scope is non-empty, it prints `review: PENDING — <N> file(s) in scope`, writes a manifest to `.runtime/lazy-python/review/<timestamp>.json` (listing the files under review and every guideline layer, including your edited `coding_guidelines.md`), and prints the dispatch line naming `lazy-python.code-reviewer` and the manifest path. Dispatch the agent against that manifest:

```
Dispatch the lazy-python.code-reviewer agent against the review manifest at .runtime/lazy-python/review/<timestamp>.json
```

The agent reads the manifest, reads every layer it lists — canon, your `coding_guidelines.md` and `documenting_guidelines.md`, any Python-scoped `.claude/rules/*.md`, and `CLAUDE.md` — reviews the files under review against its ten-point checklist, and writes a findings JSON to the `findings_path` the manifest named.

### Step 8 — Render the findings and confirm the overlay clause was applied

Render what the agent wrote:

```
chk-py review --render .runtime/lazy-python/review/<timestamp>.findings.json
```

If your test file violates the naming clause, expect a finding whose `rule` reads something like `overlay-repository-layer-naming`, with the file, line, and a message describing the mismatch — that's the reviewer applying checklist item 10 against a clause no deterministic checker knows about. If the file already conforms, an empty `findings` array (rendered as `Success: no guideline issues found`) confirms the reviewer read the clause and had nothing to flag — not that it skipped the check. A `FAIL` severity in the output means the render exits non-zero, exactly like a `pcf` or `mypy` failure would.

Re-running `chk-py review` against an unchanged scope reuses the previous findings instead of re-dispatching the agent (`review: scope unchanged since ... — reusing findings`) — edit the file or the overlay clause to force a fresh pass.

### Step 9 — Iterate and expand

Once the first docstring section and the first coding clause are both confirmed, add more of each as your project's conventions evolve — further `[[tool.pcf.extra_docstring_sections]]` blocks and overlay prose for the writer, further clauses in `coding_guidelines.md` for the reviewer. Because both agents re-read their layers on every dispatch and every `chk-py review` run, each change takes effect immediately without touching plugin code.

## After you're done

`pyproject.toml` `[tool.pcf]`, `docs/guidelines/documenting_guidelines.md`, and `docs/guidelines/coding_guidelines.md` are all living project config. Track all three in version control. When a teammate's docstring dispatch or review pass disagrees with a project convention, the fix is an overlay edit or a `pyproject.toml` registration — not a review comment repeated file by file.

To verify the overlay stubs themselves are intact (header not altered or removed), run `/lazy-python.audit` — its overlay check covers all four `docs/guidelines/*.md` files, not just the two this walkthrough touched. It does not validate section content, `pyproject.toml` registrations, or coding-guideline clauses — that judgment belongs to you and your team, backed by `chk-py all` and `chk-py review`.

If `lazy-python.docstring-writer` produces a docstring that contradicts a registered section's rules, the likely cause is ambiguous overlay wording, not a `pyproject.toml` misconfiguration — rewrite the rule and re-dispatch. If `lazy-python.code-reviewer` misses a clause you expected it to flag, confirm the clause is actually written in `coding_guidelines.md` (not just in your head) and that the file under review was included in the `chk-py review` scope — the reviewer only sees files named in its manifest.

## How the overlay and pyproject.toml layers combine

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant overlay as Project Overlay pyproject.toml
  participant guidelines as Guideline Docs
  participant writer as lazy-python.docstring-writer
  participant reviewer as lazy-python.code-reviewer
  participant chkpy as chk-py

  Note over overlay: shared source of truth for both flows

  par Docstring flow
    user->>overlay: register extra_docstring_sections entry name style anchor ref_exempt
    user->>overlay: register d2_exempt_marker_attrs and private_name_allowlist
    user->>guidelines: write section content rules in documenting_guidelines.md
    user->>writer: dispatch docstring writer
    writer->>writer: read plugin canon
    writer->>overlay: read overlay override-on-conflict
    writer->>guidelines: read CLAUDE.md Documenting section if present
    writer-->>writer: merge ruleset with pyproject.toml registrations
    writer->>writer: apply merged ruleset to target file
    writer->>chkpy: run chk-py to verify
    chkpy-->>writer: verification result
  and Code review flow
    user->>guidelines: write project-specific clause in coding_guidelines.md
    user->>chkpy: run chk-py review
    chkpy->>chkpy: resolve changed-file scope
    chkpy->>guidelines: collect canon overlay .claude/rules project notes into manifest
    chkpy->>reviewer: name code-reviewer agent with manifest
    reviewer->>chkpy: read manifest
    reviewer->>guidelines: read every listed guideline layer
    reviewer->>reviewer: review code against ten-point checklist
    reviewer->>chkpy: write findings JSON
    user->>chkpy: render findings with chk-py review --render
  end
```
