---
chapter_type: walkthrough
summary: Register a documentation-guideline clause in the project overlay, then confirm lazy-python.docstring-writer honors it in the generated docstring.
last_regen: 2026-11-27
diagram_spec:
  - anchor: "Registration and dispatch"
    request: "Sequence diagram, registration and dispatch: the user registers an extra_docstring_sections entry (name/style/anchor/ref_exempt) plus optional d2_exempt_marker_attrs / private_name_allowlist in the pyproject.toml [tool.pcf] block, writes the section's content rules in the overlay docs/guidelines/python/documenting_guidelines.md, and dispatches the lazy-python.docstring-writer agent. Participants: user, pyproject.toml [tool.pcf] block, overlay documenting_guidelines.md, docstring-writer agent."
    kind_hint: sequence
  - anchor: "Ruleset merge"
    request: "Sequence diagram, ruleset merge: lazy-python.docstring-writer reads the plugin's documenting-guidelines canon, then the project overlay docs/guidelines/python/documenting_guidelines.md (override-on-conflict), then CLAUDE.md's Documenting section if present, and merges them with the pyproject.toml [tool.pcf] registrations into one ruleset. Participants: docstring-writer, plugin documenting-guidelines canon, overlay, CLAUDE.md Documenting section, [tool.pcf] registrations."
    kind_hint: sequence
  - anchor: "Apply and verify"
    request: "Sequence diagram, apply and verify: lazy-python.docstring-writer applies the merged ruleset to the target file, then runs chk-py against the changed file and reads the verification result. Participants: docstring-writer, target file, chk-py on the changed file."
    kind_hint: sequence
source_skills:
  - lazy-python.install
  - lazy-python.docstring-writer
  - lazy-python.coding-guidelines
source_sha: 0044ac4308cce96cc832c6dbbbe2042b5ad738d5
surface_sha: e7c0a0a97cf34ad62cca327cac96a5e56bd0ebea7e2668c9c49f972f5eae568c
---
# Add a project-specific documentation-guideline clause and confirm the docstring writer honors it

Your project has documentation conventions the plugin's canon doesn't cover — an extra docstring section your team wants on certain classes, an escape hatch for a private attribute your API intentionally exposes, project-specific narrative rules. `lazycortex-python` gives you `docs/guidelines/python/documenting_guidelines.md` for the content rules and `pyproject.toml`'s `[tool.pcf]` table for the structural registrations (`extra_docstring_sections`, `d2_exempt_marker_attrs`, `private_name_allowlist`), and `lazy-python.docstring-writer` is the agent that reads both on every dispatch. Neither plugin code nor a Claude Code restart is involved — the agent re-reads the overlay every time it runs.

This walkthrough takes you from an install-created overlay stub to a verified project-specific documentation clause — confirmed by the docstring `lazy-python.docstring-writer` actually writes.

## Outcome

After completing this walkthrough you have:

- At least one project-specific clause written in `docs/guidelines/python/documenting_guidelines.md`, optionally backed by a structural registration in `pyproject.toml`'s `[tool.pcf]` table.
- A `lazy-python.docstring-writer` dispatch whose output visibly reflects that clause — a new section, an included attribute, a narrative rule honored — on a file the clause applies to.
- A working understanding of the three layers the agent reads in order (plugin canon, project overlay, `CLAUDE.md`), so you know where to add the next rule as your project's documentation conventions grow.

## What you need

- `lazycortex-python` installed in your repo — Step 1 below confirms `/lazy-python.install` has scaffolded `docs/guidelines/python/documenting_guidelines.md` (and the other three overlay stubs), and re-runs the install if it's missing.
- A class, method, or property whose docstring you can regenerate for the verification half of this walkthrough — something the new clause changes the shape of.

## The journey

### Step 1 — Confirm the overlay stub is scaffolded

