"""
Migrations for the `agent_models` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) moves the lazycortex-specs agent onto the plugin's own
namespace: a dispatch key `lazycortex-specs:spec.<name>` becomes
`lazycortex-specs:lazy-spec.<name>`, keeping its tier. Every other dispatch key
is passed through unchanged, as is a section already on the new key. Add
`2: lambda data: <transformed>` here when a v2 → v3 migration is needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# the dispatch-key prefix a specs agent carried before the plugin took its own namespace
_SPEC_AGENT_OLD_PREFIX = "lazycortex-specs:spec."
_SPEC_AGENT_NEW_PREFIX = "lazycortex-specs:lazy-spec."


def _renamespace_bucket(bucket: object) -> object:
  """
  Rewrite one tier bucket's specs dispatch keys onto the plugin's own namespace.

  Args:
    bucket: One value from the section — a tier bucket mapping dispatch keys to model
      tiers, or the section's own `_version` scalar.

  Returns:
    The bucket with every lazycortex-specs dispatch key re-prefixed, or the input
    unchanged when it is not a bucket or carries no such key.
  """
  # guard: the section also carries its own `_version` scalar alongside the buckets
  if not isinstance(bucket, dict):
    return bucket

  # the rename is per-key; an agent from any other plugin keeps its own dispatch key
  return {
    (_SPEC_AGENT_NEW_PREFIX + k[len(_SPEC_AGENT_OLD_PREFIX):]
     if isinstance(k, str) and k.startswith(_SPEC_AGENT_OLD_PREFIX) else k): v
    for k, v in bucket.items()
  }


MIGRATIONS: dict[int, Callable[[dict], dict]] = {
  # v1 → v2: lazycortex-specs dispatch keys onto the plugin's own namespace.
  1: lambda data: { bk: _renamespace_bucket(bv) for bk, bv in data.items() },
}
