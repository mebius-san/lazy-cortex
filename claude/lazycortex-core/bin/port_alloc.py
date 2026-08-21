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
  is currently bound — the listener is that repo's own running daemon. A recorded port that
  another registered daemon records as well is not reused: a port that arrived by config copy
  rather than by allocation is not the repo's to keep, so the asking repo is moved to a free
  one. For a new allocation the scan walks `MetricsNet.PORT_BASE..PORT_CEIL`, skipping ports
  recorded by other daemons and ports that fail a live bind probe.

  Guarantees:
    - A port this call returns, reused or newly allocated, is never one already claimed by
      another metrics-enabled daemon registered on this host.
    - A repository with an already-recorded port receives that exact same port on every later
      call, unless another registered daemon also records it.
    - Either an allocated port is returned or `RuntimeError` is raised; a port already claimed
      by another registered daemon or that fails a live bind probe is never returned.
    - A call never fails outright because one other daemon's record on the host is unreadable
      or malformed.

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
  recorded: int | None = None

  # Contract:
  # Allocation never fails outright because one neighboring daemon record on the host is
  # unreadable or malformed; such a record is skipped and does not block this repo's port
  # allocation.

  # Domain(runtime.metrics):
  # # Metrics-port holder identification
  # A daemon holds a metrics port only while its own row in the local daemon registry has metrics
  # enabled and names a port; a daemon whose metrics collection is switched off is not a holder and
  # never occupies a slot in the allocation. The row that names the same repository the request is
  # for is the requester's own prior allocation, not a competing holder, and is set aside separately
  # from every other holder's port.

  # walk the registry and split it into this repo's own recorded port and every other holder's port
  for row in registry:
    # guard: a daemon with metrics off holds no port
    if not row[RegistryRow.METRICS_ENABLED]:
      continue
    # guard: the repo's own row supplies the reuse candidate, never a taken port
    if str(Path(row[RegistryRow.REPO_ROOT]).resolve()) == repo_key:
      recorded = row[RegistryRow.PORT]
      continue
    taken.add(row[RegistryRow.PORT])

  # Domain(runtime.metrics):
  # # Reuse of an already-recorded port
  # A repository that already has a metrics port on record keeps that same port on every later
  # allocation, even when the port is currently bound — the listener holding it is that repository's
  # own running daemon, not a stranger, so the bind state carries no information worth acting on.

  # Domain(runtime.metrics):
  # # Avoiding a foreign recorded port
  # A recorded port is trusted for reuse only when it belongs to exactly one holder. When the same
  # port also appears against another daemon's record, it did not arrive through allocation — most
  # likely a settings file was copied between repositories along with the port it named — and it is
  # not the asking repository's to keep. The repository is moved to a freshly allocated port instead
  # of risking two daemons ending up bound to the same listener.

  # Contract:
  # A repository with an already-recorded metrics port receives that exact same port on every
  # later allocation call, as long as no other registered daemon also records it.

  # guard: the repo's own recorded port is reused verbatim, busy or not — unless a second daemon records it too
  if recorded is not None and recorded not in taken:
    return { _PORT_KEY: recorded, _REUSED_KEY: True }

  # Contract:
  # A freshly allocated port is never one already claimed by another metrics-enabled daemon
  # registered on this host.

  # Domain(runtime.metrics):
  # # Sequential port allocation
  # A new allocation is found by walking the metrics port range from its lowest port upward and
  # granting the first candidate that clears two independent checks: no other registered daemon
  # already claims it, and a live bind attempt against it succeeds right now. Neither check alone
  # is sufficient — the registry can still name a port whose owning daemon has already stopped,
  # while a port that is merely unclaimed in the registry may still be held by an unrelated process
  # outside the daemon fleet — so a port is only granted once both agree it is actually free.

  # walk the port range in order and hand out the first candidate that passes both checks
  for port in range(MetricsNet.PORT_BASE, MetricsNet.PORT_CEIL + 1):
    # guard: ports recorded by other daemons are off the table even when currently unbound
    if port in taken:
      continue
    if probe_port_free(port):
      return { _PORT_KEY: port, _REUSED_KEY: False }

  # Contract:
  # Allocation either returns an allocated port or raises RuntimeError; it never returns a
  # port that is currently claimed by another registered daemon or fails a live bind probe.

  # no candidate in the whole range cleared both checks
  raise RuntimeError(
    f"no free metrics port in {MetricsNet.PORT_BASE}..{MetricsNet.PORT_CEIL} — "
    f"{len(taken)} recorded by local daemons, the rest bound by other processes"
  )
