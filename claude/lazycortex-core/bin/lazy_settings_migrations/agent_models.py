"""
Migrations for the `agent_models` section of `lazy.settings.json`.

Empty — `agent_models` is at version 1 (the initial version) and has no
upgrades yet. Add `1: lambda data: <transformed>` here when a v1 → v2
migration is needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


MIGRATIONS: dict[int, Callable[[dict], dict]] = {}
