---
chapter_type: walkthrough
summary: Register a coding-guideline clause in the project overlay, then confirm both /lazy-python.check-style and the chk-py review gate's lazy-python.code-reviewer catch it.
last_regen: 2026-08-05
diagram_spec:
  anchor: "How the overlay and pyproject.toml layers combine"
  request: "Sequence diagram showing two parallel flows that both start from the same project overlay. Flow 1 (docstrings): user registers an extra_docstring_sections entry (name/style/anchor/ref_exempt) plus optional d2_exempt_marker_attrs / private_name_allowlist in pyproject.toml [tool.pcf], writes the section's content rules in docs/guidelines/documenting_guidelines.md, dispatches lazy-python.docstring-writer; the agent reads the plugin canon, then the overlay (override-on-conflict), then CLAUDE.md's Documenting section if present, then applies the merged ruleset plus the pyproject.toml registrations to the target file and runs chk-py to verify. Flow 2 (code review): user writes a project-specific clause in docs/guidelines/coding_guidelines.md, runs chk-py review, which resolves the changed-file scope, collects every guideline layer (canon, overlay, .claude/rules, project notes) into a manifest, and names the lazy-python.code-reviewer agent; the agent reads the manifest and every listed layer, reviews the code against its ten-point checklist (including the overlay-specific clause), writes findings JSON, and the user renders them with chk-py review --render. Show both flows sharing the overlay directory as their common source of truth but feeding two different agents and two different verification commands."
source_skills:
  - lazy-python.install
  - lazy-python.code-reviewer
  - lazy-python.check-style
---
# Add a project-specific coding-guideline clause and confirm the review gate catches it

Your project has coding conventions the plugin's canon doesn't cover — a naming scheme specific to how your codebase is organized, a module-layout rule, anything the canon has no opinion on. `lazycortex-python` gives you `docs/guidelines/coding_guidelines.md` for this, and two surfaces that read it: `/lazy-python.check-style`, the manually-invoked six-step review workflow you run after an edit batch, and `lazy-python.code-reviewer`, the agent that `chk-py`'s guideline-review gate dispatches to judge exactly the clauses no deterministic checker can prove. Neither plugin code nor a Claude Code restart is involved — both re-read the overlay on every run.

This walkthrough takes you from an install-created overlay stub to a verified project-specific coding clause — confirmed once by `/lazy-python.check-style`'s own checker pass and again by `lazy-python.code-reviewer`'s guideline finding.

## Outcome

After completing this walkthrough you have:

- At least one project-specific clause written in `docs/guidelines/coding_guidelines.md`.
- A `/lazy-python.check-style` run that surfaces the pending guideline-review gate for a file the clause applies to, and a confirmed finding (or a confirmed absence of one) that `lazy-python.code-reviewer` reports once dispatched against it.
- A working understanding of how the same overlay file reaches both the manual `check-style` workflow and the automated `chk-py` review gate, so you know where to add the next rule as your project's conventions grow.

## What you need

- `lazycortex-python` installed in your repo — Step 1 below confirms `/lazy-python.install` has scaffolded `docs/guidelines/coding_guidelines.md` (and the other three overlay stubs), and re-runs the install if it's missing.
- At least one file you can commit a small, deliberate change to for the review half of this walkthrough — something the new clause can judge as either conforming or violating.

## The journey

### Step 1 — Confirm the overlay stub is scaffolded

`/lazy-python.install` Phase 5 is what creates the four overlay stubs under `docs/guidelines/`, including `coding_guidelines.md`, the one this walkthrough edits. If you already ran `/lazy-python.install` when you first set up the plugin, it's already in place — check that `docs/guidelines/coding_guidelines.md` exists and still carries its canonical `# Project additions to coding` header.

If it's missing, re-run:

```
/lazy-python.install
```

The install is idempotent and quiet: Phase 5 creates only the missing stub files and never touches an overlay you've already started editing — safe to run again mid-project without losing prior work.

### Step 2 — Understand who reads the coding overlay

Both surfaces read `coding_guidelines.md`, but at different points in the workflow and for different reasons:

- **`/lazy-python.check-style`** reads three layers in its own Step 1, every time it's invoked: the plugin's `lazy-python.coding-guidelines.md` canon, then `docs/guidelines/coding_guidelines.md`, then the `## Style` section of `CLAUDE.md` if present. It then walks a fixed set of manual-inspection categories (docstring quality, contract consistency, guard clauses, method organization, naming, structural rules, comment preservation) against every modified file, before running `chk-py all` in its Step 4.
- **`lazy-python.code-reviewer`** reads four layers, weakest to strongest: the plugin's `lazy-python.*-guidelines.md` canon, every file under `docs/guidelines/*.md` (so `coding_guidelines.md` counts), `.claude/rules/*.md` files scoped to Python, and `CLAUDE.md` / `.claude/CLAUDE.md`. A later layer overrides an earlier one on conflict. It is dispatched against a manifest that `chk-py review` — the seventh step of the `chk-py all` gate — writes when the review scope is pending.

