"""
Migrations for the `products` section of `lazy.settings.json`.

v1 -> v2 (`MIGRATIONS[1]`) strips the retired `handoff` block from every product record — the
split-repo cross-repo handoff mechanism (`products[<key>].handoff` stop-gate, consumed by the
now-removed `import_specs.py` primitive) was replaced by `spec.upstream`
(`docs/tasks/lazycortex-specs.upstream.md` § import-pull removal). Idempotent: a record already carrying no
`handoff` key is passed through unchanged.

v2 -> v3 (`MIGRATIONS[2]`) drops the cross-repo bindings: a product's code always lives in the
repository that holds its spec catalog, so the `repo` key leaves every record's `source`, and every
`repo`-kind entry leaves its `dependencies` list. Idempotent: a record carrying neither is passed
through unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: one-off legacy field name for this single stop-gate removal step, not a reusable domain value
_HANDOFF_KEY = "handoff"
# waiver: record field names of the product schema this one migration step reads, not reusable domain values
_SOURCE_KEY = "source"
_DEPENDENCIES_KEY = "dependencies"
_REPO_KEY = "repo"
# the keys that make a dependency entry a `product` or an `external` one, whatever else it carries
_KIND_KEYS = frozenset({ "product", "external" })


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


def _is_repo_dependency(entry: object) -> bool:
  """
  Tell whether one dependency entry is of the retired `repo` kind.

  Args:
    entry: One item of a product record's `dependencies` list.

  Returns:
    True for a dict naming a `repo` and neither a `product` nor an `external`; False otherwise.
  """
  return isinstance(entry, dict) and _REPO_KEY in entry and not entry.keys() & _KIND_KEYS


def _strip_repo_entry(record: object) -> object:
  """
  Drop `source.repo` and every `repo`-kind dependency from one product record, when it is a dict.

  Args:
    record: One `products[<key>]` value, or the section's own non-dict `_version` sentinel.

  Returns:
    `record` unchanged when it is not a dict; otherwise a new dict without `source.repo` and
    without `repo`-kind dependency entries, every other key and entry preserved in order.
  """
  # guard: not a product record at all (the section's own `_version` sentinel) — pass through
  if not isinstance(record, dict):
    return record
  out = dict(record)

  # a dict `source` loses its `repo` key; any other shape is left as found
  if isinstance(out.get(_SOURCE_KEY), dict):
    out[_SOURCE_KEY] = { key: value for key, value in out[_SOURCE_KEY].items() if key != _REPO_KEY }

  # a `dependencies` list loses its `repo`-kind entries and keeps the rest in order
  if isinstance(out.get(_DEPENDENCIES_KEY), list):
    out[_DEPENDENCIES_KEY] = [ entry for entry in out[_DEPENDENCIES_KEY] if not _is_repo_dependency(entry) ]
  return out


def _migrate_strip_repo(data: dict) -> dict:
  """
  Apply the v2 -> v3 cross-repo binding removal across every product record.

  Args:
    data: The `products` section content at v2.

  Returns:
    The section content with `source.repo` and `repo`-kind dependencies removed from every
    product record; every other key, including the section's own `_version` sentinel, preserved.
  """
  return { key: _strip_repo_entry(value) for key, value in data.items() }


MIGRATIONS = {
  1: _migrate_strip_handoff,
  2: _migrate_strip_repo,
}
