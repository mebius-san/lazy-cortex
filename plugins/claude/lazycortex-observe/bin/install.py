"""
Mechanical helpers for the lazy-observe.install skill.

Provides template rendering, path resolution, token / answer persistence, agent
binary discovery, service load/unload helpers for both macOS launchd and Linux
systemd, and a best-effort smoke test against the lazycortex-core metrics
endpoint. Stdlib-only — the embedded template engine handles only the small
`{{ name }}` / `{% if/elif/endif %}` / `{% for %}` dialect used by the shipped
templates, and rejects anything else to fail loudly on Jinja2-style mistakes.
"""
from __future__ import annotations

from typing import Iterable, TypedDict

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
XDG_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local/state"))

ANSWER_FILE = XDG_CONFIG_HOME / "lazycortex" / "observe.toml"
TOKEN_FILE = XDG_CONFIG_HOME / "lazycortex" / "observe.token"
DATA_DIR = XDG_DATA_HOME / "lazycortex" / "observe"
LOG_DIR_MAC = Path.home() / "Library" / "Logs" / "lazycortex-observe"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboards"

# answer-file keys that carry credential material and are refused by the non-secret writer
_SECRET_ANSWER_KEYS = ("token", "LAZYCORTEX_OBSERVE_TOKEN")
# TOML boolean literals as they appear in the answer file, one per Python truth value
_TOML_TRUE = "true"
_TOML_FALSE = "false"
# owner-read-write-only mode the token file is tightened to
_TOKEN_FILE_MODE = 0o600
# suffix of the sibling temp file every atomic write goes through
_TMP_SUFFIX = ".tmp"
# metric-family name of the core runtime's own exposition
_RUNTIME_METRIC_FAMILY = "lazycortex_runtime"
# number of leading bytes of the metrics body the probe inspects for the runtime family
_METRICS_PROBE_READ_BYTES = 4096
# agent-kind tokens of the observe.toml contract, each mapped to its external binary names in priority order
_AGENT_BINARY_CANDIDATES = {
  "alloy":   [ "alloy", "grafana-alloy" ],
  "otelcol": [ "otelcol", "otelcol-contrib" ],
}

# sibling plugin CLI binary name — the § 1c boundary contract
_CORE_CLI_NAME = "lazycortex-core"
# subprocess wall-clock cap in seconds for the registry call
_CORE_CLI_TIMEOUT_SEC = 30
# number of leading stderr characters a failed core-CLI call carries into its error message
_STDERR_EXCERPT_LEN = 300
# external scraper process names probed by the coverage pre-flight
_SCRAPER_PROCESS_NAMES = ("prometheus", "otelcol", "alloy", "grafana-agent")

# external Grafana process-table markers
_GRAFANA_SERVER_MARKERS = ("grafana server", "grafana-server")
# external Grafana CLI flag naming the config file
_GRAFANA_CONFIG_FLAG = "--config="
# external Grafana CLI flag naming the homepath
_GRAFANA_HOMEPATH_FLAG = "--homepath="
# external grafana.ini section holding the path settings
_GRAFANA_PATHS_SECTION = "paths"
# external grafana.ini key naming the provisioning directory
_GRAFANA_PROVISIONING_KEY = "provisioning"
# Grafana's own documented default, relative to its homepath
_GRAFANA_DEFAULT_PROVISIONING = "conf/provisioning"
# external Grafana provisioning-tree layout name
_GRAFANA_DASHBOARDS_SUBDIR = "dashboards"
# packaged grafana.ini locations probed when no running server names its own config
_GRAFANA_CONFIG_CANDIDATES = (
  XDG_CONFIG_HOME / "grafana" / "grafana.ini",
  Path("/opt/homebrew/etc/grafana/grafana.ini"),
  Path("/usr/local/etc/grafana/grafana.ini"),
  Path("/etc/grafana/grafana.ini"),
)
# answer-file key of the operator's dashboards-directory override
_ANSWER_KEY_DASHBOARD_DIR = "grafana_dashboards_dir"
# subprocess wall-clock cap in seconds for the process-table read
_PS_TIMEOUT_SEC = 5
# file suffix of a shipped dashboard
_JSON_SUFFIX = ".json"

# launchd label of the shipper's user agent, fixed by the service-unit template contract
_LAUNCHD_LABEL = "com.lazycortex.observe"
# systemd user unit of the shipper, fixed by the service-unit template contract
_SYSTEMD_UNIT = "lazycortex-observe.service"
# launchd plist path of the shipper's user agent
_DEFAULT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
# default wall-clock cap in seconds for the post-load metrics wait
_WAIT_DEFAULT_SEC = 30
# poll interval in seconds between two metrics probes
_WAIT_POLL_SEC = 1
# answer-file key the agent-kind default is read from
_ANSWER_KEY_AGENT_KIND = "agent_kind"


def detect_host() -> str:
  """
  Return the canonical host identifier for the current platform.

  Returns:
    The string `darwin` on macOS or `linux` on Linux-based systems.

  Raises:
    ValueError: If the current platform is neither macOS nor Linux.
  """
  # macOS answers to its single platform token
  # waiver: OS/platform token (sys.platform), external
  if sys.platform == "darwin":
    # waiver: OS/platform token (sys.platform), external
    return "darwin"

  # every Linux variant shares one platform-token prefix
  # waiver: OS/platform token (sys.platform), external
  if sys.platform.startswith("linux"):
    # waiver: OS/platform token (sys.platform), external
    return "linux"

  # any other platform has no service manager this installer knows how to drive
  raise ValueError(f"unsupported platform: {sys.platform!r}")


def _write_atomic(target: Path, data: str | bytes) -> None:
  """
  Replace the target file's content in one atomic step through a sibling temp file.

  Guarantees:
    - An interrupted, killed, or crashed call always leaves either the previous complete file
      content or the new complete content at `target`, never a partial write.

  Args:
    target: Final path the content lands at; its parent directory must already exist.
    data: Content to write — text is written in the platform's text encoding, bytes verbatim.

  Raises:
    OSError: If the temp file cannot be written or moved into place.
  """

  # Contract:
  # An interrupted, killed, or crashed call always leaves either the previous complete file
  # content or the new complete content at `target`, never a partial write.

  # the sibling temp file is fully written before the single rename that publishes it
  tmp = target.with_name(target.name + _TMP_SUFFIX)
  if isinstance(data, bytes):
    tmp.write_bytes(data)
  else:
    tmp.write_text(data)
  os.replace(tmp, target)


# waiver: `vars` is the public substitution-dict param name; shadowing builtin vars() is harmless,
# not restructured for a checker
# pylint: disable-next=redefined-builtin
def render(template_name: str, vars: dict[str, object]) -> str:
  """
  Render a shipped template into a string using the embedded mini-dialect.

  The dialect covers `{{ key }}` and `{{ key | default('foo') }}` substitutions, `{% if cond %}` /
  `{% elif cond %}` / `{% else %}` / `{% endif %}` conditionals, and `{% for item in seq %}` /
  `{% endfor %}` loops; anything else fails loudly rather than pretending Jinja2 compatibility.

  Guarantees:
    - An unsupported template construct always raises instead of being silently skipped,
      partially substituted, or rendered as literal text.

  Args:
    template_name: File name of the template under the shipped `templates/`
      directory.
    vars: Mapping of template variable names to substituted values.

  Returns:
    The fully rendered template text.

  Raises:
    SyntaxError: If the template uses an unsupported directive or has an
      unclosed `{% if %}` / `{% for %}` block.
    TypeError: If a `{% for %}` directive iterates over a non-iterable value.
    FileNotFoundError: If the named template does not exist.
  """

  # Contract:
  # An unsupported template construct always raises rather than being silently skipped,
  # partially substituted, or rendered as literal text.

  # Domain(observe.install-state):
  # # Installer configuration renders through a narrow template dialect
  # The files an install step hands to the host's service manager, and the config a shipping agent
  # reads on startup, are produced from templates, but the substitution language is deliberately
  # smaller than a general templating engine: a fixed set of variable substitution, branching, and
  # simple loops, nothing else. A construct outside that small vocabulary is a rendering error, not a
  # silent no-op or a partial substitution, so a template mistake surfaces immediately during install
  # rather than shipping a config that looks plausible but is subtly wrong.

  # read the raw template text and hand it to the mini template engine for substitution
  return _Template((TEMPLATE_DIR / template_name).read_text(), vars).render()


