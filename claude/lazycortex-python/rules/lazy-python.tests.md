---
description: Python test placement, naming, and writing discipline — use the lazy-python.test-writer agent. Triggers on tests/**/*.py.
paths:
  - "tests/**/*.py"
---
# Python tests (LLM-read)

Critical test-discipline reminders for any `tests/**/*.py` file. Read the full canon at `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.testing-guidelines.md` before writing or editing any test; project-specific deltas live at `${CLAUDE_PROJECT_DIR}/docs/guidelines/testing_guidelines.md` (overlay — read after canon, overrides on conflict).

## Top test placement & naming rules

- **Tests live at `tests/<module>/`** — the test tree mirrors the project's source layout. A class under `<module>/foo/bar.py` has its tests at `tests/<module>/foo/test_bar.py`.
- **Base test class is project-specific** — the canonical inheritance chain (which `BaseTest` subclass each test type inherits from, and the rules for picking it) lives in `${CLAUDE_PROJECT_DIR}/docs/guidelines/testing_guidelines.md`. The plugin canon does not hardcode a class name — every project's test scaffolding differs.
- **Method naming, max 35 chars**: `test_init`, `test_prop__<name>`, `test_feature__<variation>`. Double underscore separates the subject from the variation.
- **One test method per behaviour** — no multi-behaviour tests, no parametrize-as-disguised-multi-test for unrelated cases.
- **No `setUp` / `tearDown` / `setup_method` / `teardown_method`** — pytest fixtures only. Per-test setup goes in fixtures or `__init__`-style construction inside the test.

Full categories (Paranoid Testing Strategy — 7 mandatory test types), coverage minimums, assertion conventions, fixture patterns, and project-overlay merging: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.testing-guidelines.md`.

## Hard prohibitions

- **Never write tests manually — use the `lazy-python.test-writer` agent.** The agent enforces the full canon (Paranoid Testing Strategy 7-category coverage, coverage minimums, assertion conventions, base-class selection per the overlay, special-comment preservation) which is too long to load into this rule body. Hand-writing tests from session-memory of the canon reliably skips at least one of the seven categories or picks the wrong base class; dispatch the agent and let it own the result.
- **Never modify existing tests as a "fix" for a failing assertion** — a failing test means production code drifted from the contract the test encodes. Fix the code, not the test. Edits to existing tests require explicit, contemporaneous user approval naming the test by name (per project-level test-edit policy).
