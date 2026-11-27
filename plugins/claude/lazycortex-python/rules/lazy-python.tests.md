---
description: Python test placement, naming, and writing discipline — use the lazy-python.test-writer agent. Triggers on tests/**/*.py.
paths:
  - "tests/**/*.py"
---
# Python tests (LLM-read)

Critical test-discipline reminders for any `tests/**/*.py` file. Read the full canon at `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.testing-guidelines.md` before writing or editing any test; project-specific deltas live at `${CLAUDE_PROJECT_DIR}/docs/guidelines/python/testing_guidelines.md` (overlay — read after canon, overrides on conflict).

## Top test placement & naming rules

- **Tests live at `tests/<module>/`** — the test tree mirrors the project's source layout. A class under `<module>/foo/bar.py` has its tests at `tests/<module>/foo/test_bar.py`.
- **Base test class is project-specific** — the canonical inheritance chain (which `BaseTest` subclass each test type inherits from, and the rules for picking it) lives in `${CLAUDE_PROJECT_DIR}/docs/guidelines/python/testing_guidelines.md`. The plugin canon does not hardcode a class name — every project's test scaffolding differs.
- **Method naming, max 37 chars**: `test_init`, `test_prop__<name>`, `test_feature__<variation>`. Double underscore separates the subject from the variation.
- **One test method per behaviour** — no multi-behaviour tests, no parametrize-as-disguised-multi-test for unrelated cases.
- **No `setUp` / `tearDown` / `setup_method` / `teardown_method`** — pytest fixtures only. Per-test setup goes in fixtures or `__init__`-style construction inside the test.

Full categories (Paranoid Testing Strategy — 9 mandatory test types, the last three derived from `Contract:`, `Domain(…):`, and `opt:` markers in method bodies), coverage minimums, assertion conventions, fixture patterns, and project-overlay merging: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.testing-guidelines.md`.

## Hard prohibitions

- **Never write tests manually — use the `lazy-python.test-writer` agent.** The agent enforces the full canon (Paranoid Testing Strategy 9-category coverage, coverage minimums, assertion conventions, base-class selection per the overlay, special-comment preservation) which is too long to load into this rule body. Hand-writing tests from session-memory of the canon reliably skips at least one of the nine categories or picks the wrong base class; dispatch the agent and let it own the result.
- **A regression test is written before the fix, never after.** A test added once the bug is already fixed proves nothing — it never ran red. Run it against the unchanged code first and watch it fail for the cause the report describes. It lands as one more method in the existing `tests/<module>/…/test_<source>.py` for the file that carried the defect, named for the behaviour it pins — never a `test_bug_<id>.py` or a regression directory. Full policy: the canon's *Fixing a Bug* section.
- **Never change what an existing test asserts, and never bend code to an outdated test, without the user's "yes".** The full policy — judging which side is wrong, what counts as a behaviour change, what is free, and the ban on excluding a test from the run — is the `lazy-python.failing-tests` rule.
- **Never test a stub** — a method whose body is a placeholder under `# TODO:` gets no test; a test method that must exist stays empty under a `# TODO:` naming the stub it waits for.

## Isolation and cost

Full text with the reasons and the ways to comply: the canon's *Isolation and Cost* section.

### Safety — every test, every run

- **A test never writes to a resource it does not own** — the working tree, the home directory, the user's caches and config, or a real database or service the machine uses for anything else. When the code under test resolves such a resource from the environment, the test points it at a test-owned one.

### Parallel safety — where the suite runs in parallel

- **Tests share no mutable data.** A shared test store (a test database, a common scratch directory) is fine when each test creates its own records under unique keys or names and reads, asserts and removes only those; a test never counts, truncates or rewrites a whole collection and never relies on a fixed id.
- **Every test passes in any order.** No test depends on what an earlier test left behind.
- **Global state is changed only through a mechanism that restores it** — environment variables and module-level values go through `monkeypatch` or its equivalent.

### Cost — every test

- **In-process over out-of-process.** A test calls the code under test directly; a subprocess, a network call or a real service is used only where that boundary itself is what the test proves.
- **Expensive setup shared by many tests is built once and reused.** A repository, a database schema, a seeded object graph is prepared once per session and copied, cloned or rolled back for each test, never rebuilt from scratch in every one.
- **No real waits.** A test of a timeout, poll or retry window sets that window to zero or its minimum through config or env; it never sleeps through a production default.
- **A unit test slower than 0.5 s is a finding.** Its cause is one of the above and is fixed rather than accepted.