# waiver: `vars` is the public substitution-dict param name; shadowing builtin vars() is harmless,
# not restructured for a checker
# pylint: disable-next=redefined-builtin
def render_to(template_name: str, vars: dict[str, object], target: Path) -> Path:
  """
  Render a template and write the result atomically to the given target path.

  Guarantees:
    - The write is atomic — an interrupted, killed, or crashed call always leaves either the
      previous complete file content or the new complete content at `target`, never a partial
      write.

  Args:
    template_name: File name of the template under the shipped `templates/`
      directory.
    vars: Mapping of template variable names to substituted values.
    target: Destination path that will receive the rendered text. Parent
      directories are created as needed.

  Returns:
    The same `target` path passed in, for chaining convenience.

  Raises:
    SyntaxError: If the template uses an unsupported directive or has an
      unclosed block.
    TypeError: If a `{% for %}` directive iterates over a non-iterable value.
    OSError: If the target file or its parent directory cannot be written.
  """

  # Contract:
  # The write is atomic; an interrupted, killed, or crashed call never leaves a partially
  # written file at `target` — it always keeps either the previous complete content or gains
  # the new complete content.

  # render before the parent directory exists so a template error creates nothing on disk
  # waiver: `body` is read once but must be produced ahead of the mkdir for that ordering
  body = render(template_name, vars)
  target.parent.mkdir(parents = True, exist_ok = True)

  # Domain(observe.install-state):
  # # Config files are replaced atomically, never edited in place
  # Every generated configuration file installed onto the host is written to a temporary sibling path
  # first and only moved into its final place in one atomic step. An install run that is interrupted
  # midway, killed, crashed, or out of disk, always leaves either the complete previous file or the
  # complete new one at the final path; a half-written file is never observable by whatever process
  # reads that config next.

  # write through a sibling temp file so an interrupted call leaves the previous file intact
  _write_atomic(target, body)
  return target


def write_token_file(token: str) -> Path:
  """
  Persist the bearer or basic-auth token to a 0600-mode file.

  The caller is responsible for asking the operator before invoking, since the
  written file contains sensitive credential material.

  Guarantees:
    - The token file's permission mode is owner-read-write-only (0600) before the first byte of the
      token lands in it, regardless of the process umask and of the file's or its parent
      directory's prior permission state.

  Args:
    token: Token string to persist. A trailing newline is appended on write.

  Returns:
    The path to the token file that was written.

  Raises:
    OSError: If the token file or its parent directory cannot be written or
      its permissions cannot be tightened.
  """

  # Contract:
  # The token file's permission mode is owner-read-write-only (0600) before the first byte of the
  # token lands in it, regardless of the process umask and of the file's or its parent directory's
  # prior permission state.

  # Domain(observe.install-state):
  # # Secret material is split from ordinary installer answers
  # Persistent state gathered during installation is split by sensitivity. Everyday configuration
  # answers picked during the install wizard, such as the collection URL, the auth kind, or the
  # shipping agent, are written to a plain, world-readable settings file. Anything that authenticates
  # the shipper to its collection endpoint is never mixed into that file; it is written to its own
  # file instead, and that file's permissions are tightened to owner-read-write-only so other local
  # users on the same host cannot read the credential off disk.

  # create the file already restricted (the open mode only applies on creation, under the umask), then
  # tighten the open descriptor so a pre-existing loose file is closed down before the token is written
  TOKEN_FILE.parent.mkdir(parents = True, exist_ok = True)
  token_fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _TOKEN_FILE_MODE)
  # waiver: stdlib encoding/mode/escape idiom
  with os.fdopen(token_fd, "w") as handle:
    os.fchmod(token_fd, _TOKEN_FILE_MODE)
    handle.write(token + "\n")
  return TOKEN_FILE


def write_answer_file(answers: dict[str, object]) -> Path:
  """
  Persist non-secret operator answers to a trivial top-level TOML file.

  Only top-level `key = "value"` pairs are emitted. Booleans render as `true`
  / `false`, numerics as their literal form, and everything else as quoted
  strings with backslashes and double quotes escaped. Token-like keys are
  refused so that secret material never accidentally leaks into the file.

  Guarantees:
    - A token-like key is refused before the answer file is written; the file is never left
      with partial content or with a secret-looking key present.

  Args:
    answers: Mapping of answer keys to scalar values (URL, agent kind, auth
      kind, etc.).

  Returns:
    The path to the answer file that was written.

  Raises:
    ValueError: If `answers` contains a token-like key such as `token` or
      `LAZYCORTEX_OBSERVE_TOKEN`.
    OSError: If the answer file or its parent directory cannot be written.
  """

  # Contract:
  # A token-like key is refused before the answer file is written; the file is never left
  # with partial content or with a secret-looking key present.

  # the rendered TOML lines are collected before anything touches the answer file
  ANSWER_FILE.parent.mkdir(parents = True, exist_ok = True)
  lines = []

  # Domain(observe.install-state):
  # # Secret-looking answer keys are refused, not filtered
  # The plain settings file only ever accepts answers whose keys are known in advance to be
  # non-secret. Before any answer is written, its key is checked against the closed set of names
  # known to carry credential material; a match aborts the whole write rather than silently dropping
  # just that one key, so a caller cannot accidentally leak a token into world-readable configuration
  # by extending the answer set with a badly-named field.

  # render each answer as a TOML literal line, refusing anything that looks like a secret first
  for key, value in sorted(answers.items()):
    # guard: never persist secret keys via the non-secret answer file
    if key in _SECRET_ANSWER_KEYS:
      raise ValueError(f"refused to write secret key {key!r} into the answer file")

    # boolean values render as lowercase TOML literals
    if isinstance(value, bool):
      lines.append(f"{key} = {_TOML_TRUE if value else _TOML_FALSE}")
    # numerics render as their literal form
    elif isinstance(value, (int, float)):
      lines.append(f"{key} = {value}")
    # everything else is treated as a quoted string with escaping
    else:
      # waiver: the escape chain stays out of the f-string, which would have to nest the quote it escapes
      escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
      lines.append(f'{key} = "{escaped}"')

  # every key passed the secret check, so the whole file is written in one go
  ANSWER_FILE.write_text("\n".join(lines) + "\n")
  return ANSWER_FILE


def read_answer_file() -> dict[str, object]:
  """
  Read the previously saved non-secret answer file back into a mapping.

  Lines are parsed permissively: blank lines and `#`-prefixed comments are
  skipped, malformed lines are silently ignored, and unquoted values are
  decoded as booleans, ints, floats, or strings in that order.

  Guarantees:
    - Malformed or unparseable lines never raise; the call always returns a best-effort
      mapping, empty when no answer file is present.

  Returns:
    A mapping of answer keys to decoded values, or an empty mapping when no
    answer file is present yet.

  Raises:
    OSError: If an answer file exists but cannot be read.
  """

  # Contract:
  # Malformed or unparseable lines in the answer file are tolerated, never raised; the call
  # always returns a best-effort mapping (empty when no file is present) instead of aborting.

  # guard: no previous answers persisted yet
  if not ANSWER_FILE.exists():
    return {}

  # decode the file line by line into the answer mapping
  out: dict[str, object] = {}
  pat = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$')
  for raw in ANSWER_FILE.read_text().splitlines():
    line = raw.strip()

    # guard: skip blank lines and comments
    if not line or line.startswith("#"):
      continue

    # guard: skip malformed entries silently
    if not (match := pat.match(line)):
      continue

    # the raw value text is decoded by shape: boolean, quoted string, then number
    key, value = match.group(1), match.group(2).strip()

    # decode booleans first to avoid them being eaten by the numeric branch
    if value.lower() in (_TOML_TRUE, _TOML_FALSE):
      out[key] = value.lower() == _TOML_TRUE
    # quoted string with escape sequences
    elif value.startswith('"') and value.endswith('"'):
      out[key] = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    # otherwise attempt int / float, falling back to a raw string
    else:
      try:
        out[key] = int(value) if "." not in value else float(value)
      except ValueError:
        out[key] = value

  # the best-effort mapping, empty when every line was skipped
  return out


def find_agent_binary(agent_kind: str) -> Path | None:
  """
  Locate the binary for a shipping agent kind on the current `PATH`.

  Guarantees:
    - Candidate binary names for a kind are tried in a fixed priority order; the first name
      found on `PATH` wins over any later candidate, regardless of `PATH` ordering.

  Args:
    agent_kind: Logical agent identifier — supported values today are `alloy`
      and `otelcol`.

  Returns:
    The resolved binary path, or `None` if no matching executable is on
    `PATH` for the given kind (including unknown kinds).
  """

  # Contract:
  # Candidate binary names for a kind are tried in a fixed priority order; the first name
  # found on `PATH` wins over any later candidate, regardless of `PATH` ordering.

  # candidate binary names per kind, in priority order; an unknown kind has none
  for name in _AGENT_BINARY_CANDIDATES.get(agent_kind, []):
    # the first candidate name that resolves on PATH is the answer
    if path := shutil.which(name):
      return Path(path)

  # no candidate name resolved
  return None


