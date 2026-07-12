"""
Host-local registry of lazycortex runtime daemons, derived from installed supervisor units.

Every checkout that runs the daemon leaves a supervisor unit behind — a launchd plist
`com.lazycortex.runtime.<REPO_ID>.plist` on macOS or a systemd user unit
`lazy-core-runtime-<REPO_ID>.service` on Linux. Both embed the checkout's absolute path in
the ExecStart shim invocation (`<REPO_ROOT>/.claude/bin/lazy.runtime.sh`). This module reads
those units back and joins each one with its repo's `daemon.metrics` settings, producing the
single source of truth for "all daemons on this machine" — no separate database is kept.

A unit that cannot be parsed is skipped with a warning on stderr; enumeration never fails as
a whole because one unit is malformed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import DaemonKey, MetricsNet, SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: external launchd artifact naming, not internal keys
_PLIST_PREFIX = "com.lazycortex.runtime."
# waiver: external launchd artifact naming, not internal keys
_PLIST_SUFFIX = ".plist"
# waiver: external systemd artifact naming, not internal keys
_SERVICE_PREFIX = "lazy-core-runtime-"
# waiver: external systemd artifact naming, not internal keys
_SERVICE_SUFFIX = ".service"
# waiver: sys.platform token, not a domain constant
_DARWIN = "darwin"
# waiver: regex group name local to this module's shim pattern
_ROOT_GROUP = "root"
# waiver: atomic-write sibling-file idiom, not a domain constant
_TMP_SUFFIX = ".tmp"
# waiver: subprocess wall-clock cap in seconds for a best-effort probe
_LSOF_TIMEOUT_SEC = 10

# The shim path baked into every supervisor unit; the prefix before it is the repo root.
# Plist form:   <string>/abs/repo/.claude/bin/lazy.runtime.sh</string>
# Systemd form: ExecStart=/abs/repo/.claude/bin/lazy.runtime.sh /abs/repo
_SHIM_RE = re.compile(
  r'(?:<string>|ExecStart=)"?(?P<root>.+?)/\.claude/bin/lazy\.runtime\.sh',
)


# ----------------------------------------------------------------------------------------
class RegistryRow:
  """
  Keys of one daemon row as returned by `enumerate_local_daemons`.

  The same names form the external JSON contract of the `daemon-list` CLI subcommand.

  Attributes:
    REPO_ID: The supervisor unit's `<REPO_ID>` segment.
    REPO_ROOT: The absolute repo-root path extracted from the unit.
    REPO_LABEL: The resolved `repo` metric label for the daemon.
    METRICS_ENABLED: Whether the repo's `daemon.metrics.enabled` flag is on.
    BIND: The metrics endpoint bind address.
    PORT: The metrics endpoint TCP port.
  """

  REPO_ID = "repo_id"
  REPO_ROOT = "repo_root"
  REPO_LABEL = "repo_label"
  METRICS_ENABLED = "metrics_enabled"
  BIND = "bind"
  PORT = "port"


# ----------------------------------------------------------------------------------------
class HolderKey:
  """
  Keys of the port-holder dict returned by `identify_holder`.

  Attributes:
    PID: The listening process id.
    COMMAND: The listening process command name.
    REPO_ROOT: The registered daemon repo holding the port, when the listener is one of ours.
  """

  PID = "pid"
  COMMAND = "command"
  REPO_ROOT = "repo_root"


def _xdg_config_home() -> Path:
  """
  Resolve the XDG config home directory for the current user.

  Returns:
    The value of `$XDG_CONFIG_HOME` when set, otherwise `~/.config`.
  """
  # waiver: external XDG env-var name, not a domain constant
  env = os.environ.get("XDG_CONFIG_HOME")
  # guard: explicit XDG override wins over the home-relative default
  if env:
    return Path(env)
  # waiver: XDG default directory name, not a domain constant
  return Path.home() / ".config"


def scrape_targets_path() -> Path:
  """
  Return the canonical location of the host's Prometheus scrape-targets file.

  Returns:
    Absolute path `<XDG config home>/lazycortex/scrape-targets.json`.
  """
  return _xdg_config_home() / MetricsNet.SCRAPE_TARGETS_REL


def _unit_dir(platform: str) -> Path:
  """
  Return the directory holding lazycortex supervisor units for the given platform.

  Args:
    platform: A `sys.platform`-style token; `darwin` selects launchd, anything else systemd.

  Returns:
    `~/Library/LaunchAgents` on macOS; `<XDG config home>/systemd/user` otherwise.
  """
  # guard: macOS keeps per-user launchd agents in a fixed home-relative location
  if platform == _DARWIN:
    # waiver: macOS filesystem layout names, not domain constants
    return Path.home() / "Library" / "LaunchAgents"
  # waiver: systemd user-unit filesystem layout names, not domain constants
  return _xdg_config_home() / "systemd" / "user"


def _unit_names(platform: str) -> list[str]:
  """
  List lazycortex supervisor unit filenames present in the platform's unit directory.

  Args:
    platform: A `sys.platform`-style token, as in `_unit_dir`.

  Returns:
    Sorted unit filenames matching the lazycortex naming convention; empty when the unit
    directory does not exist.
  """
  base = _unit_dir(platform)
  # guard: no unit directory means no daemons are installed on this host
  if not base.is_dir():
    return []
  if platform == _DARWIN:
    prefix, suffix = _PLIST_PREFIX, _PLIST_SUFFIX
  else:
    prefix, suffix = _SERVICE_PREFIX, _SERVICE_SUFFIX
  return sorted(
    name for name in os.listdir(base)
    if name.startswith(prefix) and name.endswith(suffix)
  )


def parse_repo_root_from_unit(text: str) -> str | None:
  """
  Extract the repository root path from a supervisor unit's body.

  Args:
    text: Full text of a launchd plist or systemd service unit.

  Returns:
    The absolute repo-root string preceding the `/.claude/bin/lazy.runtime.sh` shim path,
    or None when the unit does not contain the shim invocation.
  """
  match = _SHIM_RE.search(text)
  # guard: unit without the shim path is not a lazycortex runtime unit
  if match is None:
    return None
  return match.group(_ROOT_GROUP)


def _repo_id_from_unit_name(name: str, platform: str) -> str:
  """
  Recover the `<REPO_ID>` segment from a supervisor unit filename.

  Args:
    name: Unit filename, e.g. `com.lazycortex.runtime.Money-1a2b3c4d.plist`.
    platform: A `sys.platform`-style token, as in `_unit_dir`.

  Returns:
    The identifier between the platform prefix and suffix.
  """
  if platform == _DARWIN:
    return name[len(_PLIST_PREFIX):-len(_PLIST_SUFFIX)]
  return name[len(_SERVICE_PREFIX):-len(_SERVICE_SUFFIX)]


def enumerate_local_daemons(platform: str | None = None) -> list[dict]:
  """
  Enumerate every lazycortex runtime daemon installed on this host.

  Walks the platform's supervisor-unit directory, extracts each unit's repo root, and joins
  it with the repo's merged `daemon.metrics` settings (tracked file plus local overlay).
  Units that cannot be read or parsed, and repos that no longer exist on disk, are skipped
  with a one-line warning on stderr.

  Args:
    platform: Optional `sys.platform` override; defaults to the current platform.

  Returns:
    One dict per daemon with the `RegistryRow` keys, sorted by unit name.
  """
  platform = platform or sys.platform
  base = _unit_dir(platform)
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import metrics
  rows: list[dict] = []
  for name in _unit_names(platform):
    try:
      text = (base / name).read_text()
    except OSError as e:
      sys.stderr.write(f"daemon_registry: skipping unreadable unit {name}: {e}\n")
      continue
    root_str = parse_repo_root_from_unit(text)
    # guard: unit without a parseable repo root cannot be joined with settings — skip, never crash
    if root_str is None:
      sys.stderr.write(f"daemon_registry: skipping unit without shim path: {name}\n")
      continue
    repo_root = Path(root_str)
    # guard: repo deleted while its unit lingered — settings are gone, skip
    if not (repo_root / SettingsFile.REL).is_file():
      sys.stderr.write(f"daemon_registry: skipping unit for missing repo {root_str}: {name}\n")
      continue
    daemon_cfg = load_section(repo_root / SettingsFile.REL, SettingsKey.DAEMON)
    metrics_cfg = daemon_cfg.get(DaemonKey.METRICS) or {}
    rows.append({
      RegistryRow.REPO_ID: _repo_id_from_unit_name(name, platform),
      RegistryRow.REPO_ROOT: str(repo_root),
      RegistryRow.REPO_LABEL: metrics.resolve_repo_label(repo_root, metrics_cfg.get(DaemonKey.REPO_LABEL)),
      RegistryRow.METRICS_ENABLED: bool(metrics_cfg.get(DaemonKey.ENABLED)),
      # waiver: inline network default literal shared with runtime_daemon, not a domain constant
      RegistryRow.BIND: metrics_cfg.get(DaemonKey.BIND, "127.0.0.1"),
      RegistryRow.PORT: int(metrics_cfg.get(DaemonKey.PORT, MetricsNet.PORT_BASE)),
    })
  return rows


def identify_holder(port: int, registry: list[dict] | None = None) -> dict | None:
  """
  Best-effort identification of the process currently listening on a TCP port.

  Uses `lsof` to find the listener and cross-references the daemon registry so a conflict
  with another lazycortex daemon is reported with its repo path.

  Args:
    port: TCP port to inspect.
    registry: Optional pre-computed `enumerate_local_daemons()` result; computed when omitted.

  Returns:
    A dict with the `HolderKey` keys (`repo_root` present only when the port belongs to a
    registered daemon); None when no listener is found or `lsof` is unavailable.
  """
  try:
    proc = subprocess.run(
      # waiver: external lsof CLI flags, not domain constants
      ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"],
      capture_output = True, text = True, check = False, timeout = _LSOF_TIMEOUT_SEC,
    )
  except (FileNotFoundError, subprocess.TimeoutExpired):
    # lsof missing or wedged — holder identification is best-effort only
    return None
  pid: int | None = None
  command: str | None = None
  for line in proc.stdout.splitlines():
    # lsof -F output: `p<pid>` and `c<command>` field lines
    # waiver: external lsof -F field-prefix letters, not domain constants
    if line.startswith("p") and pid is None:
      try:
        pid = int(line[1:])
      except ValueError:
        continue
    # waiver: external lsof -F field-prefix letters, not domain constants
    elif line.startswith("c") and command is None:
      command = line[1:]
  # guard: no listener on the port
  if pid is None:
    return None
  # waiver: fallback command name for a listener lsof could not name
  holder: dict = { HolderKey.PID: pid, HolderKey.COMMAND: command or "unknown" }
  registry = registry if registry is not None else enumerate_local_daemons()
  for row in registry:
    if row[RegistryRow.METRICS_ENABLED] and row[RegistryRow.PORT] == port:
      holder[HolderKey.REPO_ROOT] = row[RegistryRow.REPO_ROOT]
      break
  return holder


def write_scrape_targets_file(out: Path | None = None, registry: list[dict] | None = None) -> dict:
  """
  Write the Prometheus file_sd scrape-targets file covering every metrics-enabled daemon.

  The file is server-blind: each entry carries only a loopback address with the daemon's
  port and the `repo` label — no repo paths, no hostnames, no credentials. The write is
  atomic (sibling temp file + `os.replace`).

  Args:
    out: Optional output path; defaults to `scrape_targets_path()`.
    registry: Optional pre-computed `enumerate_local_daemons()` result; computed when omitted.

  Returns:
    A dict with `path` (the written file), `count` (number of targets), and `targets`
    (the file content that was written).
  """
  registry = registry if registry is not None else enumerate_local_daemons()
  targets = []
  for row in registry:
    # guard: daemons without metrics contribute no scrape target
    if not row[RegistryRow.METRICS_ENABLED]:
      continue
    # a wildcard bind is scraped over loopback; anything else is scraped at its bind address
    # waiver: inline network literals, not domain constants
    address = "127.0.0.1" if row[RegistryRow.BIND] in ("0.0.0.0", "::") else row[RegistryRow.BIND]
    targets.append({
      # waiver: external Prometheus file_sd schema field names, not internal keys
      "targets": [f"{address}:{row[RegistryRow.PORT]}"],
      # waiver: external Prometheus file_sd schema field names, not internal keys
      "labels": { "repo": row[RegistryRow.REPO_LABEL] },
    })
  path = out or scrape_targets_path()
  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_suffix(path.suffix + _TMP_SUFFIX)
  tmp.write_text(json.dumps(targets, indent = 2) + "\n")
  os.replace(tmp, path)
  # waiver: external JSON contract field names of the metrics-scrape-file CLI, not internal keys
  return { "path": str(path), "count": len(targets), "targets": targets }
