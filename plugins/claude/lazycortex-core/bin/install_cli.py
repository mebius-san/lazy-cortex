"""
Install-phase verbs for the `lazycortex-core` CLI.

This module backs the `install-phase` and `daemon-run-here` subcommands the
`lazy-core.install` and `lazy-core.doctor` skills call instead of embedding Python.
`install-phase <name>` runs one idempotent bootstrap phase from `lazy_install_phases` (or a
one-line derivation such as the repo id or the interpreter path) and prints the phase's
outcome word; `daemon-run-here` reads or writes the `daemon.run_here` host-to-checkout gate
for the current host. The repository root follows the dispatcher convention: the
`LAZY_REPO_ROOT` env var, falling back to the process working directory, overridable
per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import DaemonKey, SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_install_phases import (  # pylint: disable=import-error
  bootstrap_daemon_git,
  bootstrap_lazy_settings_local_gitignore,
  bootstrap_lazyignore,
  bootstrap_logs_dir,
  bootstrap_memory_dir,
  migrate_log_hooks,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section, load_tracked_section, save_section  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# waiver: shipped template location relative to this bin/ dir, fixed by the plugin layout
_LAZYIGNORE_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / ".lazyignore"

# waiver: daemon settings field names seeded absent-only by install; the pump reads them as literals too
_DAEMON_DEFAULTS: dict[str, object] = {
  DaemonKey.ENABLED: False,
  DaemonKey.POLLING_INTERVAL_SEC: 5,
  "cleanup_completed_after": "7d",
  "cleanup_failed_after": "30d",
  "cleanup_dead_after": "7d",
  DaemonKey.STREAM_IDLE_TIMEOUT_SEC: 900,
  "stream_max_retries": 3,
}

# waiver: external Claude Code settings locations, not reusable domain keys
_LOG_HOOK_SETTINGS = ( ".claude/settings.json", ".claude/settings.local.json" )

# width of the SHA-256 prefix that keeps two same-named checkouts apart in the supervisor unit name
_REPO_ID_HASH_LEN = 8


def _read_short_host() -> str:
  """
  Return this machine's short hostname, lowercased, as the `run_here` gate keys it.

  Returns:
    The hostname up to its first dot, lowercased.
  """
  return socket.gethostname().split(".")[0].lower()


def _run_phase_logs(root: Path, template: Path) -> None:
  """
  Run the logs phase: runtime dirs, the local-settings gitignore slot, and the `.lazyignore` seed.

  Args:
    root: Repository root the phase bootstraps.
    template: Shipped `.lazyignore` template to seed from.
  """
  # waiver: outcome-line labels read by the install skill, not reusable domain keys
  print(".logs/+.runtime/:", bootstrap_logs_dir(root))
  # waiver: outcome-line labels read by the install skill, not reusable domain keys
  print("lazy.settings.local.json:", bootstrap_lazy_settings_local_gitignore(root))
  # waiver: outcome-line labels read by the install skill, not reusable domain keys
  print(".lazyignore:", bootstrap_lazyignore(root, template))


def _run_phase_log_hooks(root: Path) -> None:
  """
  Run the log-hooks phase: strip retired log-hook commands from project and user settings.

  Args:
    root: Repository root whose `.claude/` settings are migrated alongside the user's.
  """
  # both scopes are migrated — the retired hooks were installed at whichever scope the plugin was
  for rel in _LOG_HOOK_SETTINGS:
    for base in (root, Path.home()):
      path = base / rel
      print(f"{path}: {migrate_log_hooks(path)}")


def _run_phase_daemon_defaults(root: Path) -> None:
  """
  Run the daemon-defaults phase: seed absent daemon keys, the git block, and the routines section.

  Args:
    root: Repository root whose tracked settings receive the seeds.

  Raises:
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """
  settings = root / SettingsFile.REL

  # Domain(install.reconciliation):
  # # Defaults are seeded only where a key is absent
  # Installing seeds each daemon default only into a key the settings do not carry yet; a value
  # already present is left exactly as it is, whatever it says, so re-running the install never
  # overwrites an operator's choice and the phase is idempotent. The outcome word tells a run that
  # added at least one key apart from one that found everything already present. The routines
  # section follows the same rule: it is created empty only when the file has no such section.

  # seed the absent daemon keys and report whether anything changed
  section = load_tracked_section(settings, SettingsKey.DAEMON)
  # waiver: the snapshot must be taken before the seeding loop mutates the section in place; the outcome
  # word compares the two states, so the copy cannot be inlined at its single read below
  before = dict(section)
  for key, value in _DAEMON_DEFAULTS.items():
    section.setdefault(key, value)
  save_section(settings, SettingsKey.DAEMON, section)
  # waiver: outcome-line labels and tokens read by the install skill, not reusable domain keys
  print("daemon: bootstrapped" if section != before else "daemon: already-present")

  # the git block is seeded by its own bootstrap, which reports its outcome word
  # waiver: outcome-line label read by the install skill, not a reusable domain key
  print("git: " + bootstrap_daemon_git(root))

  # the routines section is seeded empty so the daemon's reader finds a section, not a stub
  if SettingsKey.ROUTINES not in (json.loads(settings.read_text()) if settings.exists() else {}):
    save_section(settings, SettingsKey.ROUTINES, {})
    # waiver: outcome-line label and token read by the install skill, not reusable domain keys
    print("routines: bootstrapped")
  else:
    # waiver: outcome-line label and token read by the install skill, not reusable domain keys
    print("routines: already-present")


def _compute_repo_id(root: Path) -> str:
  """
  Derive the supervisor unit's repo id from the checkout's absolute path.

  Args:
    root: Repository root the id names.

  Returns:
    The root's basename joined to the first eight hex digits of the path's SHA-256.
  """
  # the basename keeps the unit name readable; the hash keeps two same-named checkouts apart
  absolute = os.path.abspath(root)
  return os.path.basename(absolute) + "-" + hashlib.sha256(absolute.encode()).hexdigest()[:_REPO_ID_HASH_LEN]


# waiver: phase names are the install-phase verb's own vocabulary; every phase takes (root, template)
# waiver: declared below the phase functions it references rather than in the constants section — a
# module-level table cannot forward-reference functions defined later in the file
_PHASES: dict[str, Callable[[Path, Path], None]] = {
  "logs": _run_phase_logs,
  "log-hooks": lambda root, _template: _run_phase_log_hooks(root),
  "memory-dir": lambda root, _template: print(bootstrap_memory_dir(root)),
  "daemon-defaults": lambda root, _template: _run_phase_daemon_defaults(root),
  "daemon-git": lambda root, _template: print(bootstrap_daemon_git(root)),
  "repo-id": lambda root, _template: print(_compute_repo_id(root)),
  "interpreter": lambda _root, _template: print(sys.executable),
}


def cmd_install_phase(argv: list[str]) -> int:
  """
  Run the `install-phase` subcommand: execute one named bootstrap phase and print its outcome.

  Args:
    argv: Argument vector after the subcommand name (phase name, optional `--template`, `--cwd`).

  Returns:
    Process exit code: 0 on success.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """
  # the verb's command line: the phase name, the template override, and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core install-phase")
  # waiver: argparse CLI signature — phase names are this verb's own vocabulary
  parser.add_argument("phase", choices = list(_PHASES))
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--template", default = None, help = "Path to the .lazyignore template (logs phase)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # each phase prints exactly what its former inline snippet printed, so the skill's readers keep working
  _PHASES[args.phase](resolve_repo_root(args.cwd), Path(args.template) if args.template else _LAZYIGNORE_TEMPLATE)
  return 0


def _normalize_gate(gate: dict[object, object]) -> dict[str, object]:
  """
  Normalize a `daemon.run_here` gate to lowercase, stripped host keys.

  Args:
    gate: The gate mapping as recorded in settings, keyed by host however it was spelled.

  Returns:
    The same entries keyed by the host's short name in lowercase with surrounding whitespace removed.
  """
  return { str(key).strip().lower(): val for key, val in gate.items() }


def evaluate_run_here(root: Path) -> str:
  """
  Classify the `daemon.run_here` gate for this host against the given checkout.

  Args:
    root: Checkout the gate is tested against.

  Returns:
    `unset` when no gate is configured, `invalid-shape` when it is not a mapping,
    `not-this-host` when this host has no entry, `run-here` when the entry names this
    checkout, `not-this-checkout` when it names another.

  Raises:
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """

  # Domain(runtime.authorization):
  # # One authorized host-and-checkout pair per repository
  # A repository names, per host, the single checkout allowed to run its autonomous runtime. The
  # gate is keyed by the host's short name compared case-insensitively, and the named checkout
  # matches only when both paths resolve to the same location on disk, so a symlinked or
  # differently spelled path to the same directory still counts. A missing gate, a gate that is
  # not a mapping, a host absent from it, and a host mapped to another checkout are four distinct
  # verdicts; only an exact match authorizes a run here.

  # guard: anything but a mapping cannot name a checkout for this host
  if not isinstance(gate := load_section(root / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.RUN_HERE), dict):
    # waiver: CLI outcome tokens read by the install skill, not reusable domain keys
    return "unset" if gate is None else "invalid-shape"

  # guard: a host absent from the gate never runs a daemon
  if (mapped := _normalize_gate(gate).get(_read_short_host())) is None:
    # waiver: CLI outcome token read by the install skill, not a reusable domain key
    return "not-this-host"

  # the entry authorizes this checkout only when both paths resolve to the same location
  # waiver: CLI outcome tokens read by the install skill, not reusable domain keys
  return (
    "run-here" if Path(str(mapped)).expanduser().resolve() == root.expanduser().resolve() else "not-this-checkout"
  )


def update_run_here(root: Path, *, enable: bool) -> None:
  """
  Point this host's `daemon.run_here` entry at the given checkout, or drop it.

  Guarantees:
    - Other hosts' entries are preserved; a gate that was not a mapping is replaced by one.

  Args:
    root: Checkout this host's entry names when `enable` is true.
    enable: Whether this host should run the daemon in `root`.

  Raises:
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """

  # Contract:
  # Other hosts' entries are preserved; a gate that was not a mapping is replaced by one.

  # the gate is normalized to lowercase host keys so this host's entry is found however it was spelled
  settings = root / SettingsFile.REL
  section = load_tracked_section(settings, SettingsKey.DAEMON)
  prior = section.get(DaemonKey.RUN_HERE)
  gate = _normalize_gate(prior) if isinstance(prior, dict) else {}

  # this host's entry is rewritten to name the checkout, or dropped when the daemon must not run here
  host = _read_short_host()
  if enable:
    gate[host] = str(root.expanduser().resolve())
  else:
    gate.pop(host, None)

  # the normalized gate replaces whatever shape was recorded
  section[DaemonKey.RUN_HERE] = gate
  save_section(settings, SettingsKey.DAEMON, section)


def cmd_daemon_run_here(argv: list[str]) -> int:
  """
  Run the `daemon-run-here` subcommand: `check` prints the gate outcome, `set` rewrites it.

  Args:
    argv: Argument vector after the subcommand name (`check`, or `set` with `--on` / `--off`,
      plus optional `--cwd`).

  Returns:
    Process exit code: 0 on success.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """
  # the verb's command line: the action word, the direction switch, and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core daemon-run-here")
  # waiver: argparse CLI signature — action names are this verb's own vocabulary
  parser.add_argument("action", choices = [ "check", "set" ])
  switch = parser.add_mutually_exclusive_group()
  # waiver: argparse CLI signature, not a domain key
  switch.add_argument("--on", dest = "on", action = "store_true", help = "Map this host to this checkout")
  # waiver: argparse CLI signature, not a domain key
  switch.add_argument("--off", dest = "off", action = "store_true", help = "Drop this host from the gate")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  root = resolve_repo_root(args.cwd)

  # `check` prints the verdict and never writes
  # waiver: action name is this verb's own vocabulary, matched against the argparse choices above
  if args.action == "check":
    print(evaluate_run_here(root))
    return 0

  # guard: a write must say which way it goes
  if not (args.on or args.off):
    # waiver: argparse-style usage error wording, not a domain key
    parser.error("set requires --on or --off")

  # rewrite the gate and echo the direction the install skill reads back
  update_run_here(root, enable = args.on)
  # waiver: CLI outcome token read by the install skill, not a reusable domain key
  print("on" if args.on else "off")
  return 0
