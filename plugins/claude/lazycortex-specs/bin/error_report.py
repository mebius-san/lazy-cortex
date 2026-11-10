"""
Error-ledger reporting for the specs plugin — one caller-side seam over the core verbs.

Every failure a `lazycortex-specs` worker reports in-band goes through here, and here only
ever calls `lazycortex-core error-record` (dev.plugin-boundaries § 1c): the
journal, the incident folding and the metrics belong to the core plugin, and this module knows
nothing about them beyond the wire contract. Every call is best-effort: a report that cannot
be delivered is dropped, and the flow that reports never fails because of it.

The module also remembers the incidents it opened as open, through marker files under the
repository's `.runtime/lazy-spec/open-incidents/` directory. A later success closes such an
incident through `error-record --incident <key> --resolve`, and a success with nothing remembered
spawns no core call at all.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class _Wire:
  """
  The CLI vocabulary of the core `error-record` verb: its subcommand name, flags and flag values.
  """

  # The core CLI subcommand that opens or closes an incident.
  RECORD = "error-record"
  # The event-kind flag.
  KIND_FLAG = "--kind"
  # The cause flag.
  CAUSE_FLAG = "--cause"
  # The incident-key flag.
  INCIDENT_FLAG = "--incident"
  # The severity flag.
  SEVERITY_FLAG = "--severity"
  # The free-text detail flag.
  DETAIL_FLAG = "--detail"
  # The flag that closes an incident instead of opening one.
  RESOLVE_FLAG = "--resolve"
  # The event kind every specs report carries.
  PLUGIN_ERROR = "plugin_error"
  # The severity of a failure that left the landed change intact.
  WARN = "warn"


# Repo-relative directory of the markers this plugin keeps for the ledger incidents it opened and has not closed,
# so a success learns whether it has anything to close without spawning core.
# opt: a marker exists only while the core ledger holds its incident open, which stays true because this plugin
# is the only writer of the incidents it marks; an incident closed by anyone else leaves a stale marker that sends
# one extra, harmless resolve on the next success and is then removed.
_OPEN_INCIDENTS_REL = ".runtime/lazy-spec/open-incidents"

# The incident-key separator, and the filename-safe character it becomes in a marker name.
_KEY_SEPARATOR = ":"
_MARKER_SEPARATOR = "."


def _run_core(repo: Path, *tail: str) -> subprocess.CompletedProcess[str] | None:
  """
  Run one core verb from the repository root, swallowing every failure to reach it.

  Args:
    repo: The repository root the ledger lives under; the verb runs with it as the working directory.
    tail: The verb and its arguments.

  Returns:
    The finished process, or `None` when the core CLI could not be found or started.
  """
  # a missing core plugin, an unstartable interpreter, an OS error or an argument or output the call cannot carry
  # each end in None, never in a raise
  try:
    cli = spec_paths.resolve_core_cli(repo)
    # waiver: stdlib subprocess idiom, the arguments are the wire contract
    return subprocess.run([ sys.executable, str(cli), *tail ], cwd = repo, capture_output = True, text = True,
                          check = False)
  # waiver: best-effort boundary — a report that cannot be delivered is dropped, never raised into the caller
  except (RuntimeError, OSError, ValueError):
    return None


def report_warning(repo: Path, *, cause: str, incident: str, detail: str) -> None:
  """
  Open, or add to, a `plugin_error` incident at warning severity.

  Guarantees:
    - Never raises, whatever happens to the core CLI.

  Args:
    repo: The repository root whose ledger records the event.
    cause: A stable cause token the specs plugin defines in `spec_keys.PluginErrorCause`.
    incident: A stable incident key; repeated reports of the same condition fold into it.
    detail: One line describing this occurrence; the changing part of the failure goes here.
  """

  # Contract:
  # The call MUST NEVER raise to its caller, whatever becomes of the core CLI.
  # A report that cannot be delivered is dropped, so a flow that reports a failure never fails because of it.

  # send the warning to the core ledger; an undeliverable report is dropped
  _record_warning(repo, cause = cause, incident = incident, detail = detail)


def _record_warning(repo: Path, *, cause: str, incident: str, detail: str) -> bool:
  """
  Send one warning event to the core ledger and tell whether core recorded it.

  Args:
    repo: The repository root whose ledger records the event.
    cause: The stable cause token.
    incident: The stable incident key.
    detail: One line describing this occurrence.

  Returns:
    `True` when `error-record` exited 0, `False` when the report could not be delivered or core refused it.
  """
  # only a clean exit means core holds the event, and with it an open incident
  done = _run_core(repo, _Wire.RECORD, _Wire.KIND_FLAG, _Wire.PLUGIN_ERROR, _Wire.CAUSE_FLAG, cause,
                   _Wire.INCIDENT_FLAG, incident, _Wire.SEVERITY_FLAG, _Wire.WARN, _Wire.DETAIL_FLAG, detail)
  return done is not None and done.returncode == 0


def _incident_marker(repo: Path, incident: str) -> Path:
  """
  Locate the marker that records an incident as opened by this plugin and not yet closed.

  Args:
    repo: The repository root.
    incident: The incident key.

  Returns:
    The marker path; it exists only while the incident is remembered as open.
  """
  # the incident key with its separator made filename-safe on every host
  return repo / _OPEN_INCIDENTS_REL / incident.replace(_KEY_SEPARATOR, _MARKER_SEPARATOR)


def report_marked_warning(repo: Path, *, cause: str, incident: str, detail: str) -> None:
  """
  Open, or add to, a `plugin_error` incident at warning severity and remember it as open.

  Guarantees:
    - Never raises, whatever happens to the core CLI or the marker directory; a report or marker that cannot be
      delivered is dropped.
    - The marker is written only after core accepted the report (`error-record` exited 0); a report that could not
      be delivered, or that core refused, writes no marker.

  Notes:
    - Records the event through the core CLI and writes a marker file for the incident under the repository's
      `.runtime/lazy-spec/open-incidents/` directory; repeated reports of one incident reuse the same marker.

  Args:
    repo: The repository root whose ledger records the event.
    cause: A stable cause token the specs plugin defines in `spec_keys.PluginErrorCause`.
    incident: A stable incident key; repeated reports of the same condition fold into it.
    detail: One line describing this occurrence; the changing part of the failure goes here.
  """

  # Contract:
  # The call MUST NEVER raise to its caller, whatever becomes of the core CLI or the marker directory.
  # A report or a marker that cannot be delivered is dropped, so a flow that reports a failure never fails because of it.

  # Contract:
  # The marker is written ONLY after core has accepted the report (`error-record` exited 0).
  # A report that could not be delivered, or that core refused, writes no marker,
  # so an incident this plugin did not open is never remembered as open.

  # guard: a report core did not record opened no incident, so there is nothing to remember as open
  if not _record_warning(repo, cause = cause, incident = incident, detail = detail):
    return

  # the marker tells a later success there is an incident to close; one that cannot be written is dropped
  marker = _incident_marker(repo, incident)
  try:
    marker.parent.mkdir(parents = True, exist_ok = True)
    marker.touch()
  # waiver: best-effort boundary — an unwritable runtime directory must not fail the flow that reports
  except OSError:
    pass


def resolve_marked(repo: Path, incident: str) -> None:
  """
  Close an incident this plugin remembers as open, and spawn nothing when it remembers none.

  Guarantees:
    - Never raises, whatever happens to the core CLI or the marker.
    - Without a marker for the incident, no core verb is run, so an incident that is not open never gains an event
      and a healthy flow never writes to the ledger or spawns the core CLI; this holds while this plugin is the
      only writer of the incidents it marks.
    - The marker is removed only once core accepted the close; an undeliverable or failed close closes nothing,
      the marker stays and a later success retries.

  Notes:
    - Closes the incident through the core CLI and deletes its marker file under the repository's
      `.runtime/lazy-spec/open-incidents/` directory.

  Args:
    repo: The repository root whose ledger holds the incident.
    incident: The incident key the failure was reported under.
  """

  # Contract:
  # The call MUST NEVER raise to its caller, whatever becomes of the core CLI or the marker.

  # Contract:
  # When no marker remembers the incident as open, NO core verb is run.
  # An incident that is not open therefore never gains an event, and a healthy flow never writes to the ledger
  # or spawns the core CLI. This holds while this plugin is the only writer of the incidents it marks.

  # Contract:
  # The marker is removed ONLY after core has accepted the close.
  # An undeliverable or failed close closes nothing and the marker stays, so a later success retries it.

  # the marker that remembers whether this plugin opened the incident
  marker = _incident_marker(repo, incident)

  # an unreadable runtime directory counts as no marker, so the call never raises out of the probe
  try:
    remembered = marker.is_file()
  # waiver: best-effort boundary — a marker that cannot be probed leaves the incident to the operator
  except OSError:
    remembered = False

  # guard: no incident is remembered as open, so the success needs nothing from core
  if not remembered:
    return

  # the success is the proof the condition cleared; the marker goes only once core took the close
  done = _run_core(repo, _Wire.RECORD, _Wire.INCIDENT_FLAG, incident, _Wire.RESOLVE_FLAG)
  if done is not None and done.returncode == 0:
    try:
      marker.unlink(missing_ok = True)
    # waiver: best-effort boundary — a stale marker only costs one more resolve on the next success
    except OSError:
      pass
