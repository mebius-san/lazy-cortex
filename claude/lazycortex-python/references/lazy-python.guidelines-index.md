---
description: Entry point for the Python coding standards and conventions shipped by lazycortex-python — splits the guidelines into topic-focused sub-references.
---
# Comprehensive Coding Guidelines — Index

This document is the entry point for the Python coding standards and
conventions shipped by `lazycortex-python`. The guidelines are split
into topic-focused files.

## Sub-files

| File | Purpose |
|---|---|
| `lazy-python.coding-guidelines.md` | Code style, formatting, naming, imports, class/method design, error handling, debug logging, and module-specific patterns. |
| `lazy-python.documenting-guidelines.md` | Docstring rules (class, method, property), comments, marker comments, contract comments, and DOC comments. |
| `lazy-python.testing-guidelines.md` | Test structure, naming, assertions, coverage. |
| `lazy-python.checking-guidelines.md` | CLI tools, verification order, formatter/type-checker/linter configurations. |

## How to use

- **Writing or modifying code**: read `lazy-python.coding-guidelines.md`.
- **Writing or fixing docstrings**: read `lazy-python.documenting-guidelines.md`.
- **Writing or running tests**: read `lazy-python.testing-guidelines.md`.
- **Running checks and QA tools**: read `lazy-python.checking-guidelines.md`.
- **Reviewing code style**: read `lazy-python.coding-guidelines.md` and `lazy-python.documenting-guidelines.md`.

## Portability notes

These guidelines were ported from a sibling Python-backend project and
generalized for reuse. A few notes for readers adopting them in their
own project:

- **CLI tool names.** Commands like `./cli/chk`, `./cli/tst`, `./cli/imp` come from the source project's tool layout. Substitute your project's equivalents (or your own scripts) where they appear in `lazy-python.checking-guidelines.md` and `lazy-python.testing-guidelines.md`.
- **Copyright header.** The `Copyright Headers` section in `lazy-python.coding-guidelines.md` describes the shape of a standard header; adapt the owner and license text to match your project's license.
- **Marker comment system.** `TODO:`, `TMP:`, `DBG:`, `REF:`, `opt:`, `guard:`, `DOC(…):`, `# Contract!`, `# waiver:` are project-wide conventions imported with the rules. Treat them as human-readable annotations; no extraction tooling currently ships with this plugin.
- **Base test class.** References to `<YourBaseTest>` in `lazy-python.testing-guidelines.md` are placeholders for whatever base test class your project ships (or `unittest.TestCase` if there is no project-specific base).
