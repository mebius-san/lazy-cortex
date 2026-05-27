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
- **DOC comments** (`DOC(...)` blocks): no code references (class / method / variable names); describe domain concepts only.
- **DOC comment formulas**: use Obsidian-compatible LaTeX, not plain text.
- **Single backticks for inline code** in docstrings and DOC comments — never double backticks (that is reStructuredText, not the project's flavour).
- **Special-comment preservation** — `TODO:`, `TMP:`, `DBG:`, `REF:`, `opt:`, `guard:`, and `DOC(...)` comments must never be removed, reworded, or relocated when editing surrounding docstrings. Treat `TMP:`-marked code as non-existent and `TODO:`-marked code as already implemented when writing the Summary/Scope of a containing artifact.

Full rules + per-section schemas (Class / Method / Property), Zero-Tolerance Blockers, Preservation Rules, and the 8-point Pre-Return Self-Check: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.documenting-guidelines.md`.

## Hard prohibitions

- **Never write docstrings manually — use the `lazy-python.docstring-writer` agent.** The agent enforces the full canon (section ordering, Zero-Tolerance Blockers, semantic Pre-Return Self-Check, special-comment handling, overlay merging with `${CLAUDE_PROJECT_DIR}/docs/guidelines/documenting_guidelines.md`) which is too long to load into this rule body. Writing docstrings by hand from session-memory of the canon reliably violates at least one of the eight Self-Check clauses; dispatch the agent and let it own the result.
- **Never silently strip or rewrite `TODO:` / `TMP:` / `DBG:` / `REF:` / `opt:` / `guard:` / `DOC(...)` markers** while touching surrounding docstrings — they are caller-visible invariants, not noise.
- **Never use double backticks for inline code** in docstrings, DOC comments, or any other Python-file prose; the project's flavour is single-backtick only.
