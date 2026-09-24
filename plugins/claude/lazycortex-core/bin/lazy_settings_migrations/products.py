"""
Migrations for the `products` section of `lazy.settings.json`.

v1 -> v2 (`MIGRATIONS[1]`) strips the retired `handoff` block from every product record — the
split-repo cross-repo handoff mechanism (`products[<key>].handoff` stop-gate, consumed by the
now-removed `import_specs.py` primitive) was replaced by `spec.upstream`
(`docs/tasks/lazycortex-specs.upstream.md` § import-pull removal). Idempotent: a record already carrying no
`handoff` key is passed through unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: one-off legacy field name for this single stop-gate removal step, not a reusable domain value
_HANDOFF_KEY = "handoff"


def _strip_handoff_entry(record: object) -> object:
  """
  Drop the `handoff` key from one product record, when it is a dict.

  Args:
    record: One `products[<key>]` value, or the section's own non-dict `_version` sentinel.

  Returns:
    `record` unchanged when it is not a dict (the `_version` sentinel passes straight through);
    otherwise a new dict with `handoff` removed and every other key preserved.
  """
  # guard: not a product record at all (the section's own `_version` sentinel) — pass through
  if not isinstance(record, dict):
    return record
  return { key: value for key, value in record.items() if key != _HANDOFF_KEY }


def _migrate_strip_handoff(data: dict) -> dict:
  """
  Apply the v1 -> v2 `handoff` removal across every product record.

  Args:
    data: The `products` section content at v1.

  Returns:
    The section content with `handoff` stripped from every product record; every other key,
    including the section's own `_version` sentinel, preserved.
  """
  return { key: _strip_handoff_entry(value) for key, value in data.items() }


MIGRATIONS = {
  1: _migrate_strip_handoff,
}
