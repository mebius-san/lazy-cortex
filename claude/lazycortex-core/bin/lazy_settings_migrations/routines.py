"""
Migrations for the `routines` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) rewrites every routine entry's flat
`frontmatter_filter` into the composite `filter.frontmatter` block, converting
each predicate value `<list-or-scalar>` into `{ in: <list>, not_in: [] }`. A
routine already on the new-shape `filter` is left untouched. The section dict is
the routines map itself, so the transform iterates routine entries directly,
skipping the `_version` key and any non-dict value. Add
`2: lambda data: <transformed>` here when a v2 → v3 migration is needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


MIGRATIONS = {
  # v1 → v2: frontmatter_filter -> filter.frontmatter with {in,not_in} predicates.
  1: lambda data: {
    rk: (
      {
        **{ k: v for k, v in rv.items() if k != "frontmatter_filter" },
        "filter": {
          **rv.get("filter", {}),
          "frontmatter": {
            pk: {
              "in": pv if isinstance(pv, list) else [ pv ],
              "not_in": [],
            }
            for pk, pv in rv["frontmatter_filter"].items()
          },
        },
      }
      if isinstance(rv, dict) and "frontmatter_filter" in rv
      else rv
    )
    for rk, rv in data.items()
  },
}
