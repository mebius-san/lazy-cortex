from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import DaemonKey, SettingsFile, SettingsKey, SupervisorKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from install_cli import compute_repo_id, evaluate_run_here  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_install_phases import resolve_unit_interpreter  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from plugin_locator import query_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The shipped supervisor templates the unit is rendered from.
# waiver: shipped template location relative to this bin/ dir, fixed by the plugin layout
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "runtime"
# The launchd template file name.
_PLIST_TEMPLATE = "com.lazycortex.runtime.plist"
# The systemd template file name.
_SERVICE_TEMPLATE = "lazy-core-runtime.service"
# The launchd label of a checkout's unit, by repo id.
_LAUNCHD_LABEL = "com.lazycortex.runtime.{}"
# The systemd unit name of a checkout's unit, by repo id.
_SYSTEMD_UNIT = "lazy-core-runtime-{}.service"
# The shim file every unit runs; flags are injected right after it.
_SHIM_MARKER = "lazy.runtime.sh"
# The key that opens a systemd unit's start command.
_EXEC_START = "ExecStart="
# The key that sets one environment variable in a systemd unit.
_ENVIRONMENT = "Environment="
# The assignment the unit carries for the interpreter the shim runs the daemon with.
_PYTHON_ASSIGNMENT = "LAZYCORTEX_PYTHON="
# The indent of one `ProgramArguments` element in the launchd template.
_PLIST_ARG_INDENT = " " * 8
# The macOS platform name, whose supervisor is launchd.
_DARWIN = "darwin"
# The Linux platform name, whose supervisor is systemd.
_LINUX = "linux"
# The decode mode for a tool's captured output, so stray bytes never fail the verb.
# waiver: stdlib decode-error mode, not a domain constant
_DECODE_ERRORS = "replace"
# The shim flag that gives the daemon a login-equivalent environment.
_FLAG_LOGIN_SHELL = "--login-shell"
# The shim flag that sources one environment file.
_FLAG_ENV_FILE = "--env-file"
# The shim flag that prefers in-repo plugin sources over the cache.
_FLAG_DEV_MODE = "--dev-mode"
# The repo-relative directory whose plugin manifests mark a checkout that authors plugins.
_PLUGINS_DIR = Path("plugins") / "claude"
# The manifest a plugin directory carries.
# waiver: external Claude Code plugin manifest location, not a reusable domain key
_PLUGIN_MANIFEST = Path(".claude-plugin") / "plugin.json"



# ----------------------------------------------------------------------------------------
class _Cmd:
  """
  Supervisor tool names and their command words, as `launchctl` and `systemctl` spell them.

  Attributes:
    LAUNCHCTL: The launchd control tool.
    SYSTEMCTL: The systemd control tool.
    USER: The systemd switch selecting the user service manager.
    UNLOAD: The launchd word that stops and forgets a plist by path.
    PRINT: The launchd word that describes a loaded label.
    BOOTOUT: The launchd word that removes a label from a domain.
    BOOTSTRAP: The launchd word that loads a plist into a domain.
    DISABLE: The systemd word that stops enabling a unit at login.
    NOW: The systemd switch that also stops or starts the unit at once.
    IS_ACTIVE: The systemd word that reports whether a unit runs.
    DAEMON_RELOAD: The systemd word that rereads unit files.
    ENABLE: The systemd word that starts a unit at login.
    RESTART: The systemd word that restarts a unit.
  """

  # The launchd control tool.
  LAUNCHCTL = "launchctl"
  # The systemd control tool.
  SYSTEMCTL = "systemctl"
  # The systemd switch selecting the user service manager.
  USER = "--user"
  # The launchd word that stops and forgets a plist by path.
  UNLOAD = "unload"
  # The launchd word that describes a loaded label.
  PRINT = "print"
  # The launchd word that removes a label from a domain.
  BOOTOUT = "bootout"
  # The launchd word that loads a plist into a domain.
  BOOTSTRAP = "bootstrap"
  # The systemd word that stops enabling a unit at login.
  DISABLE = "disable"
  # The systemd switch that also stops or starts the unit at once.
  NOW = "--now"
  # The systemd word that reports whether a unit runs.
  IS_ACTIVE = "is-active"
  # The systemd word that rereads unit files.
  DAEMON_RELOAD = "daemon-reload"
  # The systemd word that starts a unit at login.
  ENABLE = "enable"
  # The systemd word that restarts a unit.
  RESTART = "restart"



