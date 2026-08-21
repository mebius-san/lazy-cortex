"""Coordinator wake-trigger worker for the `lazy-review.coordinator-watch` git-watch routine.

Invoked once per changed markdown file under review, via a `type: git`, `watch: changed_files`
routine (`lazycortex-core`'s own file-level git-watch) rather than a periodic directory scan. The
daemon resolves each item to a `(path, status, sha, author_name, author_email)` dict and passes it
as one JSON argv. Four wake triggers are checked in order — `review-entry` (a document just opted
into review), `job-done` (the postman raised a `pending_wake` after landing a payload),
`command` (a non-empty `[!todo] #review/command` callout), `operator-edit` (a non-bot commit) —
and the first that fires dispatches one `review.coordinator` expert job via the
`lazycortex-core dispatch-job` CLI (the § 1c plugin-boundary contract). A ticked question option
is not a trigger of its own: the tick normally arrives in an operator commit, wakes
`operator-edit`, and the coordinator reads it out of the document's own report. A tick that a
BOT commit carried in still wakes `operator-edit` — a tick is an operator gesture by system
invariant (bots never tick), so a fresh `- [x]` appearing between the pre-commit blob and the
current text fires the trigger regardless of the commit's author (the same per-transition
author exemption the specs coordinator's `job-done` / `doc-transition` triggers already carry).

Both markers this worker reads live in `job_markers.py`'s gitignored runtime sidecar rather than
in the document, so neither writing nor clearing one costs a commit and neither is reachable by an
operator's hand-edit. The `coordinator_job` marker enforces one active coordinator job per
document: naming a bundle that is still running is a silent skip, checked before any trigger, while
naming a finished, dead, cancelled, or vanished bundle clears the marker and the same invocation
carries on to trigger resolution.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops as _note_ops  # type: ignore # noqa: E402
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import parser as _parser  # noqa: E402
# waiver: `claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
# `import note_ops` above resolves to that unrelated module instead (this dir's `__init__.py` makes review's
# own copy package-qualified as `bin.note_ops`), so mypy checks the attribute against the wrong file's shape
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import (  # noqa: E402
    CoreCommand, EnvVar, JobFile, JobKey, JobMarker, Paths, Plugin, ReviewKey, Tag, Trailer,
)


# The fixed expert this worker ever dispatches — one persona for every document, never resolved
# from a review class (unlike the per-document main-writer resolution the review loop itself does).
_COORDINATOR_EXPERT = "review.coordinator"

# The routine's own attached protocol, folded into every dispatched job's config.json on top of
# whatever the daemon already unions in from the routine registration (`dev.plugin-boundaries.md`
# § 1c) — see `lazy-review.coordination-playbook.md` (Task 9).
_COORDINATION_PLAYBOOK_PROTOCOL = "lazycortex-review:lazy-review.coordination-playbook"

# `[!todo] #review/command` callout detection — trigger 4 (`lazy-review.coordination-playbook.md` §
# 5's "Coordinator commands" contract, ported narrowly from `lazy-spec.coordination-playbook.md`'s
# analogous `# Coordinator commands` section).
_COMMAND_MARKER = "todo"
_COMMAND_TAG = f"{Tag.REVIEW_PREFIX}command"

# Wire keys on a `changed_files` git-watch item (`lazycortex-core`'s `routine_types._compute_git_items`).
_ITEM_PATH = "path"
_ITEM_SHA = "sha"
_ITEM_AUTHOR_EMAIL = "author_email"

# Terminal markers `lazycortex-core` writes into a job bundle. A bundle carrying any of them has
# stopped running, whatever the sidecar's `coordinator_job` still claims.
_TERMINAL_MARKERS = (JobFile.DONE, JobFile.DEAD, JobFile.CANCELLED)


# ----------------------------------------------------------------------------------------
class _Trigger:
  """
  Coordinator wake-trigger tokens compared as strings, in the order they are checked.

  Attributes:
    REVIEW_ENTRY: A document was just opted into review.
    JOB_DONE: The postman landed a dispatched job's payload and raised the pending wake.
    OPERATOR_EDIT: A non-bot commit landed on an already-active document.
    COMMAND: A non-empty `[!todo] #review/command` callout is present.
  """

  REVIEW_ENTRY = "review-entry"
  JOB_DONE = "job-done"
  OPERATOR_EDIT = "operator-edit"
  COMMAND = "command"


# --------------------------------------------------------------- settings + bot-identity


def _rel_to_repo(asset_note: Path, repo: Path) -> Path:
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
  # guard: a relative note is already repo-relative
  if not asset_note.is_absolute():
    return asset_note

  # verbatim first, then the resolve retry — one side of the pair may carry the repo's
  # symlink alias while the other was resolved to the real spelling (e.g. an argparse
  # `--repo` resolved by the worker vs a `_target_file` payload written under the alias)
  try:
    return asset_note.relative_to(repo)
  except ValueError:
    return asset_note.resolve().relative_to(repo.resolve())


def _load_settings(repo: Path) -> dict:
  """
  Read `<repo>/.claude/lazy.settings.json`.

  Ported from `dispatcher.py`'s own `load_settings` (that module is being retired — see
  `collect_ops.py`'s module docstring) rather than imported, per the coordinator migration's
  own-verbs-only boundary.

  Args:
    repo: Repository root to resolve the settings path against.

  Returns:
    Parsed settings dict, or `{}` when the file is absent.

  Raises:
    RuntimeError: When the file exists but is not valid JSON.
  """
  path = repo / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE
  # guard: no settings file at all — nothing registered
  if not path.exists():
    return {}
  try:
    return json.loads(path.read_text())
  except json.JSONDecodeError as err:
    # a broken settings file must fail the tick loudly (the error-ledger contract): returning `{}`
    # here would empty the bot-identity set and reclassify every system commit as an operator wake
    raise RuntimeError(f"unparseable settings file: {path}") from err


def _bot_emails(settings: dict) -> set[str]:
  """
  Collect every registered expert's `git_author.email` from the whole experts table.

  Unlike `dispatcher.py`'s `_participating_bot_emails` (scoped to one review class's writer
  groups), this worker has no class context for a bare git-watch item — every registered
  expert counts as a system identity here.

  Args:
    settings: Parsed `lazy.settings.json` contents.

  Returns:
    Set of non-empty `git_author.email` values across every registered expert.
  """
  emails: set[str] = set()
  for name, entry in settings.get(JobKey.EXPERTS, {}).items():
    # guard: the version sentinel and any malformed (non-dict) entry carry no email to collect
    if name == JobKey.VERSION or not isinstance(entry, dict):
      continue
    email = (entry.get(JobKey.GIT_AUTHOR) or {}).get(JobKey.EMAIL, "")
    if email:
      emails.add(email)
  return emails


def _email_is_bot(email: str, bot_emails: set[str]) -> bool:
  """
  Return True when `email` belongs to a registered bot or a dotted-prefix subsystem it owns.

  Ported verbatim from `dispatcher.py:497-511`.

  Args:
    email: The commit's author email.
    bot_emails: Registered `git_author.email` values, from `_bot_emails`.

  Returns:
    True when `email` identifies a bot or a bot-owned subsystem.
  """
  if email in bot_emails:
    return True
  return any(email.endswith(f".{bot}") for bot in bot_emails)


def _is_system_commit(repo: Path, asset_note: Path, item: dict, bot_emails: set[str]) -> bool:
  """
  Classify the git-watch item's own commit as bot-authored or operator-authored.

  Mirrors `dispatcher.py`'s `_chain_state` author-identity fallback: a commit carrying a
  `Doc-Review-Phase` trailer was written by a bot regardless of its author email; a trailerless
  commit is bot-authored only when its email matches (exactly, or as a dotted-prefix subsystem
  of) a registered expert's `git_author.email`.

  Args:
    repo: Repository root to walk file history in.
    asset_note: The reviewed document's path.
    item: The git-watch `changed_files` item for this note.
    bot_emails: Registered `git_author.email` values, from `_bot_emails`.

  Returns:
    True when the commit is bot-authored, False when it is the operator's own edit.
  """
  sha = item.get(_ITEM_SHA, "")
  for record in _git_ops.history_for_file(repo, asset_note):
    if record.sha == sha:
      # a `Doc-Review-Phase` trailer alone proves a bot wrote this commit, regardless of email
      if Trailer.PHASE in record.trailers:
        return True
      break
  return _email_is_bot(item.get(_ITEM_AUTHOR_EMAIL, ""), bot_emails)


# A ticked option line inside any callout — the shape every operator gesture takes (the approve
# checkbox, a question option, a decision-candidate verdict). Bots never tick, by system invariant.
_TICKED_LINE_RE = re.compile(r"^>\s*-\s*\[x\]", re.IGNORECASE)


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
  def ticked_lines(text: str) -> set[str]:
    return {
        line.rstrip()
        for line in _parser.strip_code_fences(text).splitlines()
        if _TICKED_LINE_RE.match(line)
    }

  # a tick present now and absent before the commit is the transition this probe exists to see
  return bool(ticked_lines(current_text) - ticked_lines(blob_text))


# -------------------------------------------------------------- coordinator-job liveness


def _coordinator_job_id(markers: dict) -> str:
  """
  Read the document's tracked coordinator job id.

  Args:
    markers: The document's runtime marker entry, from `job_markers.read`.

  Returns:
    The tracked job id, or an empty string when no job is recorded.
  """
  raw = markers.get(JobMarker.COORDINATOR_JOB)
  # guard: a cleared (or never-written) marker records no job
  if not isinstance(raw, str):
    return ""
  return raw.strip()


def _is_job_live(repo: Path, job_id: str) -> bool:
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
  result = subprocess.run(
      ["git", "show", f"{sha}^:{path}"],
      cwd = str(repo), capture_output = True, text = True, check = False,
  )
  return result.stdout if result.returncode == 0 else None


# --------------------------------------------------------------------------- trigger resolution


def _resolve_trigger(current_report: dict, blob_report: dict, is_operator_edit: bool, markers: dict) -> str | None:
  """
  Resolve which of the four wake triggers fired this tick, in check order.

  Args:
    current_report: `note_ops.build_report` of the document's current text.
    blob_report: `note_ops.build_report` of the document's pre-commit blob (an empty report
      when there was no parent commit).
    is_operator_edit: Whether the git-watch item's own commit is operator-authored.
    markers: The document's runtime marker entry, from `job_markers.read`.

  Returns:
    A `_Trigger` token, or None when nothing wakes the coordinator this tick.
  """
  # waiver: 'frontmatter' is note_ops.build_report's own wire-shape key (module docstring), not a keys.py-promoted constant
  current_fm, blob_fm = current_report["frontmatter"], blob_report["frontmatter"]

  # 1. review-entry — blob has review_active absent/false, current has it true; any author
  if current_fm.get(ReviewKey.ACTIVE) is True and blob_fm.get(ReviewKey.ACTIVE) is not True:
    return _Trigger.REVIEW_ENTRY

  # 2. job-done — the postman raised the pending wake when it landed the payload. The commit
  # carrying that payload is this very git item, and its author is a registered bot, so the
  # sidecar flag rather than the commit's identity is what makes the wake visible here.
  if markers.get(JobMarker.PENDING_WAKE) == JobMarker.JOB_DONE:
    return _Trigger.JOB_DONE

  # 3. command — a non-empty [!todo] #review/command callout. Checked BEFORE operator-edit: the
  # callout is itself delivered by an operator commit, so the edit trigger would otherwise shadow
  # this one on the very wake that carries the command (found live in an end-to-end review run).
  # waiver: 'callouts'/'type'/'tag'/'body' are note_ops.build_report's own wire-shape keys, not keys.py-promoted constants
  for callout in current_report["callouts"]:
    if callout["type"] == _COMMAND_MARKER and callout["tag"] == _COMMAND_TAG and callout["body"].strip():
      return _Trigger.COMMAND

  # 4. operator-edit — the commit itself is not a registered bot / trailered writer; a ticked
  # question option arrives exactly this way, and the coordinator reads the tick from the report
  if is_operator_edit:
    return _Trigger.OPERATOR_EDIT

  # guard: none of the four triggers fired this tick
  return None


# --------------------------------------------------------------------------------- core dispatch


def _resolve_core_cli() -> Path | None:
  """
  Find the `lazycortex-core` CLI binary.

  Mirrors `collect_ops.py`'s own copy of this lookup (`dev.plugin-boundaries.md` § 1c) — each
  bin/ worker resolves it independently rather than importing a sibling plugin's Python.

  Returns:
    Absolute path to the resolved binary, preferring `$LAZYCORTEX_PLUGIN_DIRS` over the plugin
    cache, or None when neither lookup finds one.
  """
  dirs = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep)
  for d in dirs:
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not d:
      continue
    cli = Path(d) / Paths.BIN_DIR / Plugin.CORE
    if cli.is_file():
      return cli
  cache = Path.home() / Paths.PLUGIN_CACHE
  # guard: no plugin cache on this machine — nothing further to try
  if not cache.is_dir():
    return None
  plugin_dirs = [
      registry / Plugin.CORE
      for registry in cache.iterdir()
      if registry.is_dir() and (registry / Plugin.CORE).is_dir()
  ]
  all_versions = [v for pd in plugin_dirs for v in pd.iterdir() if v.is_dir()]
  # guard: no installed version found — nothing further to try
  if not all_versions:
    return None
  latest = sorted(all_versions, key = lambda v: v.name, reverse = True)[0]
  cli = latest / Paths.BIN_DIR / Plugin.CORE
  return cli if cli.is_file() else None


def _core_dispatch_job(repo: Path, bundle: dict) -> dict:
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
    RuntimeError: When the CLI can't be resolved or exits non-zero.
  """
  cli = _resolve_core_cli()
  # guard: neither lookup stage found a binary
  if cli is None:
    raise RuntimeError(
        "lazycortex-core CLI not resolvable: $LAZYCORTEX_PLUGIN_DIRS yields no match and the "
        "plugin cache has no lazycortex-core version with a bin/lazycortex-core entry."
    )
  env = os.environ.copy()
  env[EnvVar.LAZY_REPO_ROOT] = str(repo)
  proc = subprocess.run(
      [str(cli), CoreCommand.DISPATCH_JOB],
      input = json.dumps(bundle), capture_output = True, text = True, env = env, check = False,
  )
  # guard: the CLI call itself failed — surface stdout/stderr for diagnosis
  if proc.returncode != 0:
    raise RuntimeError(
        f"lazycortex-core {CoreCommand.DISPATCH_JOB} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return json.loads(proc.stdout)


# ------------------------------------------------------------------------------------- worker


def coordinator_dispatch(repo: Path, asset_note: Path, item: dict) -> dict:
  """
  Detect a coordinator wake trigger on one document and dispatch a job when one fires.

  At most one coordinator job runs per document, and only a live one counts: a `coordinator_job`
  marker naming a bundle that is still running is a silent skip, checked before any of the four
  triggers, while a marker naming a finished, dead, cancelled, or vanished bundle is cleared in
  the sidecar and this same call goes on to resolve the trigger. Neither the clear nor the
  dispatch stamp touches the document, so neither costs a commit.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    item: The git-watch `changed_files` item that woke this tick (`path`, `status`, `sha`,
      `author_name`, `author_email`).

  Returns:
    `{"action": "noop"}` when nothing wakes the coordinator or a live job is already tracked; or
    `{"action": "dispatched", "trigger", "job_id"}` on a fresh dispatch.
  """
  markers = _job_markers.read(repo, asset_note)

  # one active coordinator job per document — but only while that job is genuinely live. A marker
  # left behind by a job that finished, died, or was cancelled is cleared here and this same
  # invocation falls through to trigger resolution, so a dead job can never brick the document.
  tracked_job = _coordinator_job_id(markers)
  if tracked_job:
    # guard: the bundle is still running — the turn belongs to it and no trigger is read
    if _is_job_live(repo, tracked_job):
      return {"action": "noop"}
    markers = _job_markers.update(repo, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # resolve the trigger from the pre-commit blob vs. the current state, and who committed it
  current_text = asset_note.read_text()
  # waiver: type: ignore — note_ops is a deferred/late-bound sibling import; mypy cannot resolve it
  current_report = _note_ops.build_report(current_text, markers)  # type: ignore[attr-defined]
  settings = _load_settings(repo)
  blob_text = _read_blob(repo, item.get(_ITEM_SHA, ""), item.get(_ITEM_PATH, ""))
  # a fresh tick is an operator gesture whoever committed it — bots never tick, so a tick
  # transition overrides the author-based suppression exactly like a review_result transition
  is_operator_edit = (
      not _is_system_commit(repo, asset_note, item, _bot_emails(settings))
      or _has_fresh_tick(blob_text or "", current_text)
  )
  # waiver: type: ignore — note_ops is a deferred/late-bound sibling import; mypy cannot resolve it
  blob_report = _note_ops.build_report(blob_text or "")  # type: ignore[attr-defined]

  # check the four triggers in order; the first that fires wins
  trigger = _resolve_trigger(current_report, blob_report, is_operator_edit, markers)
  # guard: nothing wakes the coordinator this tick
  if trigger is None:
    return {"action": "noop"}

  # dispatch through the shared tail so the direct job-done path and this git path stay one shape
  dedup_key = f"{item.get(_ITEM_PATH, asset_note.name)}:{item.get(_ITEM_SHA, '')}"
  return _dispatch(repo, asset_note, trigger, dedup_key)


def _dispatch(repo: Path, asset_note: Path, trigger: str, dedup_key: str) -> dict:
  """
  Queue one coordinator job for `asset_note` and stamp the runtime marker.

  Args:
    repo: Repository root.
    asset_note: The reviewed document's path.
    trigger: The `_Trigger` token this wake carries.
    dedup_key: Caller-built dedup key for the core queue.

  Returns:
    `{"action": "dispatched", "trigger", "job_id"}`.
  """
  # consume the pending wake so the same landed payload cannot wake a second coordinator job.
  # A wake the entry trigger preempted keeps its flag and fires on a later tick instead.
  if trigger == _Trigger.JOB_DONE:
    _job_markers.update(repo, asset_note, { JobMarker.PENDING_WAKE: None })

  # assemble and queue the coordinator job's wire bundle
  bundle = {
      JobKey.EXPERT: _COORDINATOR_EXPERT,
      JobKey.PAYLOAD: { JobKey.TARGET_FILE: str(asset_note), "trigger": trigger },
      # the pump copies the note at claim, so the bundle names it rather than snapshotting it
      JobKey.SOURCE: [ str(_rel_to_repo(asset_note, repo)) ],
      JobKey.DEDUP_KEY: dedup_key,
      JobKey.PROTOCOLS: [_COORDINATION_PLAYBOOK_PROTOCOL],
  }
  response = _core_dispatch_job(repo, bundle)
  job_id = str(response.get(JobKey.JOB_ID, ""))

  # stamp the dedup marker in runtime state — no document write, so no commit and nothing an
  # operator editing the document can break
  _job_markers.update(repo, asset_note, { JobMarker.COORDINATOR_JOB: job_id })
  return {"action": "dispatched", "trigger": trigger, "job_id": job_id}


def dispatch_job_done(repo: Path, asset_note: Path, dedup_hint: str) -> dict:
  """
  Dispatch a `job-done` coordinator wake directly, without a git item.

  The postman calls this the moment a writer's job goes DONE: no payload commit is made
  any more, so no git-watch item can carry the wake — the postman raises the sidecar flag
  and queues the coordinator itself. The coordinator lands the payload with `collect-job
  --no-commit` inside its own wake and commits once.

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
  """
  markers = _job_markers.read(repo, asset_note)

  # same one-live-job mutex as the git path: a running bundle keeps the turn, a terminal
  # one is cleared and this same call goes on to dispatch
  tracked_job = _coordinator_job_id(markers)
  if tracked_job:
    # guard: the bundle is still running — the pending wake stays raised for a later tick
    if _is_job_live(repo, tracked_job):
      return {"action": "noop"}
    _job_markers.update(repo, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # dedup on the DONE job set so a retry of the same landing folds into one queued job
  rel = _rel_to_repo(asset_note, repo)
  dedup_key = f"{rel}:{_Trigger.JOB_DONE}:{dedup_hint}"
  return _dispatch(repo, asset_note, _Trigger.JOB_DONE, dedup_key)


def main(argv: list[str]) -> int:
  """
  Run one coordinator-dispatch tick from the command line, printing the result as JSON.

  Invoked by the `lazy-review.coordinator-watch` git-watch routine as `coordinator-dispatch
  <item-json>` — one JSON item per changed file, spawned with `cwd = repo`. The routine's own
  `filter.frontmatter` clause has already restricted matches to documents with `review_active:
  true`.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the item JSON is malformed or carries no usable `path`.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-review coordinator-dispatch")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("item_json")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # parse the git-watch item and pull out the changed document's path
  try:
    item = json.loads(args.item_json)
  except json.JSONDecodeError:
    sys.stderr.write(f"malformed git-watch item JSON: {args.item_json!r}\n")
    return 2
  raw_path = item.get(_ITEM_PATH) if isinstance(item, dict) else None
  # guard: not the shape a `changed_files` item takes — nothing to dispatch on
  if not isinstance(raw_path, str) or not raw_path:
    sys.stderr.write(f"git-watch item carries no {_ITEM_PATH!r}: {item!r}\n")
    return 2

  # the daemon spawns this command with cwd = repo root, so a relative item path resolves
  # against --repo (defaulting to the current directory)
  repo = Path(args.repo).resolve()
  asset_note = (repo / raw_path).resolve()
  # guard: the note was deleted or moved between the git-watch scan and this dispatch
  if not asset_note.is_file():
    print(json.dumps({"action": "noop"}))
    return 0

  # run the tick and report the result the same way every other lazy-review CLI verb does
  print(json.dumps(coordinator_dispatch(repo, asset_note, item)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
