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

The de-duplication key is built from the *collected class* (its defining module and
qualified name) plus the item name, never from the node id: a duplicate's node id
differs because it is reached through a different shim file, whereas the class object
is shared by reference across every shim, so its `__module__` / `__qualname__` always
point at the module where the class is defined. Keying on the class rather than the
test function is essential — an inherited test method is a single function object
shared by every subclass, so a function-based key would wrongly collapse distinct
subclasses into one; the collected class differs per subclass, so it does not. Tests
defined as module-level functions (no class) fall back to a function-based key. The
item name already carries any parametrization suffix, so distinct parameters stay
distinct. In a repository without re-export shims no key ever repeats, so the plugin
is a no-op and prints nothing.
"""
from __future__ import annotations

import pytest

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from _pytest.config import Config
  from _pytest.nodes import Item
  from _pytest.terminal import TerminalReporter


# alias for a de-duplication key: (defining module, qualified name, item name)
DedupKey = tuple[str | None, str | None, str | None]

# stash key holding the count of de-selected duplicate items, read back in the summary
DEDUP_COUNT: pytest.StashKey[int] = pytest.StashKey()


# ----------------------------------------------------------------------------------------
# waiver: pytest discovers hook implementations as module-level functions by name — they
# cannot be methods on a class in a `-p`-loaded plugin module
def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
  """
  Drop test items collected more than once through re-export shims.

  The first item seen for each unique test survives; every later duplicate is
  de-selected, mutating the collected-item list in place. Items that are neither a
  class method nor a plain function are left untouched.

  Guarantees:
    - Only the first item encountered in the input list survives for each de-duplication
      key; every later item sharing that key is de-selected.
    - Surviving items keep their original relative order from the input list.
    - An item that is neither a class method nor a plain function is never de-selected.
    - Every de-selected item is reported through pytest's own `pytest_deselected` hook,
      keeping other plugins and terminal reporters consistent with the trimmed session.

  Args:
    config: the active pytest configuration for this session.
    items: the collected test items, mutated in place to remove duplicates.
  """

  # Contract:
  # For every set of items that share a de-duplication key, only the first
  # item encountered in `items` survives; every later item sharing that key
  # is de-selected.

  # Contract:
  # Every surviving item keeps its original relative order from the input
  # `items` list.

  # Contract:
  # An item that is neither a class method nor a plain function (for example
  # a doctest item) is never de-selected.

  # Domain(pytool.pipeline-idempotency):
  # # Re-export shim over-collection
  # A test suite aggregated through re-export shim modules — an aggregator that star-imports
  # every package plus a per-package shim re-exporting that package's own test classes — collects
  # every test in a package twice when a run is scoped at the directory level: once through its
  # own shim and once through the aggregator. Running the same test twice risks order-dependent
  # failures from state shared between the two collected instances, so each duplicate is
  # de-selected before the run starts, keeping only the first occurrence. A suite with no shims
  # never repeats a test, and this mechanic stays a no-op.

  # track the first item seen for each unique test
  seen: set[DedupKey] = set()
  kept: list[Item] = []
  deselected: list[Item] = []

  # the same test reached through a re-export shim collects twice, keyed identically
  for item in items:
    func = getattr(item, "function", None)
    cls = getattr(item, "cls", None)
    # guard: items that are neither a class method nor a plain function (e.g. DoctestItem) — never dedup them
    if cls is None and func is None:
      kept.append(item)
      continue

    # Domain(pytool.pipeline-idempotency):
    # # Test-item dedup key
    # A duplicated test is identified by the class or function that defines it plus its
    # collected name, never by its node id: two collections of the same real test always reach
    # it through different re-export shims, so their node ids differ even though the underlying
    # class or function object is identical. The key is built from the defining class when one
    # exists, because an inherited test method is a single function object shared by every
    # subclass; keying on the function alone would wrongly treat distinct subclasses as the same
    # duplicated test. A test defined without an owning class falls back to a key built from the
    # function itself. The collected name already carries any parametrization suffix, so distinct
    # parameter sets of the same test remain distinct under this key.

    # Key on the *collected* class, not the function: an inherited method is one function
    # object shared across subclasses, so a function-based key would wrongly collapse
    # distinct subclasses. A re-export shim collects the same class object by reference, so
    # its duplicates still share a key. `item.name` already carries the parametrization
    # suffix, so distinct parameters stay distinct without a separate callspec id.
    if cls is not None:
      key: DedupKey = (cls.__module__, cls.__qualname__, item.name)
    else:
      key = (getattr(func, "__module__", None), getattr(func, "__qualname__", None), item.name)

    # keep the first occurrence of each key, de-select the rest
    if key in seen:
      deselected.append(item)
    else:
      seen.add(key)
      kept.append(item)

  # guard: nothing was collected twice — leave the session untouched and stay silent
  if not deselected:
    return

  # Contract:
  # Every de-selected item is reported through pytest's own `pytest_deselected`
  # hook rather than being silently dropped, so other plugins and terminal
  # reporters observe a consistent, correctly-shrunk session.

  # the duplicates are deselected through the hook so reporters see a consistent session
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

  Guarantees:
    - Nothing is printed to the terminal when no duplicate was de-selected during this
      run's collection phase.

  Args:
    terminalreporter: the active terminal reporter for the session.
    config: the active pytest configuration for this session.
  """

  # Contract:
  # Nothing is printed to the terminal when no duplicate was de-selected
  # during this run's collection phase.

  # guard: no duplicates were removed this run — print nothing
  count = config.stash.get(DEDUP_COUNT, 0)
  if not count:
    return

  # the summary line tells the reader why the collected count dropped
  terminalreporter.write_line(f"[lazy-python] deduplicated {count} re-exported test items")