# ----------------------------------------------------------------------------------------
class UnitState:
  """
  Outcome words of a supervisor-unit sync.

  Attributes:
    INSTALLED: No unit was on disk; it was written.
    REFRESHED: The unit on disk differed; it was rewritten.
    UNCHANGED: The unit on disk already carried the rendered bytes.
    REFUSED: The checkout is not the one the daemon may run in on this host; nothing was touched.
    FAILED: A write, a removal or a supervisor command did not succeed.
  """

  # No unit was on disk; it was written.
  INSTALLED = "installed"
  # The unit on disk differed; it was rewritten.
  REFRESHED = "refreshed"
  # The unit on disk already carried the rendered bytes.
  UNCHANGED = "unchanged"
  # The checkout is not the one the daemon may run in on this host; nothing was touched.
  REFUSED = "refused"
  # A write, a removal or a supervisor command did not succeed.
  FAILED = "failed"



# ----------------------------------------------------------------------------------------
class UnitSyncError(Exception):
  """
  A supervisor-unit sync stopped before it finished.

  Attributes:
    reason: One-line explanation of why the sync stopped.
    refused: Whether the sync was refused before anything was touched, rather than failing midway.
  """

  def __init__(self, reason: str, *, refused: bool = False) -> None:
    """
    Record why the sync stopped.

    Args:
      reason: One-line explanation printed in the verb's report.
      refused: Whether the sync was refused before touching anything, rather than failing midway.
    """
    # the message is the reason the report carries
    super().__init__(reason)

    # a refusal and a failure are reported under different states
    self.reason: str = reason
    self.refused: bool = refused



