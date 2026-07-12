"""
Sequential metrics-port allocation for lazycortex runtime daemons.

Ports are handed out in order starting at the base port (9464): the allocator skips ports
already claimed by registered daemons and ports that cannot actually be bound on this host,
and returns the first free one. A repo that already has a metrics port recorded keeps it —
re-running the allocation is idempotent.
"""
from __future__ import annotations

import socket
from pathlib import Path

# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import MetricsNet  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from daemon_registry import RegistryRow, enumerate_local_daemons  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: external JSON contract field name of the metrics-alloc-port CLI, not an internal key
_PORT_KEY = "port"
# waiver: external JSON contract field name of the metrics-alloc-port CLI, not an internal key
_REUSED_KEY = "reused"


def probe_port_free(port: int, bind: str = "127.0.0.1") -> bool:
  """
  Check whether a TCP port can actually be bound on this host right now.

  Args:
    port: TCP port to probe.
    bind: Address to bind the probe socket to.

  Returns:
    True when a bind succeeds (the port is free); False when the bind raises `OSError`.
  """
  probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  try:
    probe.bind((bind, port))
  except OSError:
    return False
  finally:
    probe.close()
  return True


def allocate_port(repo_root: Path, registry: list[dict] | None = None) -> dict:
  """
  Pick a metrics port for the given repo: its recorded one when present, else the first free.

  A repo already registered with metrics enabled keeps its recorded port even when the port
  is currently bound — the listener is that repo's own running daemon. For a new allocation
  the scan walks `MetricsNet.PORT_BASE..PORT_CEIL`, skipping ports recorded by other daemons
  and ports that fail a live bind probe.

  Args:
    repo_root: Absolute path of the repo the port is allocated for.
    registry: Optional pre-computed `enumerate_local_daemons()` result; computed when omitted.

  Returns:
    A dict `{"port": <int>, "reused": <bool>}` — `reused` is True when the repo's existing
    recorded port was kept.

  Raises:
    RuntimeError: If every port in the allocation range is taken.
  """
  registry = registry if registry is not None else enumerate_local_daemons()
  repo_key = str(Path(repo_root).resolve())
  taken: set[int] = set()
  for row in registry:
    # guard: the repo's own registered port is reused verbatim, busy or not — it is ours
    if str(Path(row[RegistryRow.REPO_ROOT]).resolve()) == repo_key and row[RegistryRow.METRICS_ENABLED]:
      return { _PORT_KEY: row[RegistryRow.PORT], _REUSED_KEY: True }
    if row[RegistryRow.METRICS_ENABLED]:
      taken.add(row[RegistryRow.PORT])
  for port in range(MetricsNet.PORT_BASE, MetricsNet.PORT_CEIL + 1):
    # guard: ports recorded by other daemons are off the table even when currently unbound
    if port in taken:
      continue
    if probe_port_free(port):
      return { _PORT_KEY: port, _REUSED_KEY: False }
  raise RuntimeError(
    f"no free metrics port in {MetricsNet.PORT_BASE}..{MetricsNet.PORT_CEIL} — "
    f"{len(taken)} recorded by local daemons, the rest bound by other processes"
  )