Checklist item 10 in the reviewer's own instructions, "Overlay-specific clauses", exists precisely for rules only your project declares — a clause your overlay adds that the canon does not carry.

### Step 3 — Write a project-specific clause in the coding overlay

Open `docs/guidelines/coding_guidelines.md` and add a clause the canon doesn't carry — something specific to how your codebase is organized. For example:

```markdown
# Project additions to coding

## Repository-layer naming

  Classes that own a persistence boundary (query + write access to one table or
  collection) are named `<Entity>Store`, never `<Entity>Repository` or `<Entity>DAO`.
  This applies to every class under `src/storage/`.
```

Without this clause, neither `check-style`'s manual review nor `code-reviewer`'s checklist has anything to check a `<Entity>Repository` class against — the canon has no opinion on your module layout or naming scheme.

### Step 4 — Make a change and dispatch /lazy-python.check-style

Make (or pick) a small change that violates or satisfies your new clause — for instance, add a class under `src/storage/` named against the convention you just wrote — then invoke:

```
/lazy-python.check-style
```

The skill's first action is to create a task list, one task per step, so you can watch it progress. It reads the three guideline layers (Step 1), enumerates the modified `.py` files via `git diff` (Step 2), walks the manual-inspection categories against each one (Step 3), then runs `chk-py all <file>.py -q` followed by `chk-py all -q` for the whole project (Step 4).

Because your overlay clause is a guideline-level rule, not a canon rule, `check-style`'s own manual pass in Step 3 won't flag it directly — that judgment belongs to `lazy-python.code-reviewer`. Instead, `chk-py all` in Step 4 will hit the seventh gate step, the guideline review: it prints `review: PENDING — <N> file(s) in scope`, writes a manifest to `.runtime/lazy-python/review/<timestamp>.json` (listing the files in scope and every guideline layer, including your edited `coding_guidelines.md`), and names `lazy-python.code-reviewer` to dispatch against it. `check-style` surfaces this as a violation from `chk-py` in its Step 4 outcome — it does not dispatch the reviewer for you.

### Step 5 — Dispatch lazy-python.code-reviewer and render the findings

Dispatch the agent against the manifest `chk-py all` printed:

```
Dispatch the lazy-python.code-reviewer agent against the review manifest at .runtime/lazy-python/review/<timestamp>.json
```

The agent reads the manifest, reads every layer it lists — canon, your `coding_guidelines.md`, any Python-scoped `.claude/rules/*.md`, and `CLAUDE.md` — reviews the files under review against its ten-point checklist, and writes a findings JSON to the `findings_path` the manifest named. Render what it wrote:

```
chk-py review --render .runtime/lazy-python/review/<timestamp>.findings.json
```

If your changed file violates the naming clause, expect a finding whose `rule` reads something like `overlay-repository-layer-naming`, with the file, line, and a message describing the mismatch — that's the reviewer applying checklist item 10 against a clause no deterministic checker knows about. If the file already conforms, an empty `findings` array (rendered as `Success: no guideline issues found`) confirms the reviewer read the clause and had nothing to flag — not that it skipped the check. A `FAIL` severity in the output means the render exits non-zero, exactly like a `pcf` or `mypy` failure would.

### Step 6 — Re-run check-style's remaining steps

Once the review findings render clean (or you've fixed what they flagged), go back to `/lazy-python.check-style`: Step 5 applies any remaining fixes from its own manual pass or from `chk-py`, and Step 6 re-verifies with `chk-py all -q` (now with the review scope closed) and `tst-py <module> -q` for any touched module. Re-running `chk-py review` against an unchanged scope reuses the previous findings instead of re-dispatching the agent (`review: scope unchanged since ... — reusing findings`) — edit the file or the overlay clause to force a fresh pass.

### Step 7 — Iterate and expand

Once the first clause is confirmed by both surfaces, add more as your project's conventions evolve — further prose in `coding_guidelines.md`. Because both `check-style` and `code-reviewer` re-read the overlay on every run, each new clause takes effect immediately without touching plugin code.

## After you're done

`docs/guidelines/coding_guidelines.md` is living project config. Track it in version control. When a teammate's `check-style` run or review pass disagrees with a project convention, the fix is an overlay edit — not a review comment repeated file by file.

To verify the overlay stub itself is intact (header not altered or removed), run `/lazy-python.audit` — its overlay check covers all four `docs/guidelines/*.md` files, not just the one this walkthrough touches. It does not validate clause content — that judgment belongs to you and your team, backed by `/lazy-python.check-style` and `lazy-python.code-reviewer`.

If `lazy-python.code-reviewer` misses a clause you expected it to flag, confirm the clause is actually written in `coding_guidelines.md` (not just in your head) and that the file under review was included in the manifest's scope — the reviewer only sees files named in its manifest.

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