def load_service_macos(plist_path: Path) -> tuple[bool, str]:
  """
  Bootstrap the launchd agent for the current GUI user.

  Guarantees:
    - When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
      performs no interpretation of what a non-zero exit means.
    - When the tool is absent from this host, nothing is spawned and the call returns `ok` as
      `False` with `stderr` naming the missing tool; it never raises for that case.

  Args:
    plist_path: Path to the launchd plist that defines the user agent.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `launchctl bootstrap` and `stderr` carries the captured error output for
    diagnostic surfacing.
  """

  # Contract:
  # When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
  # performs no interpretation of what a non-zero exit means, leaving that judgment entirely to
  # the caller. When the tool is absent from this host, nothing is spawned and the call returns
  # `ok` as False with `stderr` naming the missing tool; it never raises for that case.

  # guard: no launchctl on this host — nothing can bootstrap the agent
  try:
    proc = subprocess.run(
      [ "launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path) ],
      capture_output = True, text = True, check = False,
    )
  except OSError:
    # waiver: one-off human-facing message
    return (False, "launchctl not found")

  # the exit status is mirrored literally; the caller judges what non-zero means
  return (proc.returncode == 0, proc.stderr)


def unload_service_macos(plist_path: Path) -> tuple[bool, str]:
  """
  Boot the launchd agent out of the current GUI user's domain.

  Note that `launchctl bootout` exits non-zero when the agent is not currently
  loaded; the caller decides whether that constitutes failure.

  Guarantees:
    - When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
      performs no interpretation of what a non-zero exit means.
    - When the tool is absent from this host, nothing is spawned and the call returns `ok` as
      `False` with `stderr` naming the missing tool; it never raises for that case.

  Args:
    plist_path: Path to the launchd plist that defines the user agent.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `launchctl bootout` and `stderr` carries the captured error output for
    diagnostic surfacing.
  """

  # Contract:
  # When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
  # performs no interpretation of what a non-zero exit means, leaving that judgment entirely to
  # the caller. When the tool is absent from this host, nothing is spawned and the call returns
  # `ok` as False with `stderr` naming the missing tool; it never raises for that case.

  # Domain(observe.install-state):
  # # Stopping an already-stopped service is not evidence of failure
  # Both host service managers this shipper works with exit non-zero when asked to disable or unload
  # a service that isn't currently loaded, the very same result a genuine failure would produce. An
  # uninstall or reinstall flow that clears a service which may or may not be present must not treat
  # that non-zero result as an error by itself; it only means there was nothing to stop, and that is
  # expected on a machine where the shipper was never actually running.

  # guard: no launchctl on this host — nothing can hold the agent
  try:
    proc = subprocess.run(
      [ "launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path) ],
      capture_output = True, text = True, check = False,
    )
  except OSError:
    # waiver: one-off human-facing message
    return (False, "launchctl not found")

  # bootout exits non-zero if not loaded — caller decides whether to care.
  return (proc.returncode == 0, proc.stderr)


def load_service_linux(*, unit_name: str = _SYSTEMD_UNIT) -> tuple[bool, str]:
  """
  Enable and start the systemd user unit for the lazycortex-observe agent.

  Guarantees:
    - When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
      performs no interpretation of what a non-zero exit means.
    - When the tool is absent from this host, nothing is spawned and the call returns `ok` as
      `False` with `stderr` naming the missing tool; it never raises for that case.

  Args:
    unit_name: Name of the systemd user unit. Defaults to the canonical
      `lazycortex-observe.service`.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `systemctl --user enable --now` and `stderr` carries the captured error
    output for diagnostic surfacing.
  """

  # Contract:
  # When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
  # performs no interpretation of what a non-zero exit means, leaving that judgment entirely to
  # the caller. When the tool is absent from this host, nothing is spawned and the call returns
  # `ok` as False with `stderr` naming the missing tool; it never raises for that case.

  # guard: no systemctl on this host — nothing can enable the unit
  try:
    proc = subprocess.run(
      [ "systemctl", "--user", "enable", "--now", unit_name ],
      capture_output = True, text = True, check = False,
    )
  except OSError:
    # waiver: one-off human-facing message
    return (False, "systemctl not found")

  # the exit status is mirrored literally; the caller judges what non-zero means
  return (proc.returncode == 0, proc.stderr)


def unload_service_linux(unit_name: str = _SYSTEMD_UNIT) -> tuple[bool, str]:
  """
  Disable and stop the systemd user unit for the lazycortex-observe agent.

  Guarantees:
    - When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
      performs no interpretation of what a non-zero exit means.
    - When the tool is absent from this host, nothing is spawned and the call returns `ok` as
      `False` with `stderr` naming the missing tool; it never raises for that case.

  Args:
    unit_name: Name of the systemd user unit. Defaults to the canonical
      `lazycortex-observe.service`.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `systemctl --user disable --now` and `stderr` carries the captured error
    output for diagnostic surfacing.
  """

  # Contract:
  # When the service-manager tool runs, `ok` is a literal mirror of its exit status; the call
  # performs no interpretation of what a non-zero exit means, leaving that judgment entirely to
  # the caller. When the tool is absent from this host, nothing is spawned and the call returns
  # `ok` as False with `stderr` naming the missing tool; it never raises for that case.

  # guard: no systemctl on this host — nothing can hold the unit
  try:
    proc = subprocess.run(
      [ "systemctl", "--user", "disable", "--now", unit_name ],
      capture_output = True, text = True, check = False,
    )
  except OSError:
    # waiver: one-off human-facing message
    return (False, "systemctl not found")

  # the exit status is mirrored literally; the caller judges what non-zero means
  return (proc.returncode == 0, proc.stderr)


def check_local_metrics(scrape_target: str, *, timeout: float = 5.0) -> bool:
  """
  Best-effort probe of the lazycortex-core `/metrics` endpoint on the given target.

  Guarantees:
    - Network failures against the target — connection errors, timeouts, and unreachable
      hosts — never raise; the call always returns `False` for them instead.

  Args:
    scrape_target: Host-and-port string to probe, used directly in the
      constructed URL (e.g. `127.0.0.1:9464`).
    timeout: Maximum number of seconds to wait for the HTTP response.

  Returns:
    `True` when the endpoint responds and the body contains the
    `lazycortex_runtime` marker, otherwise `False` (including connection
    errors, timeouts, and unreachable hosts).
  """

  # Contract:
  # Network failures against the target — connection errors, timeouts, and unreachable hosts —
  # never raise; the call always returns False for them instead of propagating the exception.

  # probe the endpoint and look for the runtime's own metric family in the first chunk of the body
  try:
    with urllib.request.urlopen(f"http://{scrape_target}/metrics", timeout = timeout) as response:
      # waiver: stdlib encoding/mode/escape idiom
      body = response.read(_METRICS_PROBE_READ_BYTES).decode("utf-8", "ignore")
      return _RUNTIME_METRIC_FAMILY in body
  except (urllib.error.URLError, TimeoutError, ConnectionError):
    return False


# ----------------------------------------------------------------------------------------
# multi-daemon support: the core-CLI boundary and the coverage pre-flight
def _compute_version_key(name: str) -> tuple[int, ...]:
  """
  Compute a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(char for char in part if char.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _find_cached_sibling_root(name: str) -> Path | None:
  """
  Locate a sibling plugin's newest cached install next to this plugin's own cached install.

  Args:
    name: Sibling plugin name, which is also its cache directory and CLI name.

  Returns:
    The sibling's highest cached version directory, or None outside a cached install or when no
    version of the sibling is cached.
  """
  own = Path(__file__).resolve()

  # guard: not a cached install — a dev checkout has no version directory above bin/
  if not own.parents[1].name.replace(".", "").isdigit():
    return None

  # guard: a tree too shallow for cache/<registry>/<plugin>/<version>/bin above bin/ is not a plugin cache
  try:
    cache = own.parents[4]
  except IndexError:
    return None

  # every cached version directory of the sibling, across every registry in the cache
  versions = [
    version
    for registry in cache.iterdir() if (registry / name).is_dir()
    for version in (registry / name).iterdir()
    if version.is_dir() and version.name.replace(".", "").isdigit()
  ]

  # the newest cached version wins; nothing cached means no sibling to reach
  return max(versions, key = lambda entry: _compute_version_key(entry.name)) if versions else None


def resolve_core_cli() -> Path:
  """
  Locate the `lazycortex-core` CLI binary this installer drives across the plugin boundary.

  Every registry read and scrape-file write goes through the path returned here; the caller never
  needs to know which discovery location produced it.

  Guarantees:
    - The discovery order is fixed — every `$LAZYCORTEX_PLUGIN_DIRS` entry, then the dev-vault
      sibling layout, then the plugin cache — and the first location that carries the binary
      always wins, independent of unrelated environment state.

  Returns:
    Absolute path to the CLI binary.

  Raises:
    RuntimeError: If the binary is not found anywhere.
  """

  # Contract:
  # The discovery order is fixed — every `$LAZYCORTEX_PLUGIN_DIRS` entry, then the dev-vault
  # sibling layout, then the plugin cache — and the first location that carries the binary
  # always wins, independent of unrelated environment state.

  # Domain(plugin.boundaries):
  # # A shipper reaches its sibling plugin only through its published command line
  # This installer never imports another plugin's code directly; wherever it needs functionality that
  # another plugin owns, such as reading the host's daemon registry, it locates and runs that plugin's
  # own published command-line program instead and reads back its answer. The search for that program
  # follows a fixed order of decreasing certainty: first every directory a runtime-launched process is
  # explicitly told the enabled plugins live in, then the layout of a development checkout where every
  # plugin's sources sit side by side, and as a last resort the store of installed plugins this plugin
  # itself was installed into, where the sibling's newest installed version is taken. The general
  # command search path is never consulted: the program is a plain script file, not an installed
  # executable. Nothing found by any of the three means the run cannot reach its sibling at all, and
  # that failure is reported rather than papered over with a guess.

  # walk the discovery order and return the first location that actually carries the binary
  # waiver: external env-var name of the plugin-dirs boundary contract
  env_dirs = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep)
  for entry in env_dirs:
    # guard: empty path-list entries are skipped
    if not entry:
      continue

    # the binary's expected location inside this plugin-dir entry
    # waiver: plugin-tree layout directory name, not an internal key
    candidate = Path(entry) / "bin" / _CORE_CLI_NAME

    # the first plugin-dir entry that carries the binary is the answer
    if candidate.is_file():
      return candidate

  # the dev-vault sibling checkout is the second source
  # waiver: plugin-tree layout directory name, not an internal key
  if (sibling := Path(__file__).resolve().parents[2] / _CORE_CLI_NAME / "bin" / _CORE_CLI_NAME).is_file():
    return sibling

  # the cached sibling is the last source — the consumer-install fallback with no daemon export
  cached_root = _find_cached_sibling_root(_CORE_CLI_NAME)
  # waiver: plugin-tree layout directory name, not an internal key
  if cached_root is not None and (cached := cached_root / "bin" / _CORE_CLI_NAME).is_file():
    return cached

  # nothing found by any of the three means the sibling is unreachable from here; name every stage searched
  searched = [ entry for entry in env_dirs if entry ] or [ "<unset>" ]
  raise RuntimeError(
    f"lazycortex-core CLI not found: no bin/{_CORE_CLI_NAME} under any directory named by "
    f"$LAZYCORTEX_PLUGIN_DIRS (searched: {', '.join(searched)}), no dev-vault sibling at '{sibling}', "
    f"and no cached sibling{f' under {cached_root}' if cached_root is not None else ''}"
  )


def read_local_scrape_targets() -> list[dict[str, object]]:
  """
  Read the host's metrics-enabled daemons from the core registry as scrape-target rows.

  Guarantees:
    - Only rows whose `metrics_enabled` field is true are returned; every other daemon row the
      core CLI reports is filtered out.

  Notes:
    - Runs the sibling core CLI's `daemon-list` as a subprocess; the daemon registry and its
      settings semantics stay owned by lazycortex-core.

  Returns:
    The `daemons` rows from the core CLI with `metrics_enabled` true; each carries
    `repo_id`, `repo_root`, `repo_label`, `bind`, and `port`.

  Raises:
    RuntimeError: If the CLI cannot be found, exits non-zero, or prints unparseable JSON.
    subprocess.TimeoutExpired: If the CLI does not exit within the wall-clock cap.
  """

  # Contract:
  # Only rows whose `metrics_enabled` field is true are returned; every other daemon row the
  # core CLI reports is filtered out before the result reaches the caller.

  # ask the core registry for every daemon it knows about
  # waiver: external core-CLI subcommand and flag, not internal keys
  proc = subprocess.run(
    [ sys.executable, str(resolve_core_cli()), "daemon-list", "--json" ],
    capture_output = True, text = True, check = False, timeout = _CORE_CLI_TIMEOUT_SEC,
  )

  # guard: a failing registry call must abort loudly, not render an empty shipper config
  if proc.returncode != 0:
    raise RuntimeError(f"lazycortex-core daemon-list failed: {proc.stderr.strip()[:_STDERR_EXCERPT_LEN]}")

  # guard: unparseable registry output aborts just as loudly
  try:
    # waiver: external JSON contract field name of the core daemon-list CLI
    rows = json.loads(proc.stdout).get("daemons", [])
  except json.JSONDecodeError as error:
    raise RuntimeError(f"lazycortex-core daemon-list printed unparseable JSON: {error}") from error

  # Domain(observe.coverage-detection):
  # # Scrape targets are drawn only from daemons that opted into metrics
  # A project's daemon can run perfectly well without ever turning on its metrics endpoint, so the
  # registry this installer reads may list daemons that publish nothing to scrape. The set of scrape
  # targets handed to a same-host collector only ever includes a daemon that has declared its metrics
  # endpoint enabled; every other daemon in the registry is left out, so a collector is never pointed
  # at a port that never intended to serve metrics.

  # keep only the daemons that declared their metrics endpoint enabled
  # waiver: external JSON contract field name of the core daemon-list CLI
  return [ row for row in rows if row.get("metrics_enabled") ]


def format_scrape_address(row: dict[str, object]) -> str:
  """
  Format the `host:port` address a same-host collector scrapes one daemon row at.

  Guarantees:
    - A wildcard bind address (`0.0.0.0` or `::`) always yields the loopback address; any other
      bind address is used unchanged.

  Args:
    row: One `read_local_scrape_targets()` row carrying `bind` and `port`.

  Returns:
    The `host:port` string for the row.
  """

  # Contract:
  # A wildcard bind address (`0.0.0.0` or `::`) always yields the loopback address; any other
  # bind address is used unchanged.

  # Domain(observe.coverage-detection):
  # # A wildcard bind address is scraped over loopback
  # A metrics endpoint that a daemon binds to a wildcard address is reachable on every network
  # interface of the host, including the loopback interface, so a scrape target built for a
  # same-host collector always substitutes the loopback address for a wildcard bind rather than
  # reusing the wildcard literal, which a collector cannot connect to directly. A daemon bound to a
  # specific, non-wildcard address keeps that address unchanged, since it is already the one address
  # a same-host collector can reach.

  # a wildcard bind is scraped over loopback; anything else is scraped at its bind address
  # waiver: inline network literals, not domain constants
  bind = row.get("bind", "127.0.0.1")
  # waiver: inline network literals and the external daemon-list field name, not internal keys
  return f"{'127.0.0.1' if bind in ('0.0.0.0', '::') else bind}:{row['port']}"


def render_scrape_targets_block(targets: list[dict[str, object]], agent_kind: str) -> str:
  """
  Pre-render the multi-target lines injected into a shipper template's scrape section.

  The daemon's exposition already labels every series with `repo`, so the block carries
  addresses only — one line per daemon, indented for its template's surrounding context.

  Args:
    targets: Rows from `read_local_scrape_targets()`.
    agent_kind: `alloy` or `otelcol` — selects the target-line syntax and indentation.

  Returns:
    The newline-joined target lines (no trailing newline).
  """
  lines = []

  # render one scrape-target line per covered daemon
  for row in targets:
    endpoint = format_scrape_address(row)
    # waiver: agent-kind token of the observe.toml contract
    if agent_kind == "alloy":
      lines.append(f'    {{ __address__ = "{endpoint}" }},')
    else:
      lines.append(f'                - "{endpoint}"')
  return "\n".join(lines)


def detect_existing_coverage(*, targets: list[dict[str, object]] | None = None) -> dict[str, object]:
  """
  Read-only pre-flight: is something on this host already collecting the daemons' metrics?

  The verdict lists every signal it rests on, so the operator can weigh a conservative
  `already-covered` call against what was actually found.

  Guarantees:
    - `covered` is true if and only if at least one strong signal is present, or at least two
      independent weak process signals are present; a single weak signal alone never marks the
      host as covered.

  Notes:
    - Reads the host's service manager, process table, and established TCP connections; nothing
      on the host is modified.

  Args:
    targets: Optional pre-computed `read_local_scrape_targets()` rows; computed when omitted.

  Returns:
    `{"covered": bool, "verdict": "already-covered"|"clear", "signals": [<str>, ...]}` —
    every detected signal is listed so the operator sees exactly what was found.

  Raises:
    ValueError: If the current platform is neither macOS nor Linux.
    subprocess.TimeoutExpired: If the core CLI, consulted when `targets` is omitted, does not exit
      within the wall-clock cap.
  """

  # Contract:
  # `covered` is true if and only if at least one strong signal is present, or at least two
  # independent weak process signals are present; a single weak signal alone never marks the
  # host as covered.

  # every detected signal by name, plus the count of strong ones the verdict hinges on
  signals: list[str] = []
  strong = 0

  # signal class 1: our own service unit already installed — probed through the host's service manager
  # waiver: host token of the detect_host() contract plus external launchctl / systemctl invocations
  unit_probe_argv = (
    [ "launchctl", "print", f"gui/{os.getuid()}/{_LAUNCHD_LABEL}" ] if detect_host() == "darwin"
    else [ "systemctl", "--user", "is-active", _SYSTEMD_UNIT ]
  )

  # a host without its service manager has no supervisor that could hold the unit
  try:
    unit_present = subprocess.run(unit_probe_argv, capture_output = True, text = True, check = False).returncode == 0
  except OSError:
    unit_present = False

  # an installed unit is a strong signal
  if unit_present:
    # waiver: human-facing signal token
    signals.append("observe-service-unit-installed")
    strong += 1

  # signal class 2: scraper-shaped processes running on this host
  process_hits = 0
  for name in _SCRAPER_PROCESS_NAMES:
    # guard: no pgrep on this host — no process evidence to weigh
    # waiver: external pgrep invocation, not internal keys
    try:
      probe = subprocess.run([ "pgrep", "-f", name ], capture_output = True, text = True, check = False)
    except OSError:
      continue

    # a matching process is a weak signal; two independent ones together count as coverage
    if probe.returncode == 0:
      # waiver: human-facing signal token
      signals.append(f"scraper-process-running:{name}")
      process_hits += 1

  # signal class 3: something holds live connections to a daemon's metrics port
  if targets is None:
    try:
      targets = read_local_scrape_targets()
    except RuntimeError:
      # the pre-flight stays read-only and best-effort — no registry, no port probes
      targets = []
  for row in targets:
    # waiver: external JSON contract field name of the core daemon-list CLI
    port = row["port"]

    # guard: no lsof on this host — the established-connection signal is dropped
    # waiver: external lsof invocation, not internal keys
    try:
      probe = subprocess.run(
        [ "lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED" ],
        capture_output = True, text = True, check = False,
      )
    except OSError:
      continue

    # a live connection into the metrics port is a strong signal
    if probe.returncode == 0 and probe.stdout.strip():
      # waiver: human-facing signal token
      signals.append(f"active-scrape-connection:{port}")
      strong += 1

  # Domain(observe.coverage-detection):
  # # Coverage verdict weighs signal strength, not signal count alone
  # Before installing a metrics shipper on a host, a pre-flight check decides whether something is
  # already collecting this host's metrics. Evidence splits into strong signals, such as an installed
  # collector service already running for this project or a live network connection into a metrics
  # port, and weak signals, such as a process that merely looks like a known scraper by name and could
  # just as easily be serving something unrelated. The host counts as already covered when even one
  # strong signal is present, or when at least two independent weak signals show up together; a single
  # weak signal alone is never enough to call the host covered, since it could be a false positive.

  # verdict: any strong signal, or two independent process signals, means covered
  covered = strong > 0 or process_hits >= 2
  # waiver: verdict tokens of the Step 0 contract
  return { "covered": covered, "verdict": "already-covered" if covered else "clear", "signals": signals }


def write_scrape_file_via_core(*, out: Path | None = None) -> dict[str, object]:
  """
  Regenerate the host's Prometheus file_sd scrape-targets file through the core CLI.

  Args:
    out: Optional output-path override forwarded to the CLI.

  Returns:
    The CLI's parsed JSON result (`path`, `count`, `targets`).

  Raises:
    RuntimeError: If the CLI cannot be found, exits non-zero, or prints unparseable JSON.
    subprocess.TimeoutExpired: If the CLI does not exit within the wall-clock cap.
  """
  # hand the write to the core CLI, forwarding the output override when one was given
  # waiver: external core-CLI subcommand and flag, not internal keys
  argv = [ sys.executable, str(resolve_core_cli()), "metrics-scrape-file" ] + ([ "--out", str(out) ] if out else [])
  proc = subprocess.run(argv, capture_output = True, text = True, check = False, timeout = _CORE_CLI_TIMEOUT_SEC)

  # guard: a failing scrape-file write must surface, not pass silently
  if proc.returncode != 0:
    raise RuntimeError(f"lazycortex-core metrics-scrape-file failed: {proc.stderr.strip()[:_STDERR_EXCERPT_LEN]}")

  # guard: an unparseable CLI result surfaces just as loudly
  try:
    return json.loads(proc.stdout)
  except json.JSONDecodeError as error:
    raise RuntimeError(f"lazycortex-core metrics-scrape-file printed unparseable JSON: {error}") from error


# ----------------------------------------------------------------------------------------
# Grafana dashboard provisioning
def _read_grafana_process_config() -> tuple[Path | None, Path | None]:
  """
  Read the config and homepath flags off a currently running Grafana server process.

  Notes:
    - Runs `ps` as a subprocess to inspect the host's process table.
    - When `ps` cannot be spawned or does not finish in time, the resulting `OSError` or
      `subprocess.SubprocessError` is caught
      and the pair `(None, None)` is returned.

  Returns:
    A pair `(config, homepath)` taken from a running Grafana server process's command line;
    either or both are `None` when no such process is found or it carries neither flag.
  """
  # guard: no usable `ps` on this host — the caller stays on the packaged config candidates
  try:
    # waiver: external ps flags, not internal keys
    proc = subprocess.run(
      [ "ps", "-Ao", "args=" ], capture_output = True, text = True, check = False, timeout = _PS_TIMEOUT_SEC,
    )
  except (OSError, subprocess.SubprocessError):
    return None, None

  # scan the table for a grafana server line and lift its path flags
  for line in proc.stdout.splitlines():
    # guard: reject every process line that is not a grafana server
    if not any(marker in line for marker in _GRAFANA_SERVER_MARKERS):
      continue

    # lift the two path flags off the matched command line
    config: Path | None = None
    homepath: Path | None = None
    # limit: args split on whitespace miss a path with a space, switch to a delimited `ps -Ao pid=,args=` read
    for arg in line.split():
      if arg.startswith(_GRAFANA_CONFIG_FLAG):
        config = Path(arg[len(_GRAFANA_CONFIG_FLAG):])
      elif arg.startswith(_GRAFANA_HOMEPATH_FLAG):
        homepath = Path(arg[len(_GRAFANA_HOMEPATH_FLAG):])

    # guard: reject a grafana line that carries neither path flag
    if not (config or homepath):
      continue

    # the first grafana line carrying a path flag answers for the host
    return config, homepath

  # no grafana server is running on this host
  return None, None


def _resolve_provisioning_dir(config: Path, homepath: Path | None) -> Path | None:
  """
  Resolve the provisioning directory a Grafana config file points at.

  Guarantees:
    - A relative provisioning path always resolves against Grafana's homepath, matching
      Grafana's own resolution rule.

  Args:
    config: Path to the `grafana.ini` file to read.
    homepath: Grafana's homepath, used to resolve a relative provisioning path, or `None`
      when unknown.

  Returns:
    The resolved provisioning directory, or `None` when the config is malformed or the
    provisioning path is relative and no `homepath` is available to resolve it against. A config
    that cannot be opened declares no path, so Grafana's default relative path is resolved
    instead.
  """
  # parse the ini permissively — a consumer's grafana.ini carries duplicate sample keys
  parser = configparser.RawConfigParser(strict = False)

  # guard: a malformed ini leaves nothing to resolve (an unopenable one is skipped by the parser)
  try:
    parser.read(config)
  except (OSError, configparser.Error):
    return None

  # read the declared provisioning path, falling back to Grafana's own default
  path = Path(os.path.expanduser(
    parser.get(_GRAFANA_PATHS_SECTION, _GRAFANA_PROVISIONING_KEY, fallback = "").strip()
    or _GRAFANA_DEFAULT_PROVISIONING
  ))

  # Contract:
  # A relative provisioning path always resolves against Grafana's homepath, matching
  # Grafana's own resolution rule.

  # Grafana resolves a relative provisioning path against its homepath
  if not path.is_absolute():
    # guard: a relative path with no known homepath cannot be resolved
    if homepath is None:
      return None

    # anchor the relative path at the homepath
    path = homepath / path

  # the provisioning root every dashboard target hangs off
  return path


def detect_grafana_dashboards_dir() -> Path | None:
  """
  Locate the host's Grafana dashboard-provisioning directory.

  Resolves to the directory Grafana already watches for provisioning, so callers can deploy
  dashboards without hardcoding a host-specific path.

  Guarantees:
    - A recorded operator override is authoritative and terminal: its directory, or `None` when
      it does not exist, is returned without running any further probe.
    - Absent a recorded override, the fixed detection order decides the result: a running
      Grafana server's own config, then the packaged `grafana.ini` locations, and the first
      candidate that resolves to an existing dashboards directory wins.

  Notes:
    - Reads the host's running process list to look for a live Grafana server; if that read
      fails, detection falls back to the packaged config candidates instead of raising.

  Returns:
    The resolved dashboards directory, or `None` when a recorded override does not resolve to
    an existing directory (skipping every further probe), or when no override is recorded and
    no probed Grafana config resolves to an existing dashboards directory.

  Raises:
    OSError: If the answer file exists but cannot be read.
  """

  # Domain(observe.install-state):
  # # Dashboard provisioning directory is found by a fixed discovery order
  # A host's dashboard-rendering tool keeps a directory it automatically loads dashboards from, and this
  # installer discovers that directory rather than assuming a fixed location for it. An operator's own
  # recorded answer for this host is authoritative and stops the search immediately. Absent that, a
  # currently running instance of the tool is asked for its own configuration, since a live instance
  # reflects what the operator actually deployed rather than a guessed default; only when nothing is
  # running does the search fall back to the handful of locations the tool's own packaging conventionally
  # installs its configuration to. A relative provisioning path declared in that configuration is never
  # resolved against the working directory of whatever process reads it — it resolves against the tool's
  # own home directory, matching the tool's own resolution rule, so the same relative path always names the
  # same directory regardless of where it happens to be read from.

  # Contract:
  # A recorded operator override is authoritative and terminal: its resolved directory,
  # or `None` when it is not an existing directory, is returned without running any probe.

  # a recorded operator override is authoritative and terminal; no probe runs after it
  if recorded := read_answer_file().get(_ANSWER_KEY_DASHBOARD_DIR):
    override = Path(os.path.expanduser(str(recorded)))
    return override if override.is_dir() else None

  # Contract:
  # Absent a recorded override, the probes run in a fixed order — the running Grafana
  # server's own config, then the packaged `grafana.ini` locations — and the first
  # candidate that resolves to an existing dashboards directory wins.

  # build the config candidates, the running instance's own outranking the packaged locations
  running_config, homepath = _read_grafana_process_config()
  candidates = ([ running_config ] if running_config else []) + [
    candidate for candidate in _GRAFANA_CONFIG_CANDIDATES if candidate != running_config
  ]

  # take the first candidate that resolves to a dashboards directory this host carries
  for candidate in candidates:
    # guard: reject candidates absent from this host
    if not candidate.is_file():
      continue

    # guard: reject a config that is unreadable or leaves a relative path unresolvable
    if (provisioning := _resolve_provisioning_dir(candidate, homepath)) is None:
      continue

    # the first candidate whose dashboards directory exists on this host is the answer
    if (dashboards := provisioning / _GRAFANA_DASHBOARDS_SUBDIR).is_dir():
      return dashboards

  # no candidate carried a dashboards directory
  return None


def deploy_dashboards(target_dir: Path | None = None) -> dict[str, object]:
  """
  Copy the plugin's shipped Grafana dashboards into the host's provisioning directory.

  Reaches only the dashboard JSON files themselves; Grafana's own configuration is never
  written by this call.

  Guarantees:
    - Each written dashboard file is always either the previous complete content or the new
      complete content, never a partial write.
    - A dashboard payload already byte-identical to the file on disk is left untouched and
      counted as unchanged rather than rewritten.

  Notes:
    - Writes dashboard files into a host directory outside the repository.
    - When no destination is supplied, resolution reads the host's process table and
      Grafana's own configuration files.

  Args:
    target_dir: Destination provisioning directory to write into. Detected automatically when
      omitted.

  Returns:
    A mapping with `outcome` (`installed`, `unchanged`, or `skipped-no-grafana`), `dir` (the
    resolved destination or `None`), and the `written` / `unchanged` dashboard file name lists.

  Raises:
    OSError: If the target directory tree cannot be written to.
    PermissionError: If the process lacks permission to write into the target directory, such
      as a root-owned provisioning tree.
  """
  # guard: reject the copy when neither the caller nor this host names a Grafana provisioning tree
  if (target := target_dir or detect_grafana_dashboards_dir()) is None:
    # waiver: outcome tokens of the dashboard-provisioning step contract
    return { "outcome": "skipped-no-grafana", "dir": None, "written": [], "unchanged": [] }

  # per-file verdicts the install step reports back
  written: list[str] = []
  unchanged: list[str] = []

  # copy every shipped dashboard, skipping the ones already byte-identical on disk
  for name in sorted(os.listdir(DASHBOARD_DIR)):
    # guard: reject directory entries that are not JSON payloads
    if not name.endswith(_JSON_SUFFIX):
      continue

    # load the shipped payload and name its destination
    payload = (DASHBOARD_DIR / name).read_bytes()
    installed = target / name

    # Contract:
    # A dashboard payload already byte-identical to the file on disk is left untouched and
    # counted as unchanged rather than rewritten.

    # guard: reject a rewrite of a payload already identical on disk
    if installed.is_file() and installed.read_bytes() == payload:
      unchanged.append(name)
      continue

    # Contract:
    # Each written dashboard file is always either the previous complete content or the new
    # complete content, never a partial write.

    # write through a sibling temp file so an interrupted copy never leaves a half-written dashboard
    _write_atomic(installed, payload)
    written.append(name)

  # the step's outcome, destination and per-file verdicts
  # waiver: outcome tokens of the dashboard-provisioning step contract
  return {
    "outcome": "installed" if written else "unchanged",
    "dir": str(target), "written": written, "unchanged": unchanged,
  }



# ----------------------------------------------------------------------------------------
class _LoopFrame(TypedDict):
  """
  One open `{% for %}` block while its body is being collected.

  Attributes:
    var: Name of the loop variable bound per iteration.
    seq: Items the body is replayed over; empty when the loop sits inside an inactive branch.
    body: Buffered `(kind, payload)` fragments — literal text or a deferred expression.
    active: Whether the loop sits inside an active conditional branch.
  """

  # name of the loop variable bound per iteration
  var: str
  # items the body is replayed over; empty when the loop sits inside an inactive branch
  seq: list[object]
  # buffered `(kind, payload)` fragments — literal text or a deferred expression
  body: list[tuple[str, str]]
  # whether the loop sits inside an active conditional branch
  active: bool



# ----------------------------------------------------------------------------------------
class _Template:
  """
  Minimal text template engine for the small Jinja2-style dialect used in this module.

  Supports `{{ var }}` and `{{ var | default('foo') }}` substitutions,
  `{% if %} / {% elif %} / {% else %} / {% endif %}` conditional blocks, and
  `{% for var in seq %} / {% endfor %}` loops. Unsupported directives raise
  `SyntaxError` so that a Jinja2 mistake fails loudly rather than silently
  producing wrong output.

  Attributes:
    src: Raw template text rendered by `render()`.
    vars: Mapping of variable names to substituted values; the loop variable is bound into it
      during `{% for %}` expansion and removed again afterwards.
  """

  # directive keyword that opens a conditional frame; its length strips the keyword off the test text
  _IF_PREFIX = "if "

  # directive keyword that re-tests an open frame; its length strips the keyword off the test text
  _ELIF_PREFIX = "elif "

  # one token per substitution or directive: group 1 is a `{{ }}` expression, group 2 a `{% %}` directive
  _RE = re.compile(
    r"\{\{\s*(.+?)\s*\}\}"        # {{ var }}
    r"|\{%\s*(.+?)\s*%\}",        # {% directive %}
    re.DOTALL,
  )


  # waiver: `vars` is the substitution-dict param name; shadowing builtin vars() is harmless,
  # not restructured for a checker
  # pylint: disable-next=redefined-builtin
  def __init__(self, src: str, vars: dict[str, object]) -> None:
    """
    Initialise the engine with template source and a variable mapping.

    Args:
      src: Raw template text to render.
      vars: Mapping of variable names to substituted values; modified
        in-place during loop expansion to bind the loop variable.
    """
    self.src = src
    self.vars = vars


  def _emit(self, out: list[str], loop_stack: list[_LoopFrame], text: str, *, active: bool) -> None:
    """
    Append a literal text chunk to the output or the innermost loop body.

    Args:
      out: Top-level output buffer to extend when no loop is active.
      loop_stack: Stack of loop frames; when non-empty the chunk is buffered
        on the innermost frame instead of emitted immediately.
      text: Literal text chunk to append.
      active: Whether the surrounding conditional branch is active; inactive
        chunks are dropped silently.
    """
    # guard: skip inactive branches and empty chunks
    if not active or not text:
      return

    # inside a loop the chunk is buffered on the innermost frame; otherwise it is emitted directly
    if loop_stack:
      # waiver: loop-frame field and fragment tag, internal to the engine
      loop_stack[-1]["body"].append(("text", text))
    else:
      out.append(text)


  def _apply_directive(self,
                       directive: str,
                       stack: list[tuple[bool, bool]],
                       loop_stack: list[_LoopFrame],
                       *,
                       out: list[str]) -> None:
    """
    Apply one `{% ... %}` directive to the conditional and loop stacks.

    Handles `if` / `elif` / `else` / `endif` for conditional blocks and `for`
    / `endfor` for loops. Any other directive raises `SyntaxError`.

    Args:
      directive: The directive text between `{%` and `%}` with surrounding
        whitespace already stripped.
      stack: Conditional stack of `(active, true_branch_taken)` frames.
      loop_stack: Loop stack of frames buffering iteration bodies.
      out: Top-level output buffer used when a loop emits expanded content.

    Raises:
      SyntaxError: If the directive is unsupported or a `for` directive is
        malformed.
      TypeError: If a `for` directive iterates over a non-iterable value.
    """
    active = stack[-1][0]

    # a new conditional frame is active only when its parent is active and the test passes
    if directive.startswith(self._IF_PREFIX):
      cond = self._is_truthy(directive[len(self._IF_PREFIX):]) if active else False
      stack.append((cond, cond))

    # elif re-tests only while no earlier branch of this frame has been taken
    elif directive.startswith(self._ELIF_PREFIX):
      _prev_active, branch_taken = stack[-1]
      # a frame whose branch was already taken stays inactive for every later branch
      if branch_taken:
        stack[-1] = (False, True)
      # otherwise the elif test decides, but only inside an active parent frame
      elif stack[-2][0] and self._is_truthy(directive[len(self._ELIF_PREFIX):]):
        stack[-1] = (True, True)
      else:
        stack[-1] = (False, branch_taken)

    # else activates only when every earlier branch of this frame was skipped
    # waiver: template-dialect directive keyword, internal to the engine
    elif directive == "else":
      _prev_active, branch_taken = stack[-1]
      if branch_taken:
        stack[-1] = (False, True)
      elif stack[-2][0]:
        stack[-1] = (True, True)

    # endif closes the frame its matching if opened
    # waiver: template-dialect directive keyword, internal to the engine
    elif directive == "endif":
      stack.pop()

    # for buffers its body instead of emitting it, so endfor can replay it per item
    # waiver: template-dialect directive keyword, internal to the engine
    elif directive.startswith("for "):
      # guard: malformed for directive — the shape is `for item in seq`
      if not (match := re.match(r"for\s+(\w+)\s+in\s+(\S+)", directive)):
        raise SyntaxError(f"bad for: {directive!r}")

      # an active loop resolves its sequence now; an inactive one opens an empty frame so endfor still matches
      if active:
        # guard: refuse to iterate over a non-iterable value
        if not isinstance(seq := self._evaluate_value(match.group(2)), Iterable):
          raise TypeError(f"non-iterable in for: {seq!r}")

        # open the live frame with the materialised sequence
        # waiver: loop-frame field names, internal to the engine
        loop_stack.append({ "var": match.group(1), "seq": list(seq), "body": [], "active": True })
      else:
        # waiver: loop-frame field names, internal to the engine
        loop_stack.append({ "var": match.group(1), "seq": [], "body": [], "active": False })

    # endfor replays the buffered body once per sequence item
    # waiver: template-dialect directive keyword, internal to the engine
    elif directive == "endfor":
      # guard: skip expansion when the loop sat inside an inactive branch
      # waiver: loop-frame field name, internal to the engine
      if not (frame := loop_stack.pop())["active"]:
        return

      # replay the buffered body once per item with the loop variable bound: a deferred expression is
      # evaluated now, literal text replays as is, and either lands in the enclosing loop or the output
      # waiver: loop-frame field name, internal to the engine
      for item in frame["seq"]:
        # waiver: loop-frame field name, internal to the engine
        self.vars[frame["var"]] = item
        # waiver: loop-frame field name, internal to the engine
        for kind, payload in frame["body"]:
          # waiver: fragment tag, internal to the engine
          self._emit(out, loop_stack, self._evaluate_expr(payload) if kind == "expr" else payload, active = True)

      # remove the loop variable so it does not leak into the surrounding scope
      # waiver: loop-frame field name, internal to the engine
      self.vars.pop(frame["var"], None)

    # anything outside the dialect is a rendering error, never a silent skip
    else:
      raise SyntaxError(f"unsupported template directive: {directive!r}")


  def _is_truthy(self, expr: str) -> bool:
    """
    Evaluate the truthiness of a minimal conditional expression.

    Supports `kind == "value"` equality comparisons against a string literal
    and bare variable references that are evaluated by Python truthiness.

    Args:
      expr: Conditional expression text from inside an `{% if %}` or
        `{% elif %}` directive.

    Returns:
      `True` when the comparison or variable evaluates as truthy, `False`
      otherwise.
    """
    # the equality form `name == "literal"` is tried first so a quoted literal never reads as a bare
    # variable name
    if match := re.match(r'(\w+)\s*==\s*"([^"]*)"$', expr):
      return str(self.vars.get(match.group(1))) == match.group(2)

    # a bare name evaluates by Python truthiness of its bound value
    return bool(self.vars.get(expr))


  def _evaluate_expr(self, expr: str) -> str:
    """
    Evaluate a substitution expression and return its string form.

    Supports the `name | default('foo')` filter form that falls back to the
    given default when the variable is missing or empty, and the bare
    `name` form that returns the variable value coerced to string.

    Args:
      expr: Substitution expression text from inside a `{{ ... }}` block.

    Returns:
      The rendered string value for the expression, or an empty string when
      the variable is not bound.
    """
    # the filter form `name | default('...')` is tried first so a piped expression never reads as a
    # bare variable name
    if match := re.match(r"(\w+)\s*\|\s*default\(\s*'([^']*)'\s*\)$", expr):
      # guard: an unbound or empty variable yields the filter's default
      if (value := self.vars.get(match.group(1))) is None or value == "":
        return match.group(2)

      # a bound, non-empty variable renders as itself
      return str(value)

    # a bare name renders its bound value, or nothing when unbound
    return str(self.vars.get(expr, ""))


  def _evaluate_value(self, ident: str) -> object:
    """
    Resolve an identifier used as the iterable side of a `{% for %}` directive.

    Args:
      ident: Variable name from the directive, possibly with surrounding
        whitespace.

    Returns:
      The bound value from the variable mapping, or an empty list when the
      identifier is not bound — making an empty loop the default behaviour.
    """
    return self.vars.get(ident.strip(), [])


  def render(self) -> str:
    """
    Render the configured template source into a string.

    Returns:
      The rendered template text with all substitutions, conditionals, and
      loops resolved.

    Raises:
      SyntaxError: If the template uses an unsupported directive or contains
        an unclosed `{% if %}` or `{% for %}` block.
      TypeError: If a `{% for %}` directive iterates over a non-iterable
        value.
    """
    out: list[str] = []

    # stack of (active, true_branch_taken) — controls whether to emit text
    stack: list[tuple[bool, bool]] = [ (True, True) ]

    # loop stack: each frame collects body fragments and replays them per iteration on endfor
    loop_stack: list[_LoopFrame] = []

    # walk the source left to right, emitting the literal text between two directives
    pos = 0
    for match in self._RE.finditer(self.src):
      self._emit(out, loop_stack, self.src[pos:match.start()], active = stack[-1][0])
      pos = match.end()

      # substitution form: {{ expr }}
      if match.group(1) is not None:
        expr = match.group(1).strip()
        if stack[-1][0]:
          if loop_stack:
            # defer evaluation — the loop variable is unbound during body collection;
            # endfor replays each entry with vars[var] set per iteration
            # waiver: loop-frame field and fragment tag, internal to the engine
            loop_stack[-1]["body"].append(("expr", expr))
          else:
            out.append(self._evaluate_expr(expr))
      # directive form: {% ... %}
      else:
        self._apply_directive(match.group(2).strip(), stack, loop_stack, out = out)

    # flush any trailing text after the last match
    self._emit(out, loop_stack, self.src[pos:], active = stack[-1][0])

    # guard: every {% if %} must be closed before the template ends
    if len(stack) != 1:
      raise SyntaxError("template ended with unclosed {% if %} block")

    # guard: every {% for %} must be closed before the template ends
    if loop_stack:
      raise SyntaxError("template ended with unclosed {% for %} block")

    # the fully rendered text
    return "".join(out)



# ----------------------------------------------------------------------------------------
# CLI entry: the skills' subcommands
def _probe_targets(targets: list[dict[str, object]]) -> list[tuple[str, str, bool]]:
  """
  Probe every registered daemon's metrics endpoint once.

  Args:
    targets: Rows from `read_local_scrape_targets()`.

  Returns:
    One `(repo_label, address, served)` triple per row, in registry order.
  """
  # one probe per daemon at the address a same-host collector would scrape
  results: list[tuple[str, str, bool]] = []
  for row in targets:
    address = format_scrape_address(row)
    # waiver: external JSON contract field name of the core daemon-list CLI
    results.append((str(row["repo_label"]), address, check_local_metrics(address)))
  return results


def _print_smoke_lines(results: list[tuple[str, str, bool]]) -> None:
  """
  Print the `<repo_label> <address> <served>` report line per probed daemon.

  Args:
    results: Triples from `_probe_targets()`.
  """
  # one report line per daemon, in registry order
  for label, address, served in results:
    print(label, address, served)


def _parse_var(pair: str) -> tuple[str, object]:
  """
  Split one `key=value` CLI pair, decoding a JSON value when the text parses as one.

  Args:
    pair: The raw `key=value` text.

  Returns:
    The key and its decoded value; text that is not JSON stays a plain string.

  Raises:
    ValueError: If the pair carries no `=`.
  """
  key, sep, raw = pair.partition("=")

  # guard: a pair without a separator cannot name a key
  if not sep:
    raise ValueError(f"expected key=value, got {pair!r}")

  # a JSON literal (list, number, boolean) decodes; anything else is the string as typed
  try:
    return key, json.loads(raw)
  except json.JSONDecodeError:
    return key, raw


def cmd_smoke(_argv: list[str]) -> None:
  """
  Print one `<repo_label> <address> <served>` line per registered scrape target, then a summary token.

  Guarantees:
    - The last printed line is always `none-registered` when the registry holds no metrics-enabled
      daemon and `done` otherwise.

  Args:
    _argv: Unused; the subcommand takes no arguments.

  Raises:
    RuntimeError: If the core CLI cannot be found, exits non-zero, or prints unparseable JSON.
    subprocess.TimeoutExpired: If the core CLI does not exit within the wall-clock cap.
  """
  targets = read_local_scrape_targets()
  _print_smoke_lines(_probe_targets(targets))

  # Contract:
  # The last printed line is always `none-registered` when the registry holds no metrics-enabled
  # daemon and `done` otherwise.

  # close with the summary token the skill branches on
  # waiver: summary tokens of the skill's smoke-step contract
  print("none-registered" if not targets else "done")


def cmd_wait_metrics(argv: list[str]) -> None:
  """
  Poll the registered daemons' metrics endpoints until one answers or the timeout elapses.

  Prints the final per-daemon report lines, then `up` when at least one endpoint served the
  runtime series and `not-up` otherwise.

  Args:
    argv: Argument vector after the subcommand name (optional `--timeout` seconds).

  Raises:
    RuntimeError: If the core CLI cannot be found, exits non-zero, or prints unparseable JSON.
    subprocess.TimeoutExpired: If the core CLI does not exit within the wall-clock cap.
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "install.py wait-metrics")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--timeout", type = float, default = _WAIT_DEFAULT_SEC, help = "Seconds to wait")
  args = parser.parse_args(argv)
  targets = read_local_scrape_targets()

  # the first probe runs before the deadline is checked, so a zero timeout still reports every daemon once
  deadline = time.monotonic() + args.timeout
  results = _probe_targets(targets)

  # re-probe every poll interval until one endpoint serves the runtime series or the deadline passes
  while not any(served for _label, _address, served in results) and time.monotonic() < deadline:
    time.sleep(_WAIT_POLL_SEC)
    results = _probe_targets(targets)
  _print_smoke_lines(results)

  # close with the verdict token the skill branches on
  # waiver: verdict tokens of the skill's load-service step contract
  print("up" if any(served for _label, _address, served in results) else "not-up")


def cmd_read_answers(_argv: list[str]) -> None:
  """
  Print the persisted non-secret answers as indented JSON (an empty object when none exist).

  Args:
    _argv: Unused; the subcommand takes no arguments.

  Raises:
    OSError: If the answer file exists but cannot be read.
  """
  print(json.dumps(read_answer_file(), indent = 2))


def cmd_set_answer(argv: list[str]) -> None:
  """
  Merge `key=value` pairs into the answer file and print the resulting answers as indented JSON.

  Args:
    argv: One or more `key=value` pairs; a JSON-looking value decodes, anything else stays text.

  Raises:
    ValueError: If a pair carries no `=`, or a key is a token-like secret key the answer file refuses.
    OSError: If the answer file cannot be read or written.
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "install.py set-answer")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("pairs", nargs = "+", metavar = "key=value")
  merged = { **read_answer_file(), **dict(_parse_var(pair) for pair in parser.parse_args(argv).pairs) }
  write_answer_file(merged)
  print(json.dumps(merged, indent = 2))


def cmd_write_token(_argv: list[str]) -> None:
  """
  Read the secret from stdin and persist it to the 0600 token file, printing the path as JSON.

  Args:
    _argv: Unused; the token arrives on stdin so it never lands in a process argument list.

  Raises:
    OSError: If the token file or its parent directory cannot be written or its permissions
      cannot be tightened.
  """
  # waiver: CLI result field name of the write-token contract
  print(json.dumps({ "path": str(write_token_file(sys.stdin.read().strip())) }))


def cmd_find_agent(argv: list[str]) -> None:
  """
  Locate the shipping agent binary for a kind and print `{"kind", "path"}` as JSON.

  Args:
    argv: The agent kind (`alloy` or `otelcol`).

  Raises:
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "install.py find-agent")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("kind")
  kind = parser.parse_args(argv).kind
  path = find_agent_binary(kind)
  # waiver: CLI result field names of the find-agent contract
  print(json.dumps({ "kind": kind, "path": None if path is None else str(path) }))


