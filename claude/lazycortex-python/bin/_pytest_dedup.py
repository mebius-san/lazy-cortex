"""
Pytest plugin that de-duplicates test items collected more than once via re-export shims.

Some repositories aggregate their suites through re-export shim modules — a
`test_all.py` that star-imports every package, plus per-package shim files that
re-export a package's own test classes. When the `tst` runner scopes a run at the
directory level, every test class defined in a package is then collected twice:
once through its own shim and once through the aggregator. This plugin keeps the
first item collected for each real test function and de-selects the rest, so a
doubly-collected suite runs each test exactly once and stays free of order-dependent
failures caused by shared state between the repeated instances.

The de-duplication key is built from the test `function` (its defining module and
qualified name) plus the parametrization id, never from the node id: a duplicate's
node id differs because it is reached through a different shim file, whereas
`function.__module__` always points at the module where the test is defined. In a
repository without re-export shims no key ever repeats, so the plugin is a no-op and
prints nothing.
"""
from __future__ import annotations

import pytest

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from _pytest.config import Config
  from _pytest.nodes import Item
  from _pytest.terminal import TerminalReporter


# alias for a de-duplication key: (defining module, qualified name, parametrization id)
DedupKey = tuple[str | None, str | None, str | None]

# stash key holding the count of de-selected duplicate items, read back in the summary
DEDUP_COUNT: pytest.StashKey[int] = pytest.StashKey()


# ----------------------------------------------------------------------------------------
# waiver: pytest discovers hook implementations as module-level functions by name — they
# cannot be methods on a class in a `-p`-loaded plugin module
def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
  """
  Drop test items collected more than once through re-export shims.

  The first item seen for each real test function survives; every later duplicate
  is de-selected, mutating the collected-item list in place. Non-function items are
  left untouched.

  Args:
    config: the active pytest configuration for this session.
    items: the collected test items, mutated in place to remove duplicates.
  """
  # track the first item seen for each real test function
  seen: set[DedupKey] = set()
  kept: list[Item] = []
  deselected: list[Item] = []

  for item in items:
    # guard: non-function items (e.g. DoctestItem) expose no `function` — never dedup them
    func = getattr(item, "function", None)
    if func is None:
      kept.append(item)
      continue

    # parametrized items carry a callspec id; unparametrized ones do not
    callspec = getattr(item, "callspec", None)
    key: DedupKey = (
      getattr(func, "__module__", None),
      getattr(func, "__qualname__", None),
      getattr(callspec, "id", None) if callspec is not None else None,
    )

    # keep the first occurrence of each key, de-select the rest
    if key in seen:
      deselected.append(item)
    else:
      seen.add(key)
      kept.append(item)

  # guard: nothing was collected twice — leave the session untouched and stay silent
  if not deselected:
    return

  config.hook.pytest_deselected(items = deselected)
  items[:] = kept
  config.stash[DEDUP_COUNT] = len(deselected)


# ----------------------------------------------------------------------------------------
# waiver: pytest discovers hook implementations as module-level functions by name — they
# cannot be methods on a class in a `-p`-loaded plugin module
def pytest_terminal_summary(terminalreporter: TerminalReporter, config: Config) -> None:
  """
  Print one summary line naming how many re-exported duplicates were removed.

  Prints nothing when no duplicate was de-selected this run.

  Args:
    terminalreporter: the active terminal reporter for the session.
    config: the active pytest configuration for this session.
  """
  # guard: no duplicates were removed this run — print nothing
  count = config.stash.get(DEDUP_COUNT, 0)
  if not count:
    return

  terminalreporter.write_line(f"[lazy-python] deduplicated {count} re-exported test items")