`/lazy-python.install` Step 5 is what creates the four overlay stubs under `docs/guidelines/python/` — `coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md` and `checking_guidelines.md`. `documenting_guidelines.md` is the one this walkthrough edits. If you already ran `/lazy-python.install` when you first set up the plugin, it's already in place — check that `docs/guidelines/python/documenting_guidelines.md` exists.

If your repo kept its overlays directly under `docs/guidelines/` from an earlier plugin version, nothing reads them any more: the writer agents, the audit and `chk-py review` look only under `docs/guidelines/python/`, and a fresh install scaffolds empty stubs there beside your old files. The plugin's migration step moves each old overlay into `docs/guidelines/python/` when you run `/lazy-core.setup`. If both an old and a new file exist for a topic, the step leaves both in place and reports `kept-both`, naming the pair so you can merge them yourself and delete the old one. Language-neutral guides such as `docs/guidelines/domain-groups.md` stay where they are.

If it's missing, re-run:

```
/lazy-python.install
```

The install is idempotent and quiet: Step 5 creates only the missing stub files and never touches an overlay you've already started editing — safe to re-run mid-project without losing prior work.

The same run also refreshes the plugin's always-loaded rules in `.claude/rules/` (Step 1) — `lazy-python.style`, `lazy-python.docstrings`, `lazy-python.tests`, and `lazy-python.failing-tests`, the rule for how a failing test is judged before anything is fixed. Those mirrors are plugin-owned and overwritten on every install; your overlay files are the project-owned layer, so put project rules there rather than in the mirrors.

The install also makes the project venv reachable from isolated job worktrees. When your venv lives inside the checkout (the default `.venv/`), install lists it among the paths that every job worktree carries from the checkout, so `chk-py` and `tst-py` keep working inside an expert job that runs in its own worktree. A venv at an absolute path outside the checkout needs nothing. If `[tool.lazy-python].venv` is a relative path that climbs out of the checkout, install reports a warning; make that value absolute and re-run `/lazy-python.install`. You never edit the worktree list by hand — the install records it.

### Step 2 — Understand what lazy-python.docstring-writer reads

`lazy-python.docstring-writer`'s own Step 1 reads three layers, every dispatch, in this order:

1. The plugin's canonical `lazy-python.documenting-guidelines.md` — the docstring section order, style rules, and zero-tolerance blockers that hold regardless of project.
2. `docs/guidelines/python/documenting_guidelines.md` — your project overlay, read next; it overrides the canon on conflict.
3. `CLAUDE.md`'s `## Documenting` section if present — a third layer for project-wide notes that don't belong to a single topic.

The agent is dispatched fresh each time and does not inherit the main session's loaded rules, so it re-reads all three layers on every run — there is nothing to restart or reload after you edit the overlay.

This same canon-then-overlay layering is how every `docs/guidelines/python/<topic>_guidelines.md` file works — `coding_guidelines.md`, `testing_guidelines.md`, and `checking_guidelines.md` follow the identical pattern for their own writer and checker consumers. The coding canon's Knowledge Marker Rules — never remove or alter `TODO:`, `TMP:`, `DBG:`, `ref:`, `Decision:`, `Domain(…):`, `Contract:` comments — apply here too: `lazy-python.docstring-writer`'s own Special Comment Handling rules mirror them. It ignores `Domain(…):`, `ref:` and `DBG:` tags when writing a docstring, and treats code marked `Decision:` as settled, never carrying its rationale into the docstring. A class's markers therefore keep their meaning as its docstring evolves under this walkthrough.

One rule from the coding canon holds in every project, whatever your overlay says: source is written in English. That covers docstrings, comments and `Domain(…)` / `Contract:` blocks, even when your project's documents and conversations use another language. A project-specific clause you add to the overlay is therefore written for English docstrings — a quoted foreign-language literal the code genuinely handles is data and stays as it is.

### Step 3 — Write a project-specific clause in the documenting overlay

Open `docs/guidelines/python/documenting_guidelines.md` and add a clause the canon doesn't carry. For example, a narrative rule:

```markdown
# Project additions to documenting

## Field Semantics section

  Classes under `src/protocol/` that serialize to an external wire format
  carry a `Field Semantics` section listing wire-level constraints (units,
  valid ranges, endianness) that don't belong in `Attributes`.
```

A section like this also needs a structural registration so the docstring machinery (`pcf`'s docstring checks and `lazy-python.docstring-writer`) know it exists. Add it to `pyproject.toml`'s `[tool.pcf]` table — the install-bootstrapped section already carries a commented-out example to uncomment and adapt:

```toml
[[tool.pcf.extra_docstring_sections]]
name = "Field Semantics"
style = "bulleted"
after = "Guarantees"
ref_exempt = true
```

`name` must match the overlay's section heading exactly. `style` is `"bulleted"`, `"definition"`, or `"plain"`. `after` (or `before`) anchors the section's position relative to a built-in section or a previously declared entry. `ref_exempt = true` shields the section's body from checks that would otherwise flag its `# ref:`-style lines.

Without both pieces — the content rule in the overlay and the structural registration in `pyproject.toml` — `lazy-python.docstring-writer` has nothing to add: the canon has no opinion on your wire-format documentation, and an unregistered section name is not one the agent is allowed to invent.

### Step 4 — Dispatch lazy-python.docstring-writer

Pick (or write) a class the new clause applies to — for instance, a class under `src/protocol/` with a wire-level constraint worth documenting — then dispatch:

```
Dispatch the lazy-python.docstring-writer agent against <path/to/file.py>
```

The agent's Step 1 re-reads the three layers from Step 2 above, including your edited overlay and the `pyproject.toml` registration. Its Step 2 reads the target file, Step 3 identifies non-compliant or missing docstrings, and Step 4 writes them — following your overlay's content rule for the new `Field Semantics` section at the position and style you registered.

### Step 5 — Verify the clause took effect

Read the docstring the agent wrote (or edited). Confirm:

- The `Field Semantics` section (or whatever you named it) appears at the position you anchored it (`after = "Guarantees"` in the example above).
- Its content follows the style you declared (`bulleted`, in the example) and the wording rule you wrote in the overlay.
- Every other section still follows the canon's ordinary rules — the overlay only adds to the section machinery, it doesn't relax the zero-tolerance blockers. Among them: no inventory in Summary or Scope (a sentence walking through the fields, axes or cases one by one), no private attributes in `Attributes` unless your declared escape hatch covers them, and the 117-character line limit.

Before that, the agent's Step 5 self-check walks every docstring it wrote against its checklist (what-not-how, no private internals in prose, no inventory, no private names in `Attributes`), so most semantic slips are caught before the checker runs. The agent's own Step 6 then runs `chk-py all <file>.py -q` against the changed file as part of its dispatch — a clean run confirms the file passes the deterministic checks; it does not by itself confirm your new section's wording, which is your judgment call at this step.

If the section is missing, confirm the registration in `pyproject.toml` uses the exact section `name` your overlay heading uses — a mismatch means the agent has no rule to follow for a section it isn't told exists.

### Step 6 — Iterate and expand

Once the first clause is confirmed, add more as your project's documentation conventions grow — further sections, escape-hatch registrations (`d2_exempt_marker_attrs` for private attributes your API intentionally exposes, `private_name_allowlist` for private identifiers your narrative legitimately names), or additional prose in `documenting_guidelines.md`. Rules about how code itself is written go in the sibling `coding_guidelines.md` overlay, which `lazy-python.code-reviewer` reads alongside the canon when it judges changed code. Because `lazy-python.docstring-writer` re-reads both files on every dispatch, each new clause takes effect immediately without touching plugin code.

## After you're done

`docs/guidelines/python/documenting_guidelines.md` and the `[tool.pcf]` registrations in `pyproject.toml` are living project config. Track both in version control. When a teammate's `lazy-python.docstring-writer` dispatch produces a docstring that disagrees with a project convention, the fix is an overlay edit (and, for structural additions, a `pyproject.toml` registration) — not a one-off manual rewrite repeated file by file.

To verify the overlay stub itself is intact (not accidentally deleted or corrupted), run `/lazy-python.audit` — its overlay check covers all four `docs/guidelines/python/*.md` files, not just the one this walkthrough touches, and looks for the `# Project additions to <topic>` header each stub opens with. Keep that header when you edit: it is how the writer agents recognize the file as an overlay rather than the canon. If a header goes missing, restore it by hand — a re-run of `/lazy-python.install` keeps your edited overlay body untouched. The same audit also warns when a job running in an isolated worktree would start without the project venv link; the fix it names is a re-run of `/lazy-python.install`. The audit does not validate clause content — that judgment belongs to you and your team, backed by the docstrings `lazy-python.docstring-writer` actually produces.

## How the overlay and pyproject.toml layers combine

### Registration and dispatch

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant pcfBlock as pyproject.toml [tool.pcf] block
  participant overlayGuidelines as Overlay documenting_guidelines.md
  participant docstringWriter as lazy-python.docstring-writer agent

  user->>pcfBlock: register extra_docstring_sections entry (name, style, anchor, ref_exempt)
  opt exemptions needed
    user->>pcfBlock: add d2_exempt_marker_attrs
    user->>pcfBlock: add private_name_allowlist
  end
  Note over user,pcfBlock: Registration declares the section but holds no content rules
  user->>overlayGuidelines: write the section's content rules in docs/guidelines/python/documenting_guidelines.md
  user->>docstringWriter: dispatch the agent
  docstringWriter->>pcfBlock: read registered sections and exemptions
  pcfBlock-->>docstringWriter: extra_docstring_sections, d2_exempt_marker_attrs, private_name_allowlist
  docstringWriter->>overlayGuidelines: read the section's content rules
  overlayGuidelines-->>docstringWriter: content rules for the registered section
  docstringWriter-->>user: docstrings written with the registered section
```

You register the section's structure in the `pyproject.toml` `[tool.pcf]` block, write its content rules in `docs/guidelines/python/documenting_guidelines.md`, and dispatch `lazy-python.docstring-writer`.

### Ruleset merge

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant docstringWriter as lazy-python.docstring-writer
  participant pluginCanon as Plugin documenting-guidelines canon
  participant projectOverlay as Overlay docs/guidelines/python/documenting_guidelines.md
  participant claudeMd as CLAUDE.md Documenting section
  participant pcfRegistrations as pyproject.toml [tool.pcf] registrations

  docstringWriter->>pluginCanon: read canon
  pluginCanon-->>docstringWriter: base rules
  docstringWriter->>projectOverlay: read overlay
  projectOverlay-->>docstringWriter: overlay rules
  Note over docstringWriter,projectOverlay: override-on-conflict, overlay wins over canon
  docstringWriter->>claudeMd: read Documenting section
  alt Documenting section present
    claudeMd-->>docstringWriter: Documenting rules
  else section absent
    claudeMd-->>docstringWriter: nothing to merge
  end
  docstringWriter->>pcfRegistrations: read [tool.pcf] registrations
  pcfRegistrations-->>docstringWriter: registrations
  Note over docstringWriter: merge all sources into one ruleset
```

The agent reads the plugin's documenting-guidelines canon, then your overlay (which wins on conflict), then the Documenting section of `CLAUDE.md` if there is one, and merges them with the `[tool.pcf]` registrations into one ruleset.

### Apply and verify

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant docstringWriter as docstring-writer
  participant targetFile as target file
  participant chkPy as chk-py on the changed file

  docstringWriter->>targetFile: apply merged ruleset
  targetFile-->>docstringWriter: file changed
  docstringWriter->>chkPy: run chk-py against changed file
  chkPy->>targetFile: read changed file
  targetFile-->>chkPy: file contents
  chkPy-->>docstringWriter: verification result
  Note over docstringWriter,chkPy: docstring-writer reads the verification result
```

The agent applies the merged ruleset to the target file, then runs `chk-py` against the changed file to verify the result.