def cmd_render_config(argv: list[str]) -> None:
  """
  Render a shipped template to a target path and print `{"path", "outcome"}` as JSON.

  The persisted answers seed the template variables; `--var key=value` pairs override them, and
  `--agent-kind` adds the multi-target `scrape_targets_block` covering every metrics-enabled daemon.

  Guarantees:
    - A target already byte-identical to the fresh render is left untouched and reported as
      `unchanged`; every other case writes and reports `rendered`.

  Args:
    argv: Template name, `--target <path>`, optional `--agent-kind <kind>`, repeatable `--var key=value`.

  Raises:
    ValueError: If a `--var` pair carries no `=`.
    FileNotFoundError: If the named template does not exist.
    SyntaxError: If the template uses an unsupported directive or has an unclosed block.
    TypeError: If a `{% for %}` directive iterates over a non-iterable value.
    RuntimeError: If `--agent-kind` is given and the core CLI cannot be found, exits non-zero, or
      prints unparseable JSON.
    subprocess.TimeoutExpired: If the core CLI does not exit within the wall-clock cap.
    OSError: If the target file or its parent directory cannot be read or written.
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "install.py render-config")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("template")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--target", required = True, help = "Destination path of the rendered file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--agent-kind", default = None, help = "Compute scrape_targets_block for this agent kind")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--var", action = "append", default = [], metavar = "key=value", help = "Override a variable")
  args = parser.parse_args(argv)

  # persisted answers seed the variables; explicit pairs override them
  variables: dict[str, object] = { **read_answer_file(), **dict(_parse_var(pair) for pair in args.var) }
  if args.agent_kind:
    # waiver: template variable name of the shipped agent-config templates
    variables["scrape_targets_block"] = render_scrape_targets_block(read_local_scrape_targets(), args.agent_kind)

  # Contract:
  # A target already byte-identical to the fresh render is left untouched and reported as
  # `unchanged`; every other case writes and reports `rendered`.

  # settle the target path and the fresh render the byte-identical check compares against
  target = Path(os.path.expanduser(args.target))
  body = render(args.template, variables)

  # guard: the target already carries the fresh render — nothing to write
  # waiver: stdlib encoding/mode/escape idiom
  if target.is_file() and target.read_text(encoding = "utf-8") == body:
    # waiver: outcome tokens of the skill's render-step contract
    print(json.dumps({ "path": str(target), "outcome": "unchanged" }))
    return

  # write the already rendered body atomically and report the target as rendered
  target.parent.mkdir(parents = True, exist_ok = True)
  _write_atomic(target, body)
  # waiver: outcome tokens of the skill's render-step contract
  print(json.dumps({ "path": str(target), "outcome": "rendered" }))


def _parse_plist_arg(argv: list[str], prog: str) -> Path:
  """
  Parse the optional `--plist` override shared by the load / unload subcommands.

  Args:
    argv: Argument vector after the subcommand name.
    prog: Program name for the usage line.

  Returns:
    The launchd plist path to act on (ignored on Linux).

  Raises:
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = prog)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--plist", default = str(_DEFAULT_PLIST), help = "launchd plist path (macOS only)")
  return Path(os.path.expanduser(parser.parse_args(argv).plist))