# ----------------------------------------------------------------------------------------
class SupervisorUnit:
  """
  The launchd or systemd unit that supervises one checkout's runtime daemon on this host.

  Responsibilities:
    - Decide whether this checkout may carry a unit on this host.
    - Keep the unit file current and make the supervisor run it.

  Notes:
    - Writes and removes files under the user's unit directory and runs the supervisor's command-line tool.
    - Reloading the supervisor restarts the supervised daemon.

  Attributes:
    root: Checkout the daemon runs in.
    platform: The host platform name, as `sys.platform` reports it.
    home: Home directory the unit directory lives under.
    repo_id: Identifier that keeps two same-named checkouts apart in unit names.
  """

  def __init__(self, root: Path, *, platform: str, home: Path) -> None:
    """
    Bind the unit to a checkout, a platform and a home directory.

    Args:
      root: Checkout the daemon runs in.
      platform: The host platform name, as `sys.platform` reports it.
      home: Home directory the unit directory lives under.
    """
    # the checkout and the host the unit belongs to
    self.root: Path = root
    self.platform: str = platform
    self.home: Path = home

    # the per-checkout id keeps two same-named checkouts apart
    self.repo_id: str = compute_repo_id(root)

  @property
  def is_launchd(self) -> bool:
    """
    Whether the unit is a launchd agent rather than a systemd user unit.
    """
    return self.platform == _DARWIN

  @property
  def unit_path(self) -> Path:
    """
    Location of this checkout's unit file on this host.
    """
    # waiver: external launchd / systemd user-unit directories, fixed by the supervisors
    if self.is_launchd:
      return self.home / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL.format(self.repo_id)}.plist"
    # waiver: external systemd user-unit directory, fixed by the supervisor
    return self.home / ".config" / "systemd" / "user" / _SYSTEMD_UNIT.format(self.repo_id)

  @property
  def legacy_path(self) -> Path:
    """
    Location of a unit named by the checkout's basename alone, as an older install wrote it.
    """
    # the legacy name drops the hash, so the basename alone identified the checkout
    if self.is_launchd:
      return self.unit_path.with_name(f"{_LAUNCHD_LABEL.format(self.root.name)}.plist")
    return self.unit_path.with_name(_SYSTEMD_UNIT.format(self.root.name))

  def require_gate(self) -> None:
    """
    Refuse a checkout the daemon may not run in on this host.

    Notes:
      - Reads the checkout's settings file; writes nothing.

    Raises:
      UnitSyncError: A refusal, when the platform has no supported supervisor, the settings cannot be read, the
        daemon is not enabled, or `daemon.run_here` does not name this host and exactly this checkout.
    """
    # guard: only launchd and systemd are templated
    if self.platform not in (_DARWIN, _LINUX):
      raise UnitSyncError(f"unsupported platform: {self.platform}", refused = True)

    # the gates are read from the settings; a file that cannot be read authorizes nothing
    try:
      enabled = load_section(self.root / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.ENABLED)
      gate = evaluate_run_here(self.root)
    # guard: settings that cannot be read authorize nothing, so the checkout is refused
    except (OSError, ValueError) as error:
      raise UnitSyncError(f"settings unreadable: {error}", refused = True) from error

    # guard: a daemon that is not enabled gets no unit
    if enabled is not True:
      raise UnitSyncError("daemon.enabled is not true", refused = True)

    # guard: only the checkout this host's entry names may carry the unit
    # waiver: gate outcome token of `evaluate_run_here`, not a reusable domain key
    if gate != "run-here":
      raise UnitSyncError(f"daemon.run_here does not name this host and this checkout ({gate})", refused = True)

  def read_options(self) -> tuple[bool, list[str], bool]:
    """
    Read the unit options: the operator's supervisor block and the derived dev mode.

    Notes:
      - Reads the checkout's settings file and lists its plugin directory; writes nothing.

    Returns:
      Whether a login shell is requested, the environment files in order, and whether the checkout authors
      plugins (dev mode).

    Raises:
      OSError: If the settings file or the plugin directory cannot be read.
      ValueError: If the settings file is not valid JSON.
    """
    # the operator's supervisor block; a missing or malformed value is off or empty
    block = load_section(self.root / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.SUPERVISOR)
    block = block if isinstance(block, dict) else {}
    env_files = block.get(SupervisorKey.ENV_FILES)
    env_files = [ str(entry) for entry in env_files ] if isinstance(env_files, list) else []

    # dev mode is derived, never read: a checkout that ships plugin manifests authors plugins
    plugins = self.root / _PLUGINS_DIR
    dev_mode = plugins.is_dir() and any(
      (plugins / name / _PLUGIN_MANIFEST).is_file() for name in os.listdir(plugins)
    )
    return block.get(SupervisorKey.LOGIN_SHELL) is True, env_files, dev_mode

  def render(self, *, login_shell: bool, env_files: list[str], dev_mode: bool) -> str:
    """
    Render the unit file from the shipped template for this checkout.

    Notes:
      - Reads the shipped template and the checkout's local settings; writes nothing.

    Args:
      login_shell: Whether the shim gets a login-equivalent environment.
      env_files: Environment files the shim sources, in order.
      dev_mode: Whether the shim prefers in-repo plugin sources.

    Returns:
      The unit file's text.

    Raises:
      OSError: If the shipped template cannot be read.
      ValueError: If the local settings that pin the interpreter are not valid JSON.
    """
    # the shim flags, in the order the shim reads them
    flags: list[str] = [ _FLAG_LOGIN_SHELL ] if login_shell else []
    for path in env_files:
      flags += [ _FLAG_ENV_FILE, path ]
    if dev_mode:
      flags.append(_FLAG_DEV_MODE)

    # the interpreter the unit exports is resolved once for either template
    interpreter = resolve_unit_interpreter(self.root)
    if self.is_launchd:
      return self._render_plist(flags, interpreter)
    return self._render_service(flags, interpreter)

  def _render_plist(self, flags: list[str], interpreter: str) -> str:
    """
    Render the launchd plist with the shim flags as their own argument elements.

    Args:
      flags: Shim flags in injection order.
      interpreter: Absolute interpreter the unit exports.

    Returns:
      The plist text.

    Raises:
      OSError: If the shipped template cannot be read.
    """
    # every substituted value is XML text, so it is escaped
    text = (_TEMPLATE_DIR / _PLIST_TEMPLATE).read_text(encoding = "utf-8")
    text = text.replace("{REPO_ROOT}", escape(str(self.root))).replace("{REPO_ID}", escape(self.repo_id))
    text = text.replace("{PYTHON}", escape(interpreter))

    # each flag becomes its own argument element right after the shim's
    lines = text.split("\n")
    after = next(index for index, line in enumerate(lines) if _SHIM_MARKER in line) + 1
    lines[after:after] = [ f"{_PLIST_ARG_INDENT}<string>{escape(flag)}</string>" for flag in flags ]
    return "\n".join(lines)

  def _render_service(self, flags: list[str], interpreter: str) -> str:
    """
    Render the systemd service with the shim flags on its start command.

    Args:
      flags: Shim flags in injection order.
      interpreter: Absolute interpreter the unit exports.

    Returns:
      The service text.

    Raises:
      OSError: If the shipped template cannot be read.
    """
    # the plain substitutions; the checkout path in the start command is handled word by word below
    text = (_TEMPLATE_DIR / _SERVICE_TEMPLATE).read_text(encoding = "utf-8")
    text = text.replace("{REPO_NAME}", self.root.name)

    # systemd splits an environment assignment on whitespace, so an interpreter path with a space is quoted whole
    python_line = f"{_ENVIRONMENT}{_PYTHON_ASSIGNMENT}{{PYTHON}}"
    if any(char.isspace() for char in interpreter):
      text = text.replace(python_line, f'{_ENVIRONMENT}"{_PYTHON_ASSIGNMENT}{interpreter}"')
    text = text.replace("{PYTHON}", interpreter)
    lines = text.split("\n")

    # systemd splits the start command on whitespace, so each word is substituted on its own, the flags follow
    # the shim's word, and a word holding a space is double-quoted
    for index, line in enumerate(lines):
      if line.startswith(_EXEC_START):
        words: list[str] = []
        for word in line[len(_EXEC_START):].split():
          words.append(word.replace("{REPO_ROOT}", str(self.root)))
          words += flags if _SHIM_MARKER in word else []
        lines[index] = _EXEC_START + " ".join(f'"{word}"' if " " in word else word for word in words)

    # every other line takes the checkout path verbatim: systemd reads the rest of such a line as one value
    return "\n".join(lines).replace("{REPO_ROOT}", str(self.root))

  def migrate_legacy(self) -> bool:
    """
    Remove this checkout's unit left under the basename-only name, unloading it first.

    Guarantees:
      - A unit of another checkout under the same basename, including a checkout nested inside this one, is never
        unloaded or deleted; ownership is an exact match of the unit's working directory, never a substring.

    Notes:
      - Runs the supervisor's tool to stop the legacy unit, then deletes its file.

    Returns:
      True when a legacy unit of this checkout was removed, False when none was there.

    Raises:
      UnitSyncError: A failure, when the legacy unit file cannot be read or removed, or the supervisor's tool is
        not installed.
    """

    # Contract:
    # A unit that belongs to another checkout with the same basename, including a checkout nested inside this one,
    # is never unloaded or deleted. Ownership is an exact match of the unit's working directory, never a substring.

    # guard: no legacy unit, or one that is the current unit itself
    if self.legacy_path == self.unit_path or not self.legacy_path.is_file():
      return False

    # a legacy unit is this checkout's only when its working directory is exactly this checkout, spelled as the
    # template renders it; a substring would also match a checkout nested inside this one
    working_directory = (
      f"<key>WorkingDirectory</key><string>{escape(str(self.root))}</string>" if self.is_launchd
      else f"WorkingDirectory={self.root}"
    )
    try:
      text = self.legacy_path.read_text(encoding = "utf-8", errors = _DECODE_ERRORS)
    # guard: a legacy unit that cannot be read cannot be judged, so the sync stops rather than guess
    except OSError as error:
      raise UnitSyncError(f"cannot read legacy unit {self.legacy_path}: {error}") from error

    # guard: a same-named unit of a different checkout is not this one's to remove
    if not any(line.strip() == working_directory for line in text.splitlines()):
      return False

    # the old unit is stopped before its file goes; a non-zero exit means it was not loaded
    if self.is_launchd:
      _run([ _Cmd.LAUNCHCTL, _Cmd.UNLOAD, str(self.legacy_path) ])
    else:
      _run([ _Cmd.SYSTEMCTL, _Cmd.USER, _Cmd.DISABLE, _Cmd.NOW, self.legacy_path.name ])

    # the file goes once the unit is stopped
    try:
      self.legacy_path.unlink()
    except OSError as error:
      raise UnitSyncError(f"cannot remove legacy unit {self.legacy_path}: {error}") from error
    return True

  def write(self, text: str) -> str:
    """
    Put the rendered unit on disk unless it already holds these bytes.

    Notes:
      - Creates the unit directory if needed and writes the unit file; an equal file is not rewritten.

    Args:
      text: The rendered unit file.

    Returns:
      The outcome word: installed, refreshed or unchanged.

    Raises:
      UnitSyncError: A failure, when the unit file cannot be read, written or verified.
    """
    # the unit on disk is compared byte for byte; an equal one is never rewritten
    try:
      existing = self.unit_path.read_bytes() if self.unit_path.exists() else None
    except OSError as error:
      raise UnitSyncError(f"cannot read unit {self.unit_path}: {error}") from error

    # a unit already carrying these bytes is left as it is
    if existing == text.encode("utf-8"):
      return UnitState.UNCHANGED

    # the write counts only once a second read proves the bytes landed
    try:
      self.unit_path.parent.mkdir(parents = True, exist_ok = True)
      runtime_state.atomic_write_text(self.unit_path, text)
      landed = self.unit_path.read_bytes() == text.encode("utf-8")
    except OSError as error:
      raise UnitSyncError(f"cannot write unit {self.unit_path}: {error}") from error

    # guard: a write that did not verify is a failure, never a sync
    if not landed:
      raise UnitSyncError(f"unit {self.unit_path} does not hold the rendered bytes after the write")
    return UnitState.REFRESHED if existing is not None else UnitState.INSTALLED

  def query_loaded(self) -> bool:
    """
    Report whether the supervisor currently has this checkout's unit loaded or active.

    Notes:
      - Runs the supervisor's query command; changes nothing.

    Returns:
      True when launchd knows the label, or systemd reports the unit active.

    Raises:
      UnitSyncError: A failure, when the supervisor's tool is not installed.
    """
    # launchd prints a loaded label and fails on an unknown one
    if self.is_launchd:
      label = f"gui/{os.getuid()}/{_LAUNCHD_LABEL.format(self.repo_id)}"
      return _run([ _Cmd.LAUNCHCTL, _Cmd.PRINT, label ]).returncode == 0
    return _run([ _Cmd.SYSTEMCTL, _Cmd.USER, _Cmd.IS_ACTIVE, self.unit_path.name ]).returncode == 0

  def reload(self) -> None:
    """
    Make the supervisor run the unit as it now stands on disk.

    Notes:
      - Runs supervisor commands that restart the supervised daemon.

    Raises:
      UnitSyncError: A failure, when a supervisor command the reload needs exits non-zero, or the supervisor's
        tool is not installed.
    """
    # launchd keeps an old plist in memory, so the label is booted out first; a non-zero exit means not loaded
    if self.is_launchd:
      domain = f"gui/{os.getuid()}"
      _run([ _Cmd.LAUNCHCTL, _Cmd.BOOTOUT, f"{domain}/{_LAUNCHD_LABEL.format(self.repo_id)}" ])
      _run_checked([ _Cmd.LAUNCHCTL, _Cmd.BOOTSTRAP, domain, str(self.unit_path) ])
      return

    # systemd rereads the unit, enables it at login, and restarts it on the new bytes
    _run_checked([ _Cmd.SYSTEMCTL, _Cmd.USER, _Cmd.DAEMON_RELOAD ])
    _run_checked([ _Cmd.SYSTEMCTL, _Cmd.USER, _Cmd.ENABLE, self.unit_path.name ])
    _run_checked([ _Cmd.SYSTEMCTL, _Cmd.USER, _Cmd.RESTART, self.unit_path.name ])

  def sync(self) -> dict[str, str | bool | list[str]]:
    """
    Bring this checkout's unit current on this host, reloading the supervisor only when that is needed.

    Guarantees:
      - A refused checkout is left untouched: nothing is written or reloaded, and the gate reads only its settings.
      - A unit already holding the rendered bytes is never rewritten, and a loaded one is never reloaded.
      - A tracked file of the checkout is never written.

    Notes:
      - Reads settings and the shipped template, writes or removes unit files, and runs supervisor commands.
      - A reload restarts the supervised daemon.

    Returns:
      The report mapping: the outcome word prefixed by the supervisor kind, the unit path, the repo id, the
      options the unit was rendered with, whether a legacy unit was removed, and whether the supervisor was
      reloaded.

    Raises:
      UnitSyncError: When the sync is refused, or a step of it fails.
    """

    # Contract:
    # A refused checkout is left untouched: nothing is written or reloaded, and the gate reads only its settings.

    # Contract:
    # A unit already holding the rendered bytes is never rewritten, and a loaded one is never reloaded.

    # Contract:
    # A tracked file of the checkout is never written.

    # Domain(install.reconciliation):
    # # A supervisor is restarted only when its unit changed or it is not running
    # A running daemon is the project's live worker, and restarting it interrupts whatever job it is driving. The
    # unit is therefore re-rendered on every run but compared with what is installed, and the supervisor is told
    # to reload only when the installed unit changed or nothing is running it. Only the checkout the project names
    # for this host may carry a unit at all.

    # the gate comes first: a refused checkout is never touched
    self.require_gate()

    # the options and the rendered unit, then the legacy unit of this checkout leaves before the new one lands
    try:
      login_shell, env_files, dev_mode = self.read_options()
      text = self.render(login_shell = login_shell, env_files = env_files, dev_mode = dev_mode)
    except (OSError, ValueError) as error:
      raise UnitSyncError(f"cannot render the unit: {error}") from error
    legacy = self.migrate_legacy()

    # the unit is written only when it differs, and the supervisor reloads only for a new unit or a stopped one
    state = self.write(text)
    reloaded = state != UnitState.UNCHANGED or not self.query_loaded()
    if reloaded:
      self.reload()

    # the report names the supervisor kind with the outcome
    # waiver: CLI report fields and supervisor-kind prefixes read by the calling skills, not reusable domain keys
    return {
      "state": f"{'launchd' if self.is_launchd else 'systemd'}-{state}", "unit": str(self.unit_path),
      "repo_id": self.repo_id, "login_shell": login_shell, "env_files": env_files, "dev_mode": dev_mode,
      "legacy_removed": legacy, "reloaded": reloaded,
    }


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
  """
  Run one supervisor command and capture its output.

  Notes:
    - Spawns a subprocess; a non-zero exit is not an error here.

  Args:
    args: The command line, its tool first.

  Returns:
    The finished process.

  Raises:
    UnitSyncError: A failure, when the tool is not installed on this host.
  """
  # guard: a host without the supervisor's tool cannot carry the unit
  if shutil.which(args[0]) is None:
    raise UnitSyncError(f"{args[0]} not found")
  return subprocess.run(args, capture_output = True, text = True, check = False, encoding = "utf-8",
                        errors = _DECODE_ERRORS)


