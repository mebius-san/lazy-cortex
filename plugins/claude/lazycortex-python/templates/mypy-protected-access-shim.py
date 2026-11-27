# Managed by /lazy-python.install (Step 2) — edit the template, not this copy.
"""
Consumer-side mypy plugin shim for the `protected-access` check.

Resolves the live lazycortex-python install at mypy start-up and delegates to its
`bin/mypy_protected_access.py`, so the consumer's `plugins = ["cli/mypy/protected_access.py"]`
entry survives plugin version bumps without a frozen path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from types import ModuleType

  # waiver: consumers do not set `extension-pkg-allow-list = ["mypy"]`, so pylint cannot introspect compiled mypy
  from mypy.plugin import Plugin  # pylint: disable=no-name-in-module


_BIN_REL = "bin/mypy_protected_access.py"
_MODULE_NAME = "lazycortex_mypy_protected_access"
_PLUGIN_KEY = "lazycortex-python"
# The shared plugin locator, deployed beside the wrappers one directory above this shim, and the name it loads under
_LOCATOR_FILE = Path(__file__).resolve().parents[1] / "lazy_python_locator.py"
_LOCATOR_MODULE = "lazycortex_python_plugin_locator"


def _load_locator() -> ModuleType:
  """
  Load the plugin locator deployed in the consumer's `cli/` directory.

  Returns:
    The loaded locator module.

  Raises:
    RuntimeError: When the locator is not deployed or cannot be loaded.
  """

  # Decision: load by file path, not through `sys.path` — mypy asserts after importing a plugin that the plugin's own
  # directory still heads `sys.path`, and a path load cannot pick up another module of the same name.

  # the import spec of the deployed locator, named apart from any other module
  spec = importlib.util.spec_from_file_location(_LOCATOR_MODULE, _LOCATOR_FILE)

  # guard: without the deployed locator the plugin cannot be located at all
  if not _LOCATOR_FILE.is_file() or spec is None or spec.loader is None:
    raise RuntimeError(f"the plugin locator {_LOCATOR_FILE} is missing; re-run /lazy-python.install")

  # run the locator's module body under its own name
  module = importlib.util.module_from_spec(spec)
  sys.modules[_LOCATOR_MODULE] = module
  spec.loader.exec_module(module)
  return module


def _resolve() -> Path:
  """
  Locate the plugin file of the lazycortex-python install this repository uses.

  Returns:
    The path of `bin/mypy_protected_access.py` inside the located plugin.

  Raises:
    RuntimeError: When the plugin is not found, or the found plugin carries no plugin file; the message names every
      place searched and the repair route.
  """

  # the plugin wherever the shared locator finds it, starting from the shim's own place in the checkout; a plugin found
  # nowhere stops the type check with an error naming every place searched
  locator = _load_locator()
  try:
    root, _stage = locator.plugin_root(_PLUGIN_KEY, Path(__file__).resolve().parent)
  except locator.PluginNotFoundError as error:
    raise RuntimeError(f"{error}; install/enable it or re-run /lazy-python.install") from error

  # guard: a located plugin without the plugin file cannot serve
  if not (root / _BIN_REL).is_file():
    raise RuntimeError(f"lazycortex-python at {root} carries no {_BIN_REL}; re-run /lazy-python.install")
  return root / _BIN_REL


# Decision: resolve at import, not inside plugin() — mypy reports an exception raised while importing the plugin file
# with its message ("Error importing plugin"), but one raised from plugin() as an opaque INTERNAL ERROR.

# The resolved plugin file; a failed resolution aborts the import here
_PLUGIN_FILE = _resolve()


def plugin(version: str) -> type[Plugin]:
  """
  Load the resolved plugin module and return its `Plugin` class to mypy's plugin loader.

  Args:
    version: The mypy version string, passed through to the real entry point.

  Returns:
    The `Plugin` subclass the resolved module provides.

  Raises:
    RuntimeError: When the resolved path cannot be loaded as a module.
  """
  # guard: a path that cannot be loaded as a module is as fatal as a missing one
  if (spec := importlib.util.spec_from_file_location(_MODULE_NAME, _PLUGIN_FILE)) is None or spec.loader is None:
    raise RuntimeError("lazycortex-python plugin not loadable; re-run /lazy-python.install")

  # register before exec so dataclasses and pickling inside the plugin can find the module
  module = importlib.util.module_from_spec(spec)
  sys.modules[_MODULE_NAME] = module
  spec.loader.exec_module(module)

  # hand mypy the plugin class of the resolved module
  # waiver: the dynamically loaded module is untyped, so the annotated local gives the entry point's result its type
  result: type[Plugin] = module.plugin(version)
  return result