def cmd_load_service(argv: list[str]) -> None:
  """
  Load the shipper's service unit for the current host and print `{"ok", "stderr"}` as JSON.

  Args:
    argv: Optional `--plist <path>` override for macOS.

  Raises:
    ValueError: If the current platform is neither macOS nor Linux.
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: parsed ahead of the host check so a bad argv fails on Linux too, where the value goes unused
  plist = _parse_plist_arg(argv, "install.py load-service")
  # waiver: OS/platform token (detect_host), external
  succeeded, stderr = load_service_macos(plist) if detect_host() == "darwin" else load_service_linux()
  # waiver: CLI result field names of the service-step contract
  print(json.dumps({ "ok": succeeded, "stderr": stderr }))


def cmd_unload_service(argv: list[str]) -> None:
  """
  Unload the shipper's service unit for the current host and print `{"ok", "stderr"}` as JSON.

  Args:
    argv: Optional `--plist <path>` override for macOS.

  Raises:
    ValueError: If the current platform is neither macOS nor Linux.
    SystemExit: If `argv` does not parse; argparse exits with status 2 after printing the usage.
  """
  # waiver: parsed ahead of the host check so a bad argv fails on Linux too, where the value goes unused
  plist = _parse_plist_arg(argv, "install.py unload-service")
  # waiver: OS/platform token (detect_host), external
  succeeded, stderr = unload_service_macos(plist) if detect_host() == "darwin" else unload_service_linux()
  # waiver: CLI result field names of the service-step contract
  print(json.dumps({ "ok": succeeded, "stderr": stderr }))


def cmd_dashboards_dir(_argv: list[str]) -> None:
  """
  Print the detected Grafana dashboards provisioning directory as `{"dir"}` JSON.

  Args:
    _argv: Unused; the subcommand takes no arguments.

  Raises:
    OSError: If the answer file exists but cannot be read.
  """
  found = detect_grafana_dashboards_dir()
  # waiver: CLI result field name of the dashboards-dir contract
  print(json.dumps({ "dir": None if found is None else str(found) }))


# waiver: subcommand names of the skill-facing CLI contract, not internal keys
_COMMANDS = {
  "detect-coverage": lambda _argv: print(json.dumps(detect_existing_coverage(), indent = 2)),
  "write-scrape": lambda _argv: print(json.dumps(write_scrape_file_via_core(), indent = 2)),
  "smoke": cmd_smoke,
  "wait-metrics": cmd_wait_metrics,
  "deploy-dashboards": lambda _argv: print(json.dumps(deploy_dashboards())),
  "dashboards-dir": cmd_dashboards_dir,
  "read-answers": cmd_read_answers,
  "set-answer": cmd_set_answer,
  "write-token": cmd_write_token,
  "find-agent": cmd_find_agent,
  "render-config": cmd_render_config,
  "load-service": cmd_load_service,
  "unload-service": cmd_unload_service,
}


def main(argv: list[str]) -> int:
  """
  Parse the subcommand and run it with the remaining arguments, printing its result to stdout.

  Args:
    argv: Argument vector after the program name.

  Returns:
    Process exit code, always 0; every subcommand reports through its printed output.

  Raises:
    SystemExit: If the subcommand is unknown or its arguments do not parse; argparse exits
      with status 2 after printing the usage.
    RuntimeError: If a subcommand needs the core CLI and it cannot be found, exits non-zero, or
      prints unparseable JSON.
    subprocess.TimeoutExpired: If the core CLI does not exit within the wall-clock cap.
    ValueError: If a `key=value` pair carries no `=`, a secret-looking answer key is refused, or
      the platform is neither macOS nor Linux.
    FileNotFoundError: If a template named for rendering does not exist.
    SyntaxError: If a rendered template uses an unsupported directive or has an unclosed block.
    TypeError: If a rendered template iterates a `{% for %}` over a non-iterable value.
    OSError: If an answer, token, dashboard, or rendered file cannot be read or written.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "install.py")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("command", choices = sorted(_COMMANDS))
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("args", nargs = argparse.REMAINDER)
  args = parser.parse_args(argv)
  _COMMANDS[args.command](args.args)

  # every subcommand reports through its printed output, never through the exit code
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
