---
description: What to do when a test fails — judge which side is wrong before touching either, never bend correct code to an outdated test, never edit what a test asserts or exclude it from the run without the user's explicit yes.
paths:
  - "**/*.py"
  - "**/pyproject.toml"
  - "**/pytest.ini"
  - "**/setup.cfg"
  - "**/tox.ini"
---
# Failing tests

A failing test is a question, not an instruction. The answer is the user's whenever it changes what the suite proves.

## 1. Decide which side is wrong

- **The code is wrong** — it breaks a contract that still holds. Fix the code.
- **The test is outdated** — the code changed on purpose and the test still encodes the old contract. Never bend the code to satisfy it. Stop, show the test, the intended change it contradicts and the proposed test diff, and ask via `AskUserQuestion`.
- **Unsure which** — ask. Never settle the question by changing either side.

Degrading correct code to turn a test green is forbidden, whatever the form: reverting an intended change, keeping a removed parameter, field or code path alive only because a test still uses it, adding a branch for the test's input, hardcoding the expected value.

## 2. Never change what a test asserts without a "yes" naming the test

The line is behaviour, not location. Forbidden without the "yes": editing, weakening or deleting an assertion, its expected value or tolerance; changing a fixture or test data so a different scenario runs; deleting a test or a test file; regenerating tests after a refactor.

Free without asking, because behaviour stays byte-identical: comments, docstrings, assert messages, test and helper names, formatting; renaming, moving, splitting or merging test files when every assertion survives; repeating a production rename in the tests that import or call the renamed symbol. Adding new test files is always allowed.

Rule of thumb: if the edit could turn a failing test green or a passing one red, it needs the "yes".

## 3. Never take a test out of the run

Forbidden without a "yes" naming the test:

- `--deselect`, `-k "not ..."`, `--ignore`, `--ignore-glob`, passed to `tst-py` or written into `addopts`.
- `collect_ignore`, `collect_ignore_glob`, `pytest_collection_modifyitems`, or any other hook that drops tests from collection.
- Narrowing `testpaths` or `python_files` so a test is no longer collected.
- New `skip`, `skipif` or `xfail` markers.
- Running a subset and reporting the suite green.

Being sure the test is wrong is a reason to ask, never a reason to exclude it. The test stays in the run until the user says otherwise.

## 4. Without an operator

A job with no operator in the loop (an expert job, a non-interactive subagent) cannot ask directly. It leaves the test in the run and failing, raises the question through the escalation channel the job already has, and finishes as blocked, never as done.
