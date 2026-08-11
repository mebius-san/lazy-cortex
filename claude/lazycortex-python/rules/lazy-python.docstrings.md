---
description: Python docstring discipline — use the lazy-python.docstring-writer agent. Triggers on **/*.py.
paths:
  - "**/*.py"
---
# Python docstrings (LLM-read)

Critical docstring-discipline reminders for any `.py` file. Read the full canon at `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.documenting-guidelines.md` before writing or editing any docstring; project-specific deltas live at `${CLAUDE_PROJECT_DIR}/docs/guidelines/documenting_guidelines.md` (overlay — read after canon, overrides on conflict).

## Top docstring rules

- **Opening `"""` and closing `"""` each on their own line** — never on the same line as content. Single-line docstrings are still two lines: the opening and closing fence each get a line.
- **Describe external behaviour only** in `Summary` / `Scope` — no implementation details, no internal algorithms, no narration of "how it works", no call sequences, no private-internal references.
- **Domain comments** (`Domain(...)` blocks): no code references (class / method / variable names); describe domain concepts only.
- **No LaTeX anywhere in Python source** — docstrings and `Domain(...)` comments alike. Formulas are plain prose with backticked identifiers and unicode operators (e.g. "the effective factor is `1 - r`, with `r` in `[-1, 1]`"). Obsidian-compatible LaTeX is the concern of the markdown-assembly tooling that collects `Domain(...)` blocks at build time, never of the source.
- **Single backticks for inline code** in docstrings and Domain comments — never double backticks (that is reStructuredText, not the project's flavour).
- **Special-comment preservation** — `TODO:`, `TMP:`, `DBG:`, `ref:`, `opt:`, `guard:`, `limit:`, `Decision:`, and `Domain(...)` comments must never be removed, reworded, or relocated when editing surrounding docstrings. Treat `TMP:`-marked code as non-existent and `TODO:`-marked code as already implemented when writing the Summary/Scope of a containing artifact; treat `limit:`-marked code as complete as written — never describe it as incomplete or in need of the named upgrade, and never carry the ceiling into the docstring; treat `Decision:`-marked code as settled as written — never carry the rationale into the docstring.

Full rules + per-section schemas (Class / Method / Property), Zero-Tolerance Blockers, Preservation Rules, and the 8-point Pre-Return Self-Check: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.documenting-guidelines.md`.

## Hard prohibitions

- **Never write docstrings manually — use the `lazy-python.docstring-writer` agent.** The agent enforces the full canon (section ordering, Zero-Tolerance Blockers, semantic Pre-Return Self-Check, special-comment handling, overlay merging with `${CLAUDE_PROJECT_DIR}/docs/guidelines/documenting_guidelines.md`) which is too long to load into this rule body. Writing docstrings by hand from session-memory of the canon reliably violates at least one of the eight Self-Check clauses; dispatch the agent and let it own the result.
- **Never silently strip or rewrite `TODO:` / `TMP:` / `DBG:` / `ref:` / `opt:` / `guard:` / `limit:` / `Decision:` / `Domain(...)` markers** while touching surrounding docstrings — they are caller-visible invariants, not noise.
- **Never use double backticks for inline code** in docstrings, Domain comments, or any other Python-file prose; the project's flavour is single-backtick only.