def _run_checked(args: list[str]) -> None:
  """
  Run one supervisor command that must succeed.

  Notes:
    - Spawns a subprocess.

  Args:
    args: The command line, its tool first.

  Raises:
    UnitSyncError: A failure, when the command exits non-zero; the reason carries its output.
  """
  done = _run(args)

  # guard: a failed supervisor command is reported with what it printed, never swallowed
  if done.returncode != 0:
    raise UnitSyncError(f"{' '.join(args)} exited {done.returncode}: {(done.stderr or done.stdout).strip()}")


def cmd_daemon_unit(argv: list[str]) -> int:
  """
  Run the `daemon-unit` subcommand: `sync` brings the checkout's supervisor unit current and prints one JSON line.

  Guarantees:
    - A refusal or a failure exits 1 and prints one JSON line carrying `state` (`refused` or `failed`) and `reason`.

  Notes:
    - Prints one JSON line to standard output.
    - Performs the sync's file writes and supervisor commands in the resolved checkout.

  Args:
    argv: Argument vector after the subcommand name (`sync` and `--repo-root`).

  Returns:
    Process exit code: 0 when the unit is current, 1 when the sync was refused or failed.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """

  # Contract:
  # A refusal or a failure exits 1 and prints one JSON line carrying `state` (`refused` or `failed`) and `reason`.

  # the verb's command line: the action word and the checkout the unit belongs to
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core daemon-unit")
  # waiver: argparse CLI signature — action names are this verb's own vocabulary
  parser.add_argument("action", choices = [ "sync" ])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo-root", default = None, help = "Checkout the daemon runs in (default: cwd)")
  args = parser.parse_args(argv)

  # the unit belongs to the named checkout on this host
  unit = SupervisorUnit(query_repo_root(args.repo_root), platform = sys.platform, home = Path.home())

  # a refusal and a failure are both reported as one JSON line and a non-zero exit
  try:
    report = unit.sync()
  except UnitSyncError as error:
    # waiver: CLI report fields read by the calling skills, not reusable domain keys
    print(json.dumps({
      "state": UnitState.REFUSED if error.refused else UnitState.FAILED, "reason": error.reason,
      "unit": str(unit.unit_path), "repo_id": unit.repo_id,
    }))
    return 1

  # the report is the verb's whole output
  print(json.dumps(report))
  return 0
