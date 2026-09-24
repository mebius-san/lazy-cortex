"""
Migrations for the `daemon` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) renames the daemon's `git.branch` field to
`git.base_branch`, reflecting the move off a perpetual daemon-exclusive branch
onto the operator's base branch. A section without a `git` block, or one whose
`git` block carries no `branch` key, passes through untouched. The section dict
is the daemon block itself, so the transform operates on `data["git"]` directly.

v2 → v3 (`MIGRATIONS[2]`) seeds the `rate_limit_guard` block that stops the daemon
as the subscription window approaches exhaustion. Every trigger is seeded enabled —
the guard exists to protect the subscription, so disabling one is a deliberate act.
A section that already carries the block passes through untouched.

v3 → v4 (`MIGRATIONS[3]`) raises a seeded `stream_idle_timeout_sec` of `90` — the old
shipped default the installer wrote verbatim — to `900`: opus-tier expert spawns
legitimately stay silent for minutes while thinking, and the 90-second watchdog was
killing live processes. Only the exact old seeded literal migrates; any other value is
the operator's own choice and passes through untouched, as does a section without the
key (the raised code default covers it).
Add `4: lambda data: <transformed>` here when a v4 → v5 migration is needed.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from constants import DaemonKey, RateLimitGuardKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


MIGRATIONS = {
  # v1 → v2: git.branch -> git.base_branch.
  1: lambda data: {
    **data,
    "git": {
      **{ k: v for k, v in data["git"].items() if k != "branch" },
      "base_branch": data["git"]["branch"],
    },
  } if (
    isinstance(data.get("git"), dict)
    and "branch" in data["git"]
  ) else data,
  # v2 → v3: seed daemon.rate_limit_guard, every trigger enabled.
  2: lambda data: {
    **data,
    DaemonKey.RATE_LIMIT_GUARD: {
      RateLimitGuardKey.ENABLED:            True,
      RateLimitGuardKey.ON_ALLOWED_WARNING: True,
      RateLimitGuardKey.ON_REJECTED:        True,
      RateLimitGuardKey.ON_OVERAGE:         True,
    },
  } if not isinstance(data.get(DaemonKey.RATE_LIMIT_GUARD), dict) else data,
  # v3 → v4: the old seeded stream-idle default (90) rises to 900; operator values untouched.

  # Domain(settings.versioning):
  # # A migration raises a default only where it finds its own old seed
  # A migration step that raises a numeric default recognizes its own earlier work: it replaces the
  # value only where it still equals the exact literal that was shipped as the old default. Any other
  # value present is the operator's own deliberate choice and is left untouched, and a setting that is
  # absent entirely is left unseeded, because the raised code default already covers it once nothing
  # overrides it. Because the check only reacts to its own former seed, re-running the step costs
  # nothing, and an operator's edit survives any number of upgrades.

  3: lambda data: {
    **data,
    DaemonKey.STREAM_IDLE_TIMEOUT_SEC: 900,
  } if (
    isinstance(data.get(DaemonKey.STREAM_IDLE_TIMEOUT_SEC), int)
    and data.get(DaemonKey.STREAM_IDLE_TIMEOUT_SEC) == 90
  ) else data,
}
