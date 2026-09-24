"""
Migrations for the `spec` section of `lazy.settings.json`.

v1 -> v2 (`MIGRATIONS[1]`) strips the retired `imports` array — the split-repo pull-side channel
(`spec.imports[]`, consumed by the now-removed `import_specs.py` primitive and the
`spec.import-pull` routine) was replaced by `spec.upstream`
(`docs/tasks/lazycortex-specs.upstream.md` § import-pull removal). Idempotent: a section already carrying no
`imports` key is passed through unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: one-off legacy field name for this single pull-side removal step, not a reusable domain value
_IMPORTS_KEY = "imports"


def _migrate_strip_imports(data: dict) -> dict:
  """
  Apply the v1 -> v2 `imports` array removal.

  Args:
    data: The `spec` section content at v1.

  Returns:
    The section content with the `imports` key removed when present; every other key, including
    `_version`, preserved.
  """
  return { key: value for key, value in data.items() if key != _IMPORTS_KEY }


MIGRATIONS = {
  1: _migrate_strip_imports,
}
