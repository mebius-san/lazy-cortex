"""
Coordinator wake-trigger worker for the `lazy-review.coordinator-watch` git-watch routine.

Invoked once per git-watch tick by a `type: git`, `watch: changed_files` routine. The routine's
default `group: "all"` hands the daemon's whole tick over as one JSON argv — `{dir: ".", paths:
[...], sha, author_name, author_email}` — and this worker fans it out per path, judging every
changed document under review in turn; the plain single-file item `(path, status, sha,
author_name, author_email)` is still accepted as one unit of its own. A grouped item's `sha` and
author name the range's last commit, which may not touch a given document at all, so each per-path
unit is re-keyed to that document's own last commit before any trigger is read: every trigger
judges the file's own commit. A path whose dispatch raises is reported back to the daemon as the
last stdout line, `{"failed_paths": [...]}`, with a non-zero exit, so only those paths are retried
next tick. Four wake triggers are checked in order — `review-entry` (a document just opted into
review), `job-done` (the postman raised a `pending_wake` after landing a payload), `command` (a
non-empty `[!todo] #review/command` callout outside code fences and foreign protected sections),
`operator-edit` (a non-bot commit) — and the first
that fires dispatches one `review.coordinator` expert job via the `lazycortex-core dispatch-job`
CLI (the § 1c plugin-boundary contract). A ticked question option is not a trigger of its own: the
tick normally arrives in an operator commit, wakes `operator-edit`, and the coordinator reads it
out of the document's own report. A tick that a bot commit carried in still wakes `operator-edit`
— a tick is an operator gesture by system invariant (bots never tick), so a fresh `- [x]` appearing
between the pre-commit blob and the current text fires the trigger regardless of the commit's
author.

Both markers this worker reads live in `job_markers.py`'s gitignored runtime sidecar rather than
in the document, so neither writing nor clearing one costs a commit and neither is reachable by an
operator's hand-edit. The `coordinator_job` marker enforces one active coordinator job per
document: naming a bundle that is still running is a silent skip, checked before any trigger, while
naming a finished, dead, cancelled, or vanished bundle clears the marker and the same invocation
carries on to trigger resolution.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import note_ops as _note_ops  # noqa: E402
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import parser as _parser  # noqa: E402  # pylint: disable=wrong-import-position,deprecated-module,import-error
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    BotIdentity, CoreCommand, EnvVar, JobFile, JobKey, JobMarker, Paths, ReviewKey, ReviewProtocol, Trailer,
)


# The fixed expert this worker ever dispatches — one persona for every document, never resolved
# from a review class (unlike the per-document main-writer resolution the review loop itself does).
_COORDINATOR_EXPERT = "review.coordinator"

# Wire keys on a `changed_files` git-watch item (`lazycortex-core`'s `routine_types._compute_git_items`).
# `paths` / `dir` are the grouped-unit keys the default `group: "all"` adds; `path` is the file-level one.
_ITEM_PATH = "path"
_ITEM_PATHS = "paths"
_ITEM_DIR = "dir"
_ITEM_SHA = "sha"
_ITEM_AUTHOR_NAME = "author_name"
_ITEM_AUTHOR_EMAIL = "author_email"

# The git pathspec magic that makes one path match itself only, never as a glob.
_LITERAL_PATHSPEC = ":(literal)"

# The partial-failure line a `command` worker prints LAST on stdout so the daemon narrows the retry
# to the named subset of the unit's `paths` (`lazy-core.routine-types-schema.md`).
_FAILED_PATHS = "failed_paths"

# Bound on the buried-operator window scan — how many of the document's own commits between the
# item's sha and the sidecar's `last_seen_sha` cursor are examined before giving up.
# limit: a window wider than this many commits on ONE document within one watch tick loses the
# rescue; widen the cap if a real repo ever produces such a burst
_WINDOW_SCAN_CAP = 50

# Terminal markers `lazycortex-core` writes into a job bundle. A bundle carrying any of them has
# stopped running, whatever the sidecar's `coordinator_job` still claims.
_TERMINAL_MARKERS = (JobFile.DONE, JobFile.DEAD, JobFile.CANCELLED)

# A ticked option line inside any callout — the shape every operator gesture takes (the approve
# checkbox, a question option, a decision-candidate verdict). Bots never tick, by system invariant.
_TICKED_LINE_RE = re.compile(r"^>\s*-\s*\[x\]", re.IGNORECASE)

# The `review` settings key listing the addresses bots used to commit under before they were renamed or retired.
FORMER_BOT_EMAILS_KEY = "former_bot_emails"

# Error raised for a settings layer that is not valid JSON, filled with the repo's `.claude` dir and core's own report.
UNPARSEABLE_SETTINGS_TEMPLATE = "unparseable settings under {path}: {detail}"
# Stderr line for a git-watch item argument that is not valid JSON, filled with the raw argument.
MALFORMED_ITEM_TEMPLATE = "malformed git-watch item JSON: {item!r}\n"


# ----------------------------------------------------------------------------------------
class _Trigger:
  """
  Coordinator wake-trigger tokens compared as strings, in the order they are checked.

  Attributes:
    REVIEW_ENTRY: A document was just opted into review.
    JOB_DONE: The postman landed a dispatched job's payload and raised the pending wake.
    COMMAND: An open operator command stands outside code fences and foreign protected sections.
    OPERATOR_EDIT: A non-bot commit landed on an already-active document.
  """

  # A document was just opted into review.
  REVIEW_ENTRY = "review-entry"
  # The postman landed a dispatched job's payload and raised the pending wake.
  JOB_DONE = "job-done"
  # An open operator command stands outside code fences and foreign protected sections.
  COMMAND = "command"
  # A non-bot commit landed on an already-active document.
  OPERATOR_EDIT = "operator-edit"


# --------------------------------------------------------------- settings + bot-identity


def _to_repo_rel(asset_note: Path, repo: Path) -> Path:
  """
  Relativize a document path against the repository root, symlink spellings included.

  Args:
    asset_note: The document's path, absolute or already repo-relative.
    repo: Repository root the result is relative to.

  Returns:
    The repo-relative path. A caller mixing the repo's symlink alias and its real spelling
    (one side resolved, the other not) still gets the plain relative path.

  Raises:
    ValueError: The document lies outside the repository under both spellings.
  """
  # a relative note is already repo-relative
  if not asset_note.is_absolute():
    return asset_note

  # verbatim first, then the resolve retry — one side of the pair may carry the repo's
  # symlink alias while the other was resolved to the real spelling (e.g. an argparse
  # `--repo` resolved by the worker vs a `_target_file` payload written under the alias)
  try:
    return asset_note.relative_to(repo)
  except ValueError:
    return asset_note.resolve().relative_to(repo.resolve())


def load_settings(settings_root: Path) -> dict:
  """
  Read the `experts`, `routines` and `review` sections for a settings root as core sees them, overlay merged.

  Notes:
    - Core routes each section: the daemon-read sections `experts` and `routines` come from the checkout toplevel,
      and `review` from the nearest settings root `settings_root`.

  Args:
    settings_root: The nearest settings root of the document.

  Returns:
    Settings-shaped dict holding the merged `experts`, `routines` and `review` sections.

  Raises:
    RuntimeError: When a settings layer is not valid JSON, or no core CLI is resolvable.
  """

  # Decision: one reader of the merged view, core's `settings-get --scope merged` through `core_settings`,
  # replacing the module-local file reader — the local overlay is honoured and every reader sees the same values

  # the bot identities live in the same merged view core and the pump commit under; a broken
  # settings layer must fail the tick loudly (the error-ledger contract): returning `{}` here would
  # empty the bot-identity set and reclassify every system commit as an operator wake
  try:
    return _core_settings.read_merged_sections(settings_root, JobKey.EXPERTS, JobKey.ROUTINES, JobKey.REVIEW)
  except SettingsReadError as error:
    raise RuntimeError(
        UNPARSEABLE_SETTINGS_TEMPLATE.format(path = settings_root / Paths.CLAUDE_DIR, detail = error)
    ) from error


def collect_bot_emails(settings: dict) -> set[str]:
  """
  Collect every address a commit of the review system can be authored under.

  Every registered system identity counts, whatever review class a document belongs to.

  Args:
    settings: Parsed `lazy.settings.json` contents.

  Returns:
    Set of the non-empty `git_author.email` values of every registered expert and routine, every identity the
    plugin's own code commits under, and every non-empty string in the `review` section's optional
    `former_bot_emails` list.
  """

  # Domain(review.coordinator):
  # # Whose commit it is
  # The review system recognises its own commits by the author address alone. The addresses it
  # answers for are those of every registered expert and routine, plus every identity the review
  # plugin itself commits under, which always count: the review bot's own address and the
  # coordinator's shipped fallback address, used when its registered identity is incomplete.
  # A project may also list addresses that bots used before they were renamed or retired, so old
  # review commits in a document's history keep reading as the system's; with that list absent,
  # only the registered addresses and the plugin's own identities count.
  #
  # A subsystem whose address ends with a dot followed by one of these addresses counts as the
  # system's too. A commit's message never decides whose it is: a review phase trailer in the
  # message neither makes a commit the system's nor an operator's.

  emails: set[str] = set()

  # one loop over both registries, the entry shape (`git_author.email`) being identical in each; routines must be
  # included because a routine commits under its own `git_author`, and leaving it out would read its commits as
  # operator edits and wake this coordinator on every one
  for block in (JobKey.EXPERTS, JobKey.ROUTINES):
    for name, entry in settings.get(block, {}).items():
      # guard: the version sentinel and any malformed (non-dict) entry carry no email to collect
      if name == JobKey.VERSION or not isinstance(entry, dict):
        continue
      if email := (entry.get(JobKey.GIT_AUTHOR) or {}).get(JobKey.EMAIL, ""):
        emails.add(email)

  # every identity the plugin's own code commits under and the addresses bots committed under before a rename count
  # as well, so old review commits and the coordinator, finalize and submit commits never read as operator edits
  emails.update(BotIdentity.OWN_EMAILS)
  former = (settings.get(JobKey.REVIEW) or {}).get(FORMER_BOT_EMAILS_KEY) or []

  # guard: a former-address value that is not a list carries no address to collect
  if not isinstance(former, list):
    return emails

  # every non-empty string of the list is a former bot address
  emails.update(addr for addr in former if isinstance(addr, str) and addr)
  return emails


def collect_boundary_emails(settings: dict) -> set[str]:
  """
  Collect the author addresses whose commits bound the buried-edit scan window.

  A commit under one of these addresses marks a wake that already judged every older commit on the document.

  Args:
    settings: The parsed `lazy.settings.json` content.

  Returns:
    The review coordinator's own registered `git_author.email`, when its experts entry carries one, together with
    every identity the plugin's own code commits under.
  """
  # the coordinator's registered address, when its entry carries one, and every identity the plugin commits under
  entry = settings.get(JobKey.EXPERTS, {}).get(_COORDINATOR_EXPERT)
  author = entry.get(JobKey.GIT_AUTHOR) if isinstance(entry, dict) else None
  email = author.get(JobKey.EMAIL) if isinstance(author, dict) else None
  return { *BotIdentity.OWN_EMAILS, *([ email ] if isinstance(email, str) and email else []) }


def is_bot_email(email: str, bot_emails: set[str]) -> bool:
  """
  Return True when `email` is one of the given system addresses or a dotted-prefix subsystem of one.

  A dotted-prefix subsystem is a sender whose email ends with a dot followed by an address of the given set.

  Args:
    email: The commit's author email.
    bot_emails: System addresses to match against, either the system set from `collect_bot_emails` or the
      scan-boundary set from `collect_boundary_emails`.

  Returns:
    True when `email` is an address of the set or a dotted-prefix subsystem of one.
  """
  if email in bot_emails:
    return True
  return any(email.endswith(f".{bot}") for bot in bot_emails)


def _is_system_commit(item: dict, bot_emails: set[str]) -> bool:
  """
  Classify the git-watch item's own commit as system-authored or operator-authored.

  The commit's author address alone decides: it is a system commit exactly when the address is a system address,
  either exactly or as a dotted-prefix subsystem of one. The commit message is never read.

  Args:
    item: The git-watch `changed_files` item for this note.
    bot_emails: System addresses, from `collect_bot_emails`.

  Returns:
    True when the commit is system-authored, False when it is the operator's own edit.
  """
  # the author address alone decides; the commit message is never read for it
  return is_bot_email(item.get(_ITEM_AUTHOR_EMAIL, ""), bot_emails)


def _has_buried_operator_commit(repo: Path,
                                asset_note: Path,
                                item: dict,
                                *,
                                bot_emails: set[str],
                                last_seen: str | None,
                                boundary_emails: set[str]) -> bool:
  """
  Check whether an operator commit is buried between the sidecar cursor and the item's commit.

  Rescues an operator edit that a later bot commit on the same document shadowed within one
  watch window, since the git watch surfaces only the file's last-changing commit per tick.

  Args:
    repo: Repository root to walk file history in.
    asset_note: The reviewed document's path.
    item: The git-watch `changed_files` item for this note.
    bot_emails: System addresses, from `collect_bot_emails`.
    last_seen: The sidecar's `last_seen_sha` cursor, or None when no invocation stamped one.
    boundary_emails: Addresses whose commits end the scan with no finding, from `collect_boundary_emails`.

  Returns:
    True when a commit strictly inside the `(last_seen, item sha)` window is operator-authored;
    False otherwise — including when there is no cursor yet (conservative: the single-commit
    author semantics apply unchanged), when a commit under a boundary address ends the scan first,
    or when the cursor is unreachable in the file's history.
  """

  # Domain(review.coordinator):
  # # Shadowed-wake rescue for a one-commit-per-tick watch
  # A file-level change watch hands the coordinator one item per document per wake: that document's
  # most recent commit. An earlier change is therefore shadowed whenever a later system commit lands
  # on the same document inside the same watch window, and the item alone cannot reveal it.
  # Two rescues close this blind spot.
  #
  # A document that is already active, still in its opening round, and has received neither a
  # main-writer contribution nor a tracked job fires its entry wake from its current state alone,
  # since the entry transition itself may have been shadowed.
  #
  # A buried operator edit is recovered by scanning the document's history between the previous
  # wake's cursor and the current commit, newest first. Whose commit it is follows from the author
  # address alone; no commit message decides it. The first commit whose author address lies outside
  # the system set is the buried operator edit, even though the item points at a later system commit.
  #
  # A commit by the coordinator's registered address or by any identity the review plugin itself
  # commits under ends the scan without a finding, since that wake already judged everything
  # older. Any other system commit is passed
  # over, but it counts toward the commits examined.
  #
  # A commit explicitly marked as bookkeeping (the watch-skip trailer, compared case-insensitively)
  # is passed over and takes no place among the commits examined, so a long run of them cannot push
  # an operator edit out of the window.
  #
  # The scan gives up after a fixed number of commits examined, so an unusually deep window is
  # never walked in full.

  sha = item.get(_ITEM_SHA, "")

  # guard: no window to scan — no cursor, no sha, or the item IS the cursor
  if not sha or not last_seen or sha == last_seen:
    return False

  # walk the document's history from the item's commit down to the cursor, newest first
  in_window = False
  scanned = 0
  for record in _git_ops.read_history_for_file(repo, asset_note):
    # advance past everything newer than the item; its own commit is _is_system_commit's call
    if not in_window:
      in_window = record.sha == sha
      continue

    # reached the cursor — everything older was judged by an earlier invocation
    if record.sha == last_seen:
      return False

    # a commit by the coordinator or the review bot proves everything older in the window was already handled
    if is_bot_email(record.author_email, boundary_emails):
      return False

    # a `Lazy-Watch: skip` commit is automated bookkeeping, never an operator edit, whoever authored it; it takes no
    # place among the commits examined, so a long run of them cannot push an operator edit out of the window
    if Trailer.WATCH_SKIP in [ val.lower() for val in _git_ops.parse_trailer_values(record.body, Trailer.WATCH) ]:
      continue
    scanned += 1

    # guard: window implausibly deep — stop rather than walk unbounded history
    if scanned > _WINDOW_SCAN_CAP:
      return False

    # a commit under an address outside the system set inside the window is the buried operator edit
    if not is_bot_email(record.author_email, bot_emails):
      return True
  return False


def _has_fresh_tick(blob_text: str, current_text: str) -> bool:
  """
  Report whether a ticked option line appeared between the pre-commit blob and the current text.

  Args:
    blob_text: The document's text at the commit's parent revision, empty when unavailable.
    current_text: The document's current on-disk text.

  Returns:
    True when the current text carries at least one ticked `- [x]` callout line the blob did not
    (code fences stripped from both sides); False otherwise.
  """

  # Domain(review.markup):
  # # Fresh operator tick as an authorship signal
  # A ticked option line inside a callout is always an operator's own action; nothing else in
  # the review workflow ever ticks a box, by system invariant. When a ticked option appears in
  # a document's text that was not ticked in the prior revision, that transition alone proves
  # an operator touched the document — even when the surrounding revision otherwise carries a
  # system identity, since an operator's tick and a system-made change can land together
  # whenever both reach the same document in the same window. The review workflow treats this
  # transition as an operator interaction regardless of whose identity is on the surrounding
  # revision. A tick-shaped line that appears inside a code fence is inert example content and
  # never counts as a live tick.

  # collect each side's ticked lines once, so the transition is a plain set difference
  # limit: set comparison of whole lines, a second identical tick line added elsewhere is
  # invisible; per-callout block diffing if a real document ever carries duplicate tick lines
  def collect_ticked_lines(text: str) -> set[str]:
    return {
        line.rstrip()
        for line in _parser.strip_code_fences(text).splitlines()
        if _TICKED_LINE_RE.match(line)
    }

  # a tick present now and absent before the commit is the transition this probe exists to see
  return bool(collect_ticked_lines(current_text) - collect_ticked_lines(blob_text))


# -------------------------------------------------------------- coordinator-job liveness


def _coordinator_job_id(markers: dict) -> str:
  """
  Read the document's tracked coordinator job id.

  Args:
    markers: The document's runtime marker entry, as the dispatch decision read it.

  Returns:
    The tracked job id, or an empty string when no job is recorded.
  """
  raw = markers.get(JobMarker.COORDINATOR_JOB)

  # guard: a cleared (or never-written) marker records no job
  if not isinstance(raw, str):
    return ""
  return raw.strip()


def is_job_live(repo: Path, job_id: str) -> bool:
  """
  Report whether the coordinator job bundle named by `job_id` is still running.

  Args:
    repo: Repository root holding `.experts/.jobs/`.
    job_id: The job id read off the sidecar's `coordinator_job` marker.

  Returns:
    True while the bundle exists and carries no terminal marker; False once it is DONE, DEAD,
    CANCELLED, or gone from disk entirely.
  """
  jdir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / _COORDINATOR_EXPERT / job_id

  # guard: no bundle on disk — a job that left no trace is not one this document waits on
  if not jdir.is_dir():
    return False
  return not any((jdir / marker).is_file() for marker in _TERMINAL_MARKERS)


# ------------------------------------------------------------------------- pre-commit blob


def _read_blob(repo: Path, sha: str, path: str) -> str | None:
  """
  Read the file's pre-commit content — its blob at `sha`'s parent.

  Args:
    repo: Repository root to run `git` in.
    sha: The git-watch item's own commit sha.
    path: The item's repo-relative file path.

  Returns:
    The blob text, or None when there is no parent commit (the file's first-ever commit) or
    either argument is missing.
  """
  # guard: nothing to diff against without both fields
  if not sha or not path:
    return None

  # the parent revision's blob; a failed show means the file has no parent version
  result = subprocess.run(
      [ "git", "show", f"{sha}^:{path}" ],
      cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
  )
  return result.stdout if result.returncode == 0 else None


# --------------------------------------------------------------------------- trigger resolution


def _resolve_trigger(current_report: dict,
                     blob_report: dict,
                     *,
                     is_operator_edit: bool,
                     markers: dict,
                     command_open: bool) -> str | None:
  """
  Resolve which of the four wake triggers fired this tick, in check order.

  Args:
    current_report: `note_ops.build_report` of the document's current text.
    blob_report: `note_ops.build_report` of the document's pre-commit blob (an empty report
      when there was no parent commit).
    is_operator_edit: Whether the git-watch item's own commit is operator-authored.
    markers: The document's runtime marker entry, as the dispatch decision read it.
    command_open: Whether the document's current text holds an open operator command, as
      `note_ops.has_open_command` reads it.

  Returns:
    A `_Trigger` token, or None when nothing wakes the coordinator this tick.
  """

  # Domain(review.coordinator):
  # # Wake-trigger priority order
  # A coordinator wake evaluates four possible triggers in a fixed order, and the first one
  # that fires is the only one acted on this wake: a document entering review, an expert job
  # landing its result, an operator command left in the document, then any other operator
  # edit. The command trigger is checked ahead of the general operator-edit trigger on
  # purpose — a command is itself delivered by an operator commit, so checking edits first
  # would consume the wake as a plain edit and the command would never be seen.

  # waiver: 'frontmatter' is note_ops.build_report's own wire-shape key (module docstring), not a keys.py-promoted constant
  current_fm, blob_fm = current_report["frontmatter"], blob_report["frontmatter"]

  # 1. review-entry — blob has review_active absent/false, current has it true; any author
  if current_fm.get(ReviewKey.ACTIVE) is True and blob_fm.get(ReviewKey.ACTIVE) is not True:
    return _Trigger.REVIEW_ENTRY

  # 1b. review-entry, state fallback — the entry transition can be shadowed when a later bot
  # commit touches the same file inside one watch window (the item then diffs against a blob
  # that is already active). A document that is active, entry-shaped (round 1, no main writer
  # has spoken), and tracked by nothing in the sidecar has never had its entry wake — fire it
  # from state alone. The entry wake's own writer dispatch stamps `active_job`, so a handled
  # entry never re-fires here.
  if (current_fm.get(ReviewKey.ACTIVE) is True
      and current_fm.get(ReviewKey.ROUND) == 1
      # the frontmatter reader keeps the bracketed list raw, so empty is "", "[]", or absent
      and str(current_fm.get(ReviewKey.MAIN_DONE) or "").strip() in ("", "[]")
      and not markers.get(JobMarker.COORDINATOR_JOB)
      and not markers.get(JobMarker.ACTIVE_JOB)
      and not markers.get(JobMarker.PENDING_WAKE)):
    return _Trigger.REVIEW_ENTRY

  # 2. job-done — the postman raised the pending wake when it landed the payload. The commit
  # carrying that payload is this very git item, and its author is a registered bot, so the
  # sidecar flag rather than the commit's identity is what makes the wake visible here.
  if markers.get(JobMarker.PENDING_WAKE) == JobMarker.JOB_DONE:
    return _Trigger.JOB_DONE

  # 3. command — an open operator command outside code fences and foreign protected sections, as
  # `note_ops.has_open_command` reads it. Checked BEFORE operator-edit: the
  # callout is itself delivered by an operator commit, so the edit trigger would otherwise shadow
  # this one on the very wake that carries the command (found live in an end-to-end review run).
  if command_open:
    return _Trigger.COMMAND

  # 4. operator-edit — the commit's author address is outside the system set; a ticked
  # question option arrives exactly this way, and the coordinator reads the tick from the report
  if is_operator_edit:
    return _Trigger.OPERATOR_EDIT

  # none of the four triggers fired this tick
  return None


# --------------------------------------------------------------------------------- core dispatch


def core_dispatch_job(repo: Path, bundle: dict) -> dict:
  """
  Queue a new coordinator job via the `lazycortex-core dispatch-job` CLI.

  The sole inter-plugin contract this module uses (`dev.plugin-boundaries.md` § 1c) — JSON in
  via stdin, JSON out via stdout, no Python import of a sibling plugin's module.

  Args:
    repo: Repository root, exported as `LAZY_REPO_ROOT` for the CLI's own settings resolution.
    bundle: The job-bundle wire body (`expert` / `payload` / `source` / `dedup_key` / `protocols`).

  Returns:
    Parsed JSON response dict from the CLI's stdout.

  Raises:
    RuntimeError: When the CLI can't be resolved or exits non-zero, whatever bytes it printed.
    OSError: When the CLI cannot be launched.
    ValueError: When the CLI exited 0 and its stdout is not UTF-8 text or not JSON.
  """
  # the output is taken as bytes, so the exit code is read before anything the CLI printed is decoded
  env = os.environ.copy()
  env[EnvVar.LAZY_REPO_ROOT] = str(repo)
  proc = subprocess.run(
      [ sys.executable, str(_git_ops.require_core_cli(repo)), CoreCommand.DISPATCH_JOB ],
      input = json.dumps(bundle).encode("utf-8"), capture_output = True, env = env, check = False,
  )

  # guard: the CLI call itself failed, whatever bytes it printed — surface stdout/stderr for diagnosis
  if proc.returncode != 0:
    raise RuntimeError(
        f"lazycortex-core {CoreCommand.DISPATCH_JOB} exit={proc.returncode} "
        f"stdout={proc.stdout.decode('utf-8', errors = 'replace')!r} "
        f"stderr={proc.stderr.decode('utf-8', errors = 'replace')!r}"
    )

  # the CLI reported success; an answer that is not UTF-8 text or not JSON is refused as a value error
  return json.loads(proc.stdout.decode("utf-8"))


# ------------------------------------------------------------------------------------- worker


def dispatch_coordinator(repo: Path, asset_note: Path, item: dict) -> dict:
  """
  Dispatch a coordinator job for one document when its wake trigger fires.

  Guarantees:
    - At most one coordinator job runs per document: a `coordinator_job` marker naming a bundle
      that is still running blocks a new dispatch, while one naming a finished, dead, cancelled,
      or vanished bundle is cleared before the trigger is resolved.
    - The decision NEVER reads a failed lookup as "no job is running": when the marker store exists but cannot be
      read, or reads but is no store (not UTF-8 text, not valid JSON, not a JSON object), the wake is refused before
      anything is queued; the `OSError` propagates, the core dispatch is not called and nothing is written.

  Notes:
    - Stamps the item's commit sha as the document's `last_seen_sha` cursor on every call,
      dispatched or not, so the next invocation's buried-operator rescue has an accurate cursor;
      when the marker store cannot be read or is no store, nothing is stamped or written.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    item: The git-watch `changed_files` item that woke this tick (`path`, `status`, `sha`,
      `author_name`, `author_email`).

  Returns:
    `{"action": "noop"}` when nothing wakes the coordinator or a live job is already tracked; or
    `{"action": "dispatched", "trigger", "job_id"}` on a fresh dispatch.

  Raises:
    RuntimeError: When a settings layer is not valid JSON, or when the `lazycortex-core` CLI
      cannot be resolved or its dispatch call exits non-zero.
    OSError: When the marker store exists but cannot be read or reads but is no store, the `lazycortex-core` CLI
      cannot be launched, or a marker write fails.
    ValueError: When the queue call's answer cannot be read.
  """

  # Contract:
  # At most one coordinator job runs per document: a `coordinator_job` marker naming a bundle
  # that is still running blocks a new dispatch, while one naming a finished, dead, cancelled,
  # or vanished bundle is cleared before the trigger is resolved. The decision NEVER reads a failed lookup as
  # "no job is running": when the marker store exists but cannot be read, or reads but is no store (not UTF-8 text,
  # not valid JSON, not a JSON object), the wake is refused before anything is queued; the `OSError` propagates, the
  # core dispatch is not called and nothing is written.

  result = _resolve_and_dispatch(repo, asset_note, item)

  # stamp the cursor last, so this invocation's own window scan used the previous value
  if sha := item.get(_ITEM_SHA, ""):
    _job_markers.update(repo, asset_note, { JobMarker.LAST_SEEN_SHA: sha })
  return result


def _resolve_and_dispatch(repo: Path, asset_note: Path, item: dict) -> dict:
  """
  Dispatch a coordinator job for one document's git-watch item when its wake trigger fires.

  Notes:
    - A `coordinator_job` marker naming a still-running bundle blocks a new dispatch; one naming a
      finished, dead, cancelled, or vanished bundle is cleared before the trigger is resolved.
    - Clearing a stale job marker and stamping a fresh dispatch never touch the document itself,
      so neither action costs a commit.
    - A marker store that exists but cannot be read, or reads but is no store, refuses the wake before anything is
      queued or cleared.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    item: The git-watch `changed_files` item that woke this tick (`path`, `status`, `sha`,
      `author_name`, `author_email`).

  Returns:
    `{"action": "noop"}` when nothing wakes the coordinator or a live job is already tracked; or
    `{"action": "dispatched", "trigger", "job_id"}` on a fresh dispatch.

  Raises:
    RuntimeError: When a settings layer is not valid JSON, or when the `lazycortex-core` CLI
      cannot be resolved or its dispatch call exits non-zero.
    OSError: When the marker store exists but cannot be read or reads but is no store, the `lazycortex-core` CLI
      cannot be launched, or a marker write fails.
    ValueError: When the queue call's answer cannot be read.
  """

  # the decision reads the markers through the checked reader: a sidecar that cannot be read refuses the wake
  # here, before anything is queued, instead of reading as "no job running"
  markers = _job_markers.read_checked(repo, asset_note)

  # one active coordinator job per document — but only while that job is genuinely live. A marker
  # left behind by a job that finished, died, or was cancelled is cleared here and this same
  # invocation falls through to trigger resolution, so a dead job can never brick the document.
  tracked_job = _coordinator_job_id(markers)
  if tracked_job:
    # a still-running bundle keeps its turn — the turn belongs to it and no trigger is read
    if is_job_live(repo, tracked_job):
      return { "action": "noop" }
    markers = _job_markers.update(repo, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # the document's current text and its structural report, the state every trigger is judged on
  current_text = asset_note.read_text(encoding = "utf-8")
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  current_report = _note_ops.build_report(current_text, markers)  # type: ignore[attr-defined]

  # guard: the document is not under review and nothing is waiting to land on it — no trigger
  # can legitimately fire, so the wake ends here before any settings read or blob fetch
  if not _is_under_review(current_report, markers):
    return { "action": "noop" }

  # the document as it stood before the woken commit, for the fresh-tick comparison
  blob_text = _read_blob(repo, item.get(_ITEM_SHA, ""), item.get(_ITEM_PATH, ""))

  # a fresh tick is an operator gesture whoever committed it — bots never tick, so a tick
  # transition overrides the author-based suppression exactly like a review_result transition;
  # an operator commit buried under a later bot commit in the same watch window is rescued by
  # the cursor-bounded window scan
  settings = load_settings(_core_settings.query_settings_root_for(asset_note))
  bot_emails = collect_bot_emails(settings)
  is_operator_edit = (
      not _is_system_commit(item, bot_emails)
      or _has_fresh_tick(blob_text or "", current_text)
      or _has_buried_operator_commit(
          repo, asset_note, item, bot_emails = bot_emails, last_seen = markers.get(JobMarker.LAST_SEEN_SHA),
          boundary_emails = collect_boundary_emails(settings),
      )
  )

  # the pre-commit blob's report, against which the review-entry transition is judged
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  blob_report = _note_ops.build_report(blob_text or "")  # type: ignore[attr-defined]

  # check the four triggers in order; the first that fires wins. An open command is read the way `strip-command`
  # reads it, so a command the coordinator cannot remove never wakes it
  trigger = _resolve_trigger(
      current_report, blob_report, is_operator_edit = is_operator_edit, markers = markers,
      # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
      # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
      command_open = _note_ops.has_open_command(current_text),  # type: ignore[attr-defined]
  )

  # nothing wakes the coordinator this tick
  if trigger is None:
    return { "action": "noop" }

  # dispatch through the shared tail so the direct job-done path and this git path stay one shape
  dedup_key = f"{item.get(_ITEM_PATH, asset_note.name)}:{item.get(_ITEM_SHA, '')}"
  return _dispatch(repo, asset_note, trigger, dedup_key)


def _is_under_review(current_report: dict, markers: dict) -> bool:
  """
  Decide whether a document is the coordinator's business at all this wake.

  Args:
    current_report: The document's structural report, as `note_ops.build_report` returns it.
    markers: The document's runtime marker entry, as the dispatch decision read it.

  Returns:
    True when the document carries an active review, or when a landed expert payload is
    waiting to be picked up; False otherwise.
  """

  # Domain(review.coordinator):
  # # A wake belongs to a document that is actually in review
  # The coordinator watches a whole tree of documents and is woken by commits touching any of
  # them, so the first question of every wake is whether this document is in review at all. A
  # document that is not, and has no expert result waiting to land on it, has no move the
  # coordinator could make — every one of its wake triggers presupposes an open review. Asking
  # the question here rather than trusting the watch to have asked it is what keeps the cost of
  # a mistake in the watch's configuration bounded: the wake ends in one cheap read instead of
  # becoming a full coordinator turn for every document an operator happens to edit.

  # an expert payload landed by the postman is picked up even as the review closes around it
  # waiver: 'frontmatter' is note_ops.build_report's own wire-shape key (module docstring), not a keys.py-promoted constant
  return (current_report.get("frontmatter") or {}).get(ReviewKey.ACTIVE) is True or bool(
      markers.get(JobMarker.PENDING_WAKE))


def _dispatch(repo: Path, asset_note: Path, trigger: str, dedup_key: str) -> dict:
  """
  Queue one coordinator job for `asset_note` and stamp the runtime marker.

  Notes:
    - Stamps the `coordinator_job` marker with the queued job; for a `job-done` trigger the same write consumes the
      pending wake, so one landed payload wakes one coordinator job.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    trigger: The `_Trigger` token this wake carries.
    dedup_key: Caller-built dedup key for the core queue.

  Returns:
    `{"action": "dispatched", "trigger", "job_id"}`.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or its dispatch call exits non-zero; a pending
      `job-done` wake is then left raised.
    OSError: When the `lazycortex-core` CLI cannot be launched, or the marker cannot be written once the job is
      queued; a pending `job-done` wake is then left raised.
    ValueError: When the queue call's answer cannot be read; a pending `job-done` wake is then left raised.
  """
  # assemble and queue the coordinator job's wire bundle
  bundle = {
      JobKey.EXPERT: _COORDINATOR_EXPERT,
      JobKey.PAYLOAD: { JobKey.TARGET_FILE: str(asset_note), "trigger": trigger },
      # the pump copies the note at claim, so the bundle names it rather than snapshotting it
      JobKey.SOURCE: [ { JobKey.PATH: str(_to_repo_rel(asset_note, repo)) } ],
      JobKey.DEDUP_KEY: dedup_key,
      # the routine's own attached protocol, folded into the job's config.json on top of whatever the daemon
      # already unions in from the routine registration (`dev.plugin-boundaries.md` § 1c)
      JobKey.PROTOCOLS: [ ReviewProtocol.COORDINATION_PLAYBOOK ],
  }
  job_id = str(core_dispatch_job(repo, bundle).get(JobKey.JOB_ID, ""))

  # stamp the dedup marker in runtime state — no document write, so no commit and nothing an
  # operator editing the document can break; the same write consumes the pending wake, so the same
  # landed payload cannot wake a second coordinator job. A wake the entry trigger preempted keeps its
  # flag and fires on a later tick instead.
  changes: dict[str, str | None] = { JobMarker.COORDINATOR_JOB: job_id }
  if trigger == _Trigger.JOB_DONE:
    changes[JobMarker.PENDING_WAKE] = None
  _job_markers.update(repo, asset_note, changes)
  return { "action": "dispatched", "trigger": trigger, "job_id": job_id }


def dispatch_job_done(repo: Path, asset_note: Path, dedup_hint: str) -> dict:
  """
  Dispatch a `job-done` coordinator wake directly, without a git item.

  The postman calls this the moment a writer's job goes DONE: no payload commit is made
  any more, so no git-watch item can carry the wake — the postman raises the sidecar flag
  and queues the coordinator itself. The coordinator lands the payload with `collect-job`
  inside its own wake and commits once.

  Guarantees:
    - At most one coordinator job runs per document across both dispatch paths: a live
      tracked job blocks a new dispatch, and a terminal or vanished one is cleared before
      this call queues its own job.
    - The decision NEVER reads a failed lookup as "no job is running": when the marker store exists but cannot be
      read, or reads but is no store (not UTF-8 text, not valid JSON, not a JSON object), the wake is refused before
      anything is queued; the `OSError` propagates, the core dispatch is not called and nothing is written.
    - The pending wake is consumed only once the coordinator job is queued: when the queue call raises, the wake
      is still raised, so a later tick dispatches it.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    dedup_hint: Stable token for the core queue's dedup key (e.g. the DONE job ids).

  Returns:
    `{"action": "noop"}` when a live coordinator job already owns the document, or
    `{"action": "dispatched", "trigger", "job_id"}` on a fresh dispatch.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or its dispatch call
      exits non-zero — the caller's sweep boundary decides what a failed dispatch means.
    OSError: When the marker store exists but cannot be read or reads but is no store (nothing is queued), the
      `lazycortex-core` CLI cannot be launched, or the marker cannot be written once the job is queued.
    ValueError: When the queue call's answer is not JSON.
  """

  # Contract:
  # At most one coordinator job runs per document across both dispatch paths: a
  # `coordinator_job` marker naming a bundle that is still running blocks a new dispatch,
  # while one naming a finished, dead, cancelled, or vanished bundle is cleared before this
  # call queues its own job. The decision NEVER reads a failed lookup as "no job is running": when the marker store
  # exists but cannot be read, or reads but is no store (not UTF-8 text, not valid JSON, not a JSON object), the wake
  # is refused before anything is queued; the `OSError` propagates, the core dispatch is not called and nothing is
  # written.

  # same one-live-job mutex as the git path: a running bundle keeps the turn, a terminal
  # one is cleared and this same call goes on to dispatch; a sidecar that cannot be read refuses the wake
  # here, before anything is queued
  tracked_job = _coordinator_job_id(_job_markers.read_checked(repo, asset_note))
  if tracked_job:
    # a still-running bundle keeps its turn — the pending wake stays raised for a later tick
    if is_job_live(repo, tracked_job):
      return { "action": "noop" }
    _job_markers.update(repo, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # dedup on the DONE job set so a retry of the same landing folds into one queued job
  dedup_key = f"{_to_repo_rel(asset_note, repo)}:{_Trigger.JOB_DONE}:{dedup_hint}"

  # Contract:
  # The pending wake is consumed only once the coordinator job is queued: when the queue call raises, the
  # wake MUST still be raised, so a later tick dispatches it.

  # queue the coordinator job; only a queued job consumes the wake
  return _dispatch(repo, asset_note, _Trigger.JOB_DONE, dedup_key)


def _dispatch_path(repo: Path, raw_path: str, item: dict) -> dict:
  """
  Run the coordinator tick for one changed document named by a repo-relative path.

  Args:
    repo: Repository root the daemon spawned this worker in.
    raw_path: The document's repo-relative path, as the git-watch item carries it.
    item: The file-level git-watch item for that document (`path`, `sha`, `author_*`).

  Returns:
    `{"action": "noop"}` when the document is gone from disk or nothing wakes the coordinator;
    `{"action": "dispatched", "trigger", "job_id"}` on a fresh dispatch.

  Raises:
    RuntimeError: When a settings layer is not valid JSON, or when the `lazycortex-core` CLI
      cannot be resolved or its dispatch call exits non-zero.
    OSError: When the marker store exists but cannot be read or reads but is no store, the `lazycortex-core` CLI
      cannot be launched, or a marker write fails.
    ValueError: When the queue call's answer cannot be read.
  """
  asset_note = (repo / raw_path).resolve()

  # guard: the note was deleted or moved between the git-watch scan and this dispatch
  if not asset_note.is_file():
    return { "action": "noop" }
  return dispatch_coordinator(repo, asset_note, item)


def _rekey_path_item(repo: Path, item: dict, raw_path: str) -> dict:
  """
  Derive the file-level item for one member path of a grouped git-watch unit.

  Notes:
    - Spawns one `git log` subprocess in `repo` per call.

  Args:
    repo: Repository root to walk the document's history in.
    item: The grouped unit (`dir`, `paths`, `sha`, `author_name`, `author_email`).
    raw_path: The member path to build the file-level item for; taken literally, never as a pattern.

  Returns:
    A copy of `item` without `paths` / `dir`, carrying `path = raw_path` and the document's own
    last commit — at or before the unit's `sha` — as `sha` / `author_name` / `author_email`; the
    unit's range-level commit is kept when the document has no history at all, or when the
    unit's `sha` is unknown to git (a rewritten tip).
  """

  # Domain(review.coordinator):
  # # Each document of a batch is judged by its own last commit
  # A batch of changed documents arrives attributed to one commit, the last of the scanned range,
  # and that commit may not have touched a given document at all. Every judgement the coordinator
  # makes about a document — whether the change was an operator's, what the text looked like
  # before it, whether an operator edit lies buried under later system commits — reads the commit
  # that last changed that document, so each member of the batch is re-attributed to its own last
  # commit before it is judged. The lookup never reaches past the batch's own commit, so a batch
  # retried later still judges the state it was raised for and not a newer one.

  # the file-level shape: the unit's fields minus the batch keys, plus this member's path
  per_path = { key: value for key, value in item.items() if key not in (_ITEM_PATHS, _ITEM_DIR) }
  per_path[_ITEM_PATH] = raw_path

  # the document's own last commit, bounded at the unit's range tip when the unit carries one; the member
  # path is taken literally, so a name carrying glob characters never borrows a sibling's commit
  tip = item.get(_ITEM_SHA)
  head = subprocess.run(
      [ "git", "log", "-1", "--format=%H%x00%an%x00%ae", *([ tip ] if isinstance(tip, str) and tip else []),
        "--", f"{_LITERAL_PATHSPEC}{raw_path}" ],
      cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
  )

  # guard: no commit to key off — the range-level fields stay rather than losing the tick
  if head.returncode != 0 or not head.stdout.strip():
    return per_path
  own_sha, name, email = head.stdout.strip().split("\x00", 2)
  return { **per_path, _ITEM_SHA: own_sha, _ITEM_AUTHOR_NAME: name, _ITEM_AUTHOR_EMAIL: email }


def _dispatch_grouped(repo: Path, item: dict, paths: list) -> int:
  """
  Fan a grouped git-watch unit out per path, reporting the paths whose dispatch raised.

  Notes:
    - Prints one JSON result line per handled path to stdout, in member order.
    - Writes one diagnostic line per failed path to stderr; a member that is not a non-empty
      string is skipped with a stderr line and is neither dispatched nor reported for retry.

  Args:
    repo: Repository root the daemon spawned this worker in.
    item: The grouped unit (`dir`, `paths`, `sha`, `author_name`, `author_email`).
    paths: The unit's member paths, iterated in order.

  Returns:
    Exit code: 0 when every path was handled; 1 when at least one raised, after printing
    `{"failed_paths": [...]}` naming those paths as the last stdout line.
  """
  failed: list[str] = []
  for raw_path in paths:
    # guard: a member that is not a usable path — nothing to dispatch on and nothing to retry
    if not isinstance(raw_path, str) or not raw_path:
      sys.stderr.write(f"grouped git-watch item carries an unusable path: {raw_path!r}\n")
      continue
    try:
      print(json.dumps(_dispatch_path(repo, raw_path, _rekey_path_item(repo, item, raw_path))))
    # waiver: this unit's per-path error boundary — one broken document must not hide the others' results
    except Exception as error:
      sys.stderr.write(f"coordinator-dispatch: {raw_path}: {error}\n")
      failed.append(raw_path)

  # every path handled — a clean exit retries nothing
  if not failed:
    return 0

  # the LAST stdout line narrows the daemon's retry to the paths that actually failed
  print(json.dumps({ _FAILED_PATHS: failed }))
  return 1


def main(argv: list[str]) -> int:
  """
  Run one coordinator-dispatch tick from the command line, printing the result as JSON.

  Invoked by the `lazy-review.coordinator-watch` git-watch routine as `coordinator-dispatch
  <item-json> [--repo <dir>]`, spawned with `cwd = repo`; the tick works in the root of the checkout it is
  spawned in. The item is either the grouped unit the routine's default `group: "all"` produces
  (`dir`, `paths`, `sha`, `author_*`) — one worker call per tick carrying every changed document,
  printed as one JSON line per path — or a single file-level item (`path`, `status`, `sha`,
  `author_*`), printed as one line. The routine's own `filter.frontmatter` clause restricts
  matches to documents with `review_active: true`; a watch registered without the clause still
  works and costs one cheap read per document instead of a coordinator turn.

  Guarantees:
    - For a grouped unit in which at least one member path's dispatch raised, the last stdout line
      is a JSON object whose `failed_paths` names exactly the failed member paths, and the exit
      code is 1.

  Notes:
    - Writes a diagnostic line to stderr for malformed input and for every path whose dispatch
      raised.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the current directory), and the checkout that directory sits in is the one
      worked in.

  Returns:
    Exit code: 0 on success; 1 when a grouped unit had at least one path whose dispatch raised, including a wake
    refused for a marker store that cannot be read or is no store (the last stdout line is then
    `{"failed_paths": [...]}`); 2 when the item JSON is malformed or carries neither a usable `path` nor a non-empty
    `paths` list. A single file-level item whose dispatch raises is not caught: the exception escapes and the
    process exits non-zero.
  """

  # Contract:
  # For a grouped unit in which at least one member path's dispatch raised, the LAST stdout
  # line MUST be a JSON object whose `failed_paths` names exactly the failed member paths,
  # and the exit code MUST be 1; the daemon narrows its retry to those paths.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-review coordinator-dispatch")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("item_json")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = None)
  args = parser.parse_args(argv)

  # guard: a git-watch item that is not valid JSON names nothing to dispatch
  try:
    item = json.loads(args.item_json)
  except json.JSONDecodeError:
    sys.stderr.write(MALFORMED_ITEM_TEMPLATE.format(item = args.item_json))
    return 2

  # a relative item path resolves against the checkout root of --repo, else of $LAZY_REPO_ROOT, else of the cwd
  repo = _review_locator.query_repo_root(args.repo)

  # a member list marks the grouped unit; a lone `path` marks the file-level item
  paths = item.get(_ITEM_PATHS) if isinstance(item, dict) else None

  # the grouped unit (`group: "all"` / `"dir"` / globs) fans out per member path in one tick
  if isinstance(paths, list) and paths:
    return _dispatch_grouped(repo, item, paths)

  # the single file-level item names its one document under `path`
  raw_path = item.get(_ITEM_PATH) if isinstance(item, dict) else None

  # guard: not the shape a `changed_files` item takes — nothing to dispatch on
  if not isinstance(raw_path, str) or not raw_path:
    sys.stderr.write(f"git-watch item carries no {_ITEM_PATH!r}: {item!r}\n")
    return 2

  # run the tick and report its result as one JSON line on stdout
  print(json.dumps(_dispatch_path(repo, raw_path, item)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
