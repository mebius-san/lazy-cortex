"""
Guard that holds a job barred from committing in the repository to that bar.

A job dispatched without the commit right that runs on the shared checkout is judged by the commits its own
expert identity authored between the job's claim head and the claim head of the next job of that identity (or
`HEAD`). A found commit is recorded three ways: in the
job's bundle, so it is never reported twice and the job never counts as a success; in the runtime state, as a
record that lasts until the operator resumes the halt that lists it; and as the daemon-wide `forbidden_commit`
halt. While a record lasts the daemon publishes nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
import error_ledger  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_runtime import JOBS_BASE  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from job_response import is_job_bundle  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase, IncidentSeverity, JobArtifact,
  JobConfigKey, JobFile, JobMarker, JobRequestKey, StateKey, WorkspaceMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable, Iterator


# The line a halt lists in place of the commits when git could not list them.
COMMIT_CHECK_FAILED = "... (the job's commits could not be listed: git log failed)"
# The field separator of the `git log` format the commits are read with.
_SEP = "\x1f"
# How one record call ended: a duplicate of a standing record, a fresh halt block, or a merge into a standing one.
_DUPLICATE = "duplicate"
_WRITTEN = "written"
_MERGED = "merged"
# The cause of the incident naming a job whose still-running spawn holds the daemon's publish.
_PUBLISH_HELD_CAUSE = "publish_held"
# The resolution that incident is closed with once the spawn is gone.
_SPAWN_GONE_RESOLUTION = "spawn_gone"


def is_pid_alive(pid: int) -> bool:
  """
  Return whether the given process is currently alive.

  Args:
    pid: Numeric OS process identifier to probe.

  Returns:
    True if a process with that PID exists (or the caller lacks permission to signal it),
    False if the PID is invalid (non-positive or too large for the OS) or the process is gone.
  """
  # guard: non-positive PID is never a real process
  if pid <= 0:
    return False
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  except (OSError, OverflowError):
    # a number no process table can hold is as invalid as a non-positive one
    return False
  return True


def read_barred_identity(jdir: Path) -> tuple[str, str] | None:
  """
  Return the author identity a job barred from committing on the shared checkout would commit under.

  Args:
    jdir: Job bundle directory whose `config.json` and `request.json` are read.

  Returns:
    The `(name, email)` pair the spawn carries; None when the job may commit, runs in its own branch worktree,
    carries no author name, or its config cannot be read.
  """
  # guard: a job allowed to commit has no bar to hold it to
  if (cfg := _read_config(jdir)) is None or cfg.get(JobConfigKey.CAN_COMMIT_IN_REPO, False):
    return None
  return _read_identity(jdir, cfg)


def judge(repo: Path, jdir: Path) -> tuple[list[str], str | None] | None:
  """
  Find the not yet reported commits a barred job's own identity authored since its claim head.

  Guarantees:
    - A commit already in the job's reported-commits file is never returned again.
    - Only commits authored by the job's own identity are returned; the email is compared case-insensitively, and a
      job with no email is matched on an empty email and the same name.
    - Commits at or after the claim head of the first later-claimed job of the same identity on the shared checkout
      are never attributed to this job, except when that later job was claimed while this job's spawn was still
      running. Then every commit of the identity in that later job's window, up to the time this job's spawns were
      proven gone (with no proof the overlap is still open), is returned too, as an ambiguous line
      `<hash> <subject> (ambiguous with <expert>/<job id>)`.
    - A listing git could not make is returned as an empty list with the reason, never as None; callers must treat
      it as unverified, not as clean.
    - None means the job is not barred, has no claim head, or authored nothing new.

  Args:
    repo: Repository root whose `HEAD` is read.
    jdir: Job bundle directory being judged.

  Returns:
    None when the job is not barred, carries no claim head, or authored nothing new. Otherwise the
    `<hash> <subject>` lines of its new commits, followed by the ambiguous ones as
    `<hash> <subject> (ambiguous with <expert>/<job id>)`, with None; or an empty list with the reason the commits
    could not be listed.
  """

  # Domain(runtime.job-execution):
  # # A job barred from committing is held to it
  # A job dispatched without the right to commit in the repository is told so in its prompt, but a prompt is
  # no guarantee. After the run the shared checkout's branch is compared with the commit it stood at when the
  # job was claimed, and a commit the job's own identity authored in between is a breach: the job fails and the
  # whole runtime stops, so the commit is neither built on nor published before the operator has seen it. The
  # commit itself is left exactly where it landed — undoing it is the operator's call, never the runtime's. A
  # run whose runner was killed before it could look is judged the same way once its runner is found gone. A
  # commit already reported for the job is not reported again, so a resumed runtime does not stop twice over
  # the commits the operator has already judged. A check that could not be made gives no proof the job kept its
  # word, so it stops the runtime the same way.

  # Contract:
  # A commit whose hash is already in the job's reported-commits file is never returned again.

  # Contract:
  # Only commits authored by the job's own identity are returned; the email is compared case-insensitively, and a
  # job with no email is matched on an empty email and the same name.

  # Contract:
  # The window is bounded: a commit at or after the claim head of the first later-claimed job of the same
  # identity on the shared checkout is never attributed to this job, except when that later job was claimed while
  # this job's spawn was still running. Then every commit of the identity in that later job's window, up to the
  # time this job's spawns were proven gone (with no proof the overlap is still open), is returned too, as an
  # ambiguous line `<hash> <subject> (ambiguous with <expert>/<job id>)`.

  # Contract:
  # A listing git could not make is returned as an empty list with the reason, never as None; a caller MUST treat
  # it as unverified, not as clean.

  # Contract:
  # None means the job is not barred, has no claim head, or authored nothing new.

  # guard: only a barred job on the shared checkout is judged
  if (identity := read_barred_identity(jdir)) is None:
    return None

  # limit: a job with no recorded claim head is not judged — the marker is missing only when the tree had no
  # resolvable HEAD at claim, which a daemon checkout never has; a fallback would need the claim-time branch
  try:
    claim_head = (jdir / JobArtifact.CLAIM_HEAD).read_text(encoding = "utf-8").strip()
  except FileNotFoundError:
    return None

  # guard: an empty marker carries no boundary either
  if not claim_head:
    return None

  # a listing git could not make is no proof the job kept its bar; the window closes where a later job of the same
  # identity was claimed, so that job's commits are never the barred job's — unless this job's spawn outlived that
  # claim, which makes every commit of the identity during the overlap ambiguous between the two
  later = _find_later_claims(repo, jdir, identity)
  try:
    commits = _query_commits_since(repo, claim_head, later[0][1] if later else None)
    ambiguous = _find_overlap_commits(repo, jdir, later)
  except (OSError, subprocess.CalledProcessError) as error:
    detail = (getattr(error, "stderr", None) or "").strip()
    return [], f"{error}: {detail}" if detail else str(error)

  # the job's own and its ambiguous commits that were not reported before, in their one-line form
  reported = _read_reported(jdir)
  name, email = identity
  found = [
    f"{sha} {subject}" for sha, author_name, author_email, _stamp, subject in commits
    if sha not in reported and _is_authored_by(author_name, author_email, name, email)
  ]
  found += [
    f"{sha} {subject} (ambiguous with {other})" for sha, author_name, author_email, other, subject in ambiguous
    if sha not in reported and _is_authored_by(author_name, author_email, name, email)
  ]
  return (found, None) if found else None


def record(repo: Path, expert: str, jdir: Path, verdict: tuple[list[str], str | None], *,
           triggered_by: str, on_halt: Callable[..., None]) -> bool:
  """
  Record a barred job's forbidden commits and halt the daemon over them.

  A failed listing already on record for the job is not recorded again, whatever claim head it named.

  Notes:
    - Appends the found hashes to the job's reported-commits file, which marks the job as failed for good.
    - Appends one record to the runtime state's forbidden-commit list, which lasts until the operator resumes the
      halt that lists it.
    - Writes the `forbidden_commit` halt block and calls `on_halt` for it when no halt stands; merges the job and
      its commits into a standing `forbidden_commit` block and adds an event naming the job and its commits to that
      halt's incident without counting the halt again; leaves any other standing block as it is, the record
      raising the halt once that block is cleared.
    - Writes one line naming the job and the commits to stderr.

  Args:
    repo: Repository root whose runtime state is written.
    expert: Name of the expert whose job committed.
    jdir: Job bundle directory of that job.
    verdict: What `judge` returned for the job.
    triggered_by: Routine or step name the halt records as its trigger.
    on_halt: The halt-accounting callable, called with the same keywords as the daemon's `record_halt`.

  Returns:
    True when a record was added; False when the failed listing was already on record.
  """
  commits, failure = verdict
  entry = {
    IncidentKey.EXPERT: expert, IncidentKey.JOB_ID: jdir.name,
    HaltKey.CLAIM_HEAD: (jdir / JobArtifact.CLAIM_HEAD).read_text(encoding = "utf-8").strip(),
    HaltKey.COMMITS: commits if failure is None else [ COMMIT_CHECK_FAILED ],
  }

  # the found hashes are never reported again, and their job never counts as a success
  if commits:
    # waiver: stdlib file-mode token, not a domain constant
    with (jdir / JobArtifact.REPORTED_COMMITS).open("a", encoding = "utf-8") as handle:
      handle.write("".join(f"{line.split(' ', 1)[0]}\n" for line in commits))

  # the record and the halt land in one write, so a resume can never fall between them
  block = _build_halt_block([ entry ], triggered_by = triggered_by)
  outcome: list[str] = []

  # appends the record, then writes, extends or leaves the standing halt block
  def _apply(state: dict) -> None:
    records = state.setdefault(StateKey.FORBIDDEN_COMMITS, [])

    # guard: a failed listing of this job stands on record already, whatever claim head it named
    if failure is not None and any(
      _job_key(other) == _job_key(entry) and other.get(HaltKey.COMMITS) == [ COMMIT_CHECK_FAILED ]
      for other in records
    ):
      outcome.append(_DUPLICATE)
      return
    records.append(entry)
    standing = state.get(StateKey.DAEMON_HALTED)
    if standing is None:
      state[StateKey.DAEMON_HALTED] = block
      outcome.append(_WRITTEN)
    elif standing.get(HaltKey.REASON) == HaltReason.FORBIDDEN_COMMIT:
      standing[HaltKey.COMMITS] = [ *standing.get(HaltKey.COMMITS, []), *entry[HaltKey.COMMITS] ]
      standing[HaltKey.JOBS] = [ *standing.get(HaltKey.JOBS, []), _job_key(entry) ]
      outcome.append(_MERGED)
  runtime_state.update(repo, _apply)

  # guard: nothing new was recorded
  if _DUPLICATE in outcome:
    return False

  # the loud line reaches the daemon journal's stderr tail and the operator's terminal
  sys.stderr.write(
    f"DAEMON HALTED (forbidden commit): expert {expert} job {jdir.name} is barred from committing in the "
    f"repository; commits: {'; '.join(entry[HaltKey.COMMITS])}\n"
  )

  # a block this call wrote opens the halt incident and counts the halt; a job merged into a standing block is
  # added to that incident, naming the job and its commits, without counting the halt twice
  detail = failure or "; ".join(commits)
  if _WRITTEN in outcome:
    on_halt(repo, reason = HaltReason.FORBIDDEN_COMMIT, triggered_by = triggered_by,
            detail = detail, expert = expert, job_id = jdir.name)
  elif _MERGED in outcome:
    error_ledger.record(repo, {
      IncidentKey.INCIDENT: f"halt:{Path(repo).name}", IncidentKey.PHASE: IncidentPhase.OPENED,
      IncidentKey.KIND: IncidentKind.DAEMON_HALT, IncidentKey.CAUSE: HaltReason.FORBIDDEN_COMMIT,
      IncidentKey.ACTOR: triggered_by, IncidentKey.DETAIL: detail, IncidentKey.EXPERT: expert,
      IncidentKey.JOB_ID: jdir.name,
    })
  return True


def reraise(repo: Path, *, triggered_by: str, on_halt: Callable[..., None]) -> bool:
  """
  Raise the `forbidden_commit` halt again when no halt stands while forbidden-commit records remain.

  Notes:
    - Writes one halt block listing every record's job and commits, and calls `on_halt` for it.

  Args:
    repo: Repository root whose runtime state is read and written.
    triggered_by: Routine or step name the halt records as its trigger.
    on_halt: The halt-accounting callable, called with the same keywords as the daemon's `record_halt`.

  Returns:
    True when this call wrote the halt block; False when a halt stands or no record remains.
  """
  written: list[dict] = []

  # writes the block over every record when no halt stands
  def _apply(state: dict) -> None:
    entries = state.get(StateKey.FORBIDDEN_COMMITS) or []
    # guard: a standing halt keeps its own account, and with no record there is nothing to raise
    if state.get(StateKey.DAEMON_HALTED) is not None or not entries:
      return
    state[StateKey.DAEMON_HALTED] = _build_halt_block(entries, triggered_by = triggered_by)
    written.append(state[StateKey.DAEMON_HALTED])

  # one atomic read-modify-write, so a halt another writer persisted meanwhile is never clobbered
  runtime_state.update(repo, _apply)

  # guard: nothing was written
  if not written:
    return False
  on_halt(repo, reason = HaltReason.FORBIDDEN_COMMIT, triggered_by = triggered_by,
          detail = "; ".join(written[0][HaltKey.COMMITS]),
          expert = written[0][IncidentKey.EXPERT], job_id = written[0][IncidentKey.JOB_ID])
  return True


def release(state: dict) -> None:
  """
  Clear the standing halt from a loaded runtime state, with the forbidden-commit records it listed.

  Records the halt did not list stay, so their halt is raised once nothing stands.

  Guarantees:
    - The standing halt is cleared, whatever its reason.
    - For a `forbidden_commit` halt, only the forbidden-commit records whose job the halt block lists are dropped; a
      block with no job list stands for its own expert and job. Every other record is kept, and the key is removed
      when no record is left.
    - For any other halt, every forbidden-commit record is left as it is.
    - Only the given dict is mutated, so the caller can make the release one state write.

  Args:
    state: The loaded runtime state, changed in place.
  """

  # Contract:
  # The standing halt is cleared, whatever its reason.

  # Contract:
  # For a `forbidden_commit` halt, only the forbidden-commit records whose job the halt block lists are dropped;
  # a block with no job list stands for its own expert and job. Every other record is kept, and the key is removed
  # when no record is left.

  # Contract:
  # For any other halt, every forbidden-commit record is left as it is.

  # Contract:
  # Only the given dict is mutated, so the caller can make the release one state write.

  halt = state.pop(StateKey.DAEMON_HALTED, None)

  # guard: only a forbidden-commit halt was the operator's view of records
  if not halt or halt.get(HaltKey.REASON) != HaltReason.FORBIDDEN_COMMIT:
    return

  # the records the operator saw in the block go; any other stays
  listed = set(halt.get(HaltKey.JOBS) or [ _job_key(halt) ])
  kept = [ entry for entry in state.get(StateKey.FORBIDDEN_COMMITS) or [] if _job_key(entry) not in listed ]
  if kept:
    state[StateKey.FORBIDDEN_COMMITS] = kept
  else:
    state.pop(StateKey.FORBIDDEN_COMMITS, None)


def is_held(repo: Path) -> bool:
  """
  Report whether a forbidden-commit record keeps the daemon from publishing.

  Args:
    repo: Repository root whose runtime state is read.

  Returns:
    True while the runtime state holds at least one forbidden-commit record.
  """
  return bool(runtime_state.load(repo).get(StateKey.FORBIDDEN_COMMITS))


def is_recorded(repo: Path, job_id: str) -> bool:
  """
  Report whether a forbidden-commit record names the given job.

  Args:
    repo: Repository root whose runtime state is read.
    job_id: Identifier of the job looked for.

  Returns:
    True when a standing record names the job.
  """
  entries = runtime_state.load(repo).get(StateKey.FORBIDDEN_COMMITS) or []
  return any(entry.get(IncidentKey.JOB_ID) == job_id for entry in entries)


def is_tainted(jdir: Path) -> bool:
  """
  Report whether a job was ever found to have committed although barred.

  Args:
    jdir: Job bundle directory looked at.

  Returns:
    True when a forbidden commit was reported for the job; such a job never counts as a success.
  """
  return bool(_read_reported(jdir))


def find_spawn_pids(jdir: Path) -> list[int] | None:
  """
  List the processes, other than this one, whose command line names a job directory.

  Args:
    jdir: Absolute job directory the spawn's command line carries.

  Returns:
    The process ids; None when the process table cannot be read.
  """
  # guard: without `ps` no spawn can be found
  try:
    listing = subprocess.run(
      [ "ps", "-ax", "-o", "pid=,command=" ],
      capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    )
  except OSError:
    return None

  # guard: a table `ps` could not print is no account of the processes
  if listing.returncode != 0:
    return None

  # every process naming the job dir on its command line is one of its spawns, never this process itself
  needle = str(jdir)
  pids: list[int] = []
  for line in listing.stdout.splitlines():
    pid_text, _, command = line.strip().partition(" ")
    if pid_text.isdigit() and needle in command and int(pid_text) != os.getpid():
      pids.append(int(pid_text))
  return pids


def note_claim_overlaps(repo: Path, jdir: Path) -> None:
  """
  Record, for a job just claimed on the shared checkout, the barred orphans of its identity whose spawn still runs.

  Notes:
    - Writes the job's claim-overlaps file, one `<expert>/<job id>` per line, when there is any such orphan; an
      orphan whose spawn cannot be proven gone counts as running.

  Args:
    repo: Repository root containing the expert job tree.
    jdir: The job just claimed.
  """
  # guard: a job in its own branch worktree, or one with no identity, shares no commits with an orphan
  if (identity := _read_identity(jdir)) is None:
    return
  name, email = identity

  # every barred orphan of the same identity whose spawn may still commit beside this job
  overlaps: list[str] = []
  for expert, other in _iter_bundles(repo):
    # guard: only another job's orphaned claim, barred and of the same identity
    if other == jdir or not _is_orphaned_claim(other):
      continue
    if (other_identity := read_barred_identity(other)) is None or not _is_authored_by(*other_identity, name, email):
      continue
    pids = find_spawn_pids(other)
    if pids is None or pids:
      overlaps.append(f"{expert}/{other.name}")

  # the overlaps travel with the claim, read back whenever the orphan is judged
  if overlaps:
    (jdir / JobArtifact.CLAIM_OVERLAPS).write_text("".join(f"{key}\n" for key in overlaps), encoding = "utf-8")


def note_spawns_gone(repo: Path, jdir: Path) -> None:
  """
  Record that no spawn of an orphaned job is left running, and lift the job's hold on the daemon's publish.

  Notes:
    - Writes the job's spawns-gone marker once; its time ends any overlap with a later claim.
    - Closes the incident that named the job as holding the publish, when one was opened.

  Args:
    repo: Repository root whose error ledger receives the event.
    jdir: The job's bundle directory.
  """
  marker = jdir / JobArtifact.SPAWNS_GONE

  # the first proof is the one that bounds the overlap
  if not marker.exists():
    marker.touch()
  _resolve_held_publish(repo, jdir.parent.name, jdir)


def sweep_orphaned(repo: Path, *, triggered_by: str, on_halt: Callable[..., None]) -> bool:
  """
  Judge every claimed, unfinished barred job whose claimant is gone, and record what each committed.

  A job's bundle is left to the pump to close; a found commit only marks it as failed for good.

  Notes:
    - A job whose spawn may still be running is named once in the error ledger as holding the daemon's publish.
    - A job with no spawn left running has that proof recorded, which lifts its hold; a job that held the publish
      and is no longer an orphaned claim has its hold lifted too.

  Args:
    repo: Repository root containing the expert job tree.
    triggered_by: Routine or step name a raised halt records as its trigger.
    on_halt: The halt-accounting callable, called with the same keywords as the daemon's `record_halt`.

  Returns:
    True when such a job's spawn may still be running — it is alive, or the process table cannot be read — so
    a commit may still land after the sweep; False otherwise.
  """
  # every orphaned claim of a barred job is judged
  running = False
  for expert, jdir in _iter_bundles(repo):
    orphaned = _is_orphaned_claim(jdir)

    # a job that held the publish and is no longer an orphaned claim was settled; its hold is lifted
    if not orphaned and (jdir / JobArtifact.PUBLISH_HELD).exists():
      _resolve_held_publish(repo, expert, jdir)

    # guard: only an orphaned claim of a barred job is judged
    if not orphaned or read_barred_identity(jdir) is None:
      continue

    # a spawn that outlived its pump can still commit; the job holding the publish is named once in the ledger,
    # and a spawn proven gone is noted, which bounds any overlap and lifts that job's hold
    pids = find_spawn_pids(jdir)
    if pids is None or pids:
      running = True
      _note_held_publish(repo, expert, jdir)
    else:
      note_spawns_gone(repo, jdir)

    # what the job committed so far is recorded now
    if (verdict := judge(repo, jdir)) is not None:
      record(repo, expert, jdir, verdict, triggered_by = triggered_by, on_halt = on_halt)
  return running


def _read_config(jdir: Path) -> dict | None:
  """
  Read a job's `config.json`.

  Args:
    jdir: Job bundle directory.

  Returns:
    The config object; None when it is absent, unreadable or not an object.
  """
  try:
    cfg = json.loads((jdir / JobFile.CONFIG).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return None
  return cfg if isinstance(cfg, dict) else None


def _read_identity(jdir: Path, cfg: dict | None = None) -> tuple[str, str] | None:
  """
  Return the author identity a job running on the shared checkout commits under, whatever its commit right.

  Args:
    jdir: Job bundle directory whose `config.json` and `request.json` are read.
    cfg: The job's config when the caller has read it already.

  Returns:
    The `(name, email)` pair the spawn carries; None when the job runs in its own branch worktree, carries no
    author name, or its config cannot be read.
  """
  # guard: an unreadable config names no identity
  if (cfg := cfg if cfg is not None else _read_config(jdir)) is None:
    return None

  # guard: a branch job with a payload branch runs in its own worktree, away from the shared checkout
  if cfg.get(JobConfigKey.WORKSPACE) == WorkspaceMode.BRANCH and _has_payload_branch(jdir):
    return None

  # the identity the pump exports into the spawn's environment
  author = cfg.get(JobConfigKey.GIT_AUTHOR)

  # guard: no identity block — the spawn carries an empty name, under which git refuses to commit
  if not isinstance(author, dict):
    return None
  # waiver: the expert-entry identity sub-keys, owned by the lazy.settings contract, not reusable domain keys
  name, email = str(author.get("name") or ""), str(author.get("email") or "")

  # guard: git refuses every commit under an empty author name, an email alone included
  if not name:
    return None
  return name, email


def _find_later_claims(repo: Path, jdir: Path, identity: tuple[str, str]) -> list[tuple[int, str, Path]]:
  """
  List the jobs of the same identity claimed on the shared checkout after a job, earliest first.

  Args:
    repo: Repository root containing the expert job tree.
    jdir: The job the later claims are looked for after.
    identity: The job's `(name, email)` author identity.

  Returns:
    One `(claim time in nanoseconds, claim head, bundle directory)` tuple per later claim.
  """
  own = (jdir / JobArtifact.CLAIM_HEAD).stat().st_mtime_ns
  name, email = identity

  # every later claim of the same identity on the shared checkout
  later: list[tuple[int, str, Path]] = []
  for _expert, other in _iter_bundles(repo):
    marker = other / JobArtifact.CLAIM_HEAD
    try:
      claimed = marker.stat().st_mtime_ns
    except OSError:
      continue

    # guard: the job itself, or an earlier claim
    if other == jdir or claimed <= own:
      continue

    # guard: a job in its own branch worktree, or under another identity, does not commit for this one
    if (other_identity := _read_identity(other)) is None or not _is_authored_by(*other_identity, name, email):
      continue
    later.append(( claimed, marker.read_text(encoding = "utf-8").strip(), other ))
  return sorted(later, key = lambda claim: claim[0])


def _find_overlap_commits(repo: Path, jdir: Path,
                          later: list[tuple[int, str, Path]]) -> list[tuple[str, str, str, str, str]]:
  """
  List the commits landed while a job's spawn outlived the claim of a later job of the same identity.

  Args:
    repo: Repository root whose branch is read.
    jdir: The job whose spawn may have outlived the later claims.
    later: The later claims of the same identity, earliest first.

  Returns:
    One `(hash, author name, author email, other job, subject)` tuple per commit of a later job's window that
    landed before the job's spawn was proven gone, the other job named `<expert>/<job id>`.

  Raises:
    subprocess.CalledProcessError: When `git log` exits non-zero.
    OSError: When git cannot be started.
  """
  key = f"{jdir.parent.name}/{jdir.name}"

  # the overlap ends when the spawn was proven gone; with no proof it is still open
  try:
    gone_at: float | None = (jdir / JobArtifact.SPAWNS_GONE).stat().st_mtime
  except OSError:
    gone_at = None

  # each later window that noted this job's spawn alive at its claim contributes what landed before the proof
  found: list[tuple[str, str, str, str, str]] = []
  for index, ( _claimed, head, other ) in enumerate(later):
    try:
      overlaps = (other / JobArtifact.CLAIM_OVERLAPS).read_text(encoding = "utf-8").split()
    except FileNotFoundError:
      continue

    # guard: the later job saw this job's spawn gone when it was claimed
    if key not in overlaps or not head:
      continue
    end = later[index + 1][1] if index + 1 < len(later) else None
    found += [
      ( sha, name, email, f"{other.parent.name}/{other.name}", subject )
      for sha, name, email, stamp, subject in _query_commits_since(repo, head, end)
      if gone_at is None or stamp <= gone_at
    ]
  return found


def _held_incident(expert: str, jdir: Path) -> str:
  """
  Name the incident that records a job's spawn holding the daemon's publish.

  Args:
    expert: Name of the expert whose queue holds the job.
    jdir: The job's bundle directory.

  Returns:
    The incident key.
  """
  return f"held:{expert}/{jdir.name}"


def _resolve_held_publish(repo: Path, expert: str, jdir: Path) -> None:
  """
  Close the incident naming a job as holding the daemon's publish, when one was opened.

  Notes:
    - Writes a `resolved` event for the incident and removes the job's held-publish marker.

  Args:
    repo: Repository root whose error ledger receives the event.
    expert: Name of the expert whose queue holds the job.
    jdir: The job's bundle directory.
  """
  marker = jdir / JobArtifact.PUBLISH_HELD

  # guard: the job never held the publish
  if not marker.exists():
    return
  error_ledger.resolve(repo, _held_incident(expert, jdir), resolution = _SPAWN_GONE_RESOLUTION,
                       kind = IncidentKind.JOB_ERROR, cause = _PUBLISH_HELD_CAUSE, actor = IncidentActor.DAEMON,
                       expert = expert, job_id = jdir.name)
  marker.unlink(missing_ok = True)


def _note_held_publish(repo: Path, expert: str, jdir: Path) -> None:
  """
  Name a job whose still-running spawn holds the daemon's publish in the error ledger, once per job.

  Notes:
    - Writes a `job_error` incident of severity `warn` and cause `publish_held`, keyed on the job, and a marker in
      the job's bundle so the incident is written once; the incident is keyed apart from the job's own incident, so
      closing it never closes a failure of the job.

  Args:
    repo: Repository root whose error ledger receives the incident.
    expert: Name of the expert whose queue holds the job.
    jdir: The job's bundle directory.
  """
  marker = jdir / JobArtifact.PUBLISH_HELD

  # guard: the job was named already
  if marker.exists():
    return
  error_ledger.record(repo, {
    IncidentKey.INCIDENT: _held_incident(expert, jdir), IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.JOB_ERROR, IncidentKey.CAUSE: _PUBLISH_HELD_CAUSE,
    IncidentKey.SEVERITY: IncidentSeverity.WARN, IncidentKey.ACTOR: IncidentActor.DAEMON,
    IncidentKey.EXPERT: expert, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.DETAIL: "the job's pump is gone while its spawn may still run and commit; the daemon publishes "
                        "nothing until the spawn is gone",
  })
  marker.touch()


def _iter_bundles(repo: Path) -> Iterator[tuple[str, Path]]:
  """
  Walk every bundle directory of the expert job tree.

  Args:
    repo: Repository root containing the expert job tree.

  Yields:
    One `(expert, bundle directory)` pair per entry; a folder that cannot be listed yields nothing.
  """
  base = Path(repo) / JOBS_BASE

  # guard: nothing was ever dispatched
  if not base.is_dir():
    return
  for edir in sorted(base.iterdir()):
    try:
      bundles = sorted(edir.iterdir()) if edir.is_dir() else []
    except OSError:
      continue
    for jdir in bundles:
      yield edir.name, jdir


def _build_halt_block(entries: list[dict], *, triggered_by: str) -> dict:
  """
  Build the `forbidden_commit` halt block that lists the given records.

  Args:
    entries: The forbidden-commit records the block lists, the first one naming the job.
    triggered_by: Routine or step name the halt records as its trigger.

  Returns:
    The halt block.
  """
  return {
    HaltKey.HALTED_SINCE: time.time(), HaltKey.TRIGGERED_BY: triggered_by,
    HaltKey.REASON: HaltReason.FORBIDDEN_COMMIT,
    HaltKey.COMMITS: [ line for entry in entries for line in entry[HaltKey.COMMITS] ],
    HaltKey.JOBS: [ _job_key(entry) for entry in entries ],
    HaltKey.CLAIM_HEAD: entries[0][HaltKey.CLAIM_HEAD],
    IncidentKey.EXPERT: entries[0][IncidentKey.EXPERT], IncidentKey.JOB_ID: entries[0][IncidentKey.JOB_ID],
  }


def _job_key(entry: dict) -> str:
  """
  Name the job a forbidden-commit record or halt block is about.

  Args:
    entry: The record or block.

  Returns:
    The `<expert>/<job id>` name.
  """
  return f"{entry.get(IncidentKey.EXPERT)}/{entry.get(IncidentKey.JOB_ID)}"


def _query_commits_since(repo: Path, claim_head: str,
                         until: str | None) -> list[tuple[str, str, str, float, str]]:
  """
  List the commits the branch gained since the claim head, up to an end commit.

  Args:
    repo: Repository root whose `HEAD` is read.
    claim_head: Commit the tree stood at when the job was claimed.
    until: Commit the window ends at, or None for `HEAD`.

  Returns:
    One `(hash, author name, author email, committer time, subject)` tuple per commit, newest first; the time is in
    epoch seconds.

  Raises:
    subprocess.CalledProcessError: When `git log` exits non-zero.
    OSError: When git cannot be started.
  """
  # waiver: git CLI vocabulary, not a domain constant
  argv = [
    "git", "log", "--no-show-signature", f"--format=%H{_SEP}%an{_SEP}%ae{_SEP}%ct{_SEP}%s",
    f"{claim_head}..{until or 'HEAD'}",
  ]
  listing = subprocess.run(
    argv, cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "replace",
  )

  # guard: git could not list the range — an unknown claim head, a broken repository
  if listing.returncode != 0:
    raise subprocess.CalledProcessError(listing.returncode, argv, output = listing.stdout, stderr = listing.stderr)

  # each line splits into its five fields; a subject carrying the separator keeps the rest
  rows: list[tuple[str, str, str, float, str]] = []
  for line in listing.stdout.splitlines():
    # waiver: the five fields of the format above, not a domain constant
    sha, name, email, stamp, subject = [ *line.split(_SEP, 4), "", "", "", "" ][:5]
    rows.append((sha, name, email, float(stamp) if stamp.isdigit() else 0.0, subject))
  return rows


def _is_authored_by(author_name: str, author_email: str, name: str, email: str) -> bool:
  """
  Report whether a commit's author is the identity a spawn carries.

  Args:
    author_name: The commit's author name.
    author_email: The commit's author email.
    name: The spawn's author name.
    email: The spawn's author email, empty when its config names none.

  Returns:
    True for the same email, compared case-insensitively; with no email, for an empty email and the same name.
  """

  # Domain(runtime.job-execution):
  # # A forbidden commit is matched on the job's own identity
  # Only the identity the runtime hands the job's expert is held against the job. Git writes that identity into
  # every commit the expert, its helpers and its sub-steps make, while the expert's persona memory commits under
  # a separate memory identity and an operator working in the same checkout commits under their own; neither is
  # the job's. An address is matched regardless of letter case, as mail addresses are. An identity with a name
  # and no address still commits, under an empty address, so such a job is matched on that empty address and the
  # name together.

  # an address decides on its own; without one the empty address and the name decide together
  if email:
    return author_email.lower() == email.lower()
  return not author_email and author_name == name


def _read_reported(jdir: Path) -> set[str]:
  """
  Read the hashes already reported as forbidden commits for a job.

  Args:
    jdir: Job bundle directory whose reported-commits file is read.

  Returns:
    The reported hashes; empty when none was reported.
  """
  try:
    return set((jdir / JobArtifact.REPORTED_COMMITS).read_text(encoding = "utf-8").split())
  except FileNotFoundError:
    return set()


def _has_payload_branch(jdir: Path) -> bool:
  """
  Report whether a job's request names a branch to run on.

  Args:
    jdir: Job bundle directory whose `request.json` is read.

  Returns:
    True when the request names a branch; False when it names none or cannot be read.
  """
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return False
  return isinstance(request, dict) and bool(request.get(JobRequestKey.BRANCH))


def _is_orphaned_claim(jdir: Path) -> bool:
  """
  Report whether a bundle is a claimed, unfinished job whose claimant process is gone.

  Args:
    jdir: Bundle directory being looked at.

  Returns:
    True for a READY bundle with a claim marker, no terminal marker and no live claimant.
  """
  # guard: only a claimed, unfinished real bundle has a claimant to lose
  if not is_job_bundle(jdir) or not (jdir / JobMarker.READY).exists() or not (jdir / JobMarker.PID).exists():
    return False

  # guard: a finished, buried or cancelled job is past its run
  if any((jdir / marker).exists() for marker in ( JobMarker.DONE, JobMarker.DEAD, JobMarker.CANCELLED )):
    return False

  # an unreadable or garbled claim marker reads the same as a claimant that is gone
  try:
    pid = int((jdir / JobMarker.PID).read_text(encoding = "utf-8").strip())
  except (OSError, ValueError):
    return True
  return not is_pid_alive(pid)
