"""
Guarded fast-forward pull — the Python primitive backing the
`lazycortex-core safe-pull` CLI subcommand.

Built for the runtime daemon's `post_push_hook`: after the daemon pushes
from its own checkout, the hook fans the new commits out into the
operator's working copies. A bare `git pull` there races whatever that
checkout is doing — a session's partial commit, parked staged content —
and a lost index update leaves residue the git guard then refuses over.
This primitive pulls only when it is provably safe: it waits out a held
`index.lock`, refuses to touch a checkout with staged content, and
merges only a strict fast-forward.

CLI: `safe-pull <repo-dir> <remote> <ref> [--timeout-sec N]`. Every
guarded outcome exits `0` (the hook contract is best-effort); only
unusable arguments exit non-zero.

Stdout: one JSON object — `{"outcome": "pulled"|"noop"|"skipped"|"error", ...}`
with `reason` on a skip and `from`/`to` shas on a pull.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_PROG = "lazycortex-core safe-pull"
_GIT_DIR = ".git"
_INDEX_LOCK = "index.lock"
_TIMEOUT_SEC_DEFAULT = 60.0
# poll cadence while the target's index.lock is held — short enough to catch a freed lock
# promptly, long enough to stay invisible in load
_LOCK_POLL_SEC = 0.5
# Outcome vocabulary of the JSON result
_OUT_PULLED = "pulled"
_OUT_NOOP = "noop"
_OUT_SKIPPED = "skipped"
_OUT_ERROR = "error"
_REASON_LOCK = "index_lock_held"
_REASON_DIRTY = "index_dirty"
_REASON_NOT_BEHIND = "not_behind"


def _emit(payload: dict) -> None:
  """
  Print the single-line JSON result the hook caller reads.

  Args:
    payload: The result object, already carrying its `outcome`.
  """
  print(json.dumps(payload))


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
  """
  Run one git command against the target checkout without raising on failure.

  Args:
    repo: Absolute path of the checkout the command targets.
    args: Argument vector after the `git` token.

  Returns:
    The completed process, output captured as text; the caller reads the return code.
  """
  return subprocess.run([ "git", "-C", str(repo), *args ],
                        check = False, capture_output = True, text = True)


def main(argv: list[str]) -> int:
  """
  Run the `safe-pull` subcommand: a guarded fast-forward pull into another checkout.

  Args:
    argv: CLI arguments after the subcommand token —
      `<repo-dir> <remote> <ref> [--timeout-sec N]`.

  Returns:
    `0` for every guarded outcome (`pulled`, `noop`, `skipped`); non-zero only when the
    arguments are unusable (missing directory, not a git checkout).
  """
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("repo_dir", help = "Absolute path of the checkout to pull into")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("remote", help = "Remote name or URL to fetch from")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("ref", help = "Branch name to fetch")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("--timeout-sec", type = float, default = _TIMEOUT_SEC_DEFAULT,
                      help = "Ceiling on waiting out a held index.lock")
  args = parser.parse_args(argv)

  # guard: an unusable target is the caller's configuration error, the one non-zero path
  repo = Path(args.repo_dir)
  if not (repo / _GIT_DIR).exists():
    _emit({ "outcome": _OUT_ERROR, "error": f"not a git checkout: {args.repo_dir}" })
    return 1

  # wait out a held index lock — someone is committing or staging; never pull through them
  lock = repo / _GIT_DIR / _INDEX_LOCK
  deadline = time.monotonic() + args.timeout_sec
  while lock.exists():
    # guard: still held at the deadline — leave the checkout alone, the next push retries
    if time.monotonic() >= deadline:
      _emit({ "outcome": _OUT_SKIPPED, "reason": _REASON_LOCK })
      return 0
    time.sleep(_LOCK_POLL_SEC)

  # guard: staged content belongs to the operator — a pull must not touch that index at all
  # waiver: git CLI vocabulary, not a domain constant
  if _git(repo, "diff", "--cached", "--quiet").returncode != 0:
    _emit({ "outcome": _OUT_SKIPPED, "reason": _REASON_DIRTY })
    return 0

  # fetch, then merge only a strict fast-forward — ahead or diverged is not this hook's business
  # waiver: git CLI vocabulary, not a domain constant
  fetch = _git(repo, "fetch", args.remote, args.ref)
  # guard: an unreachable remote is a transient the next push retries — not an error here
  if fetch.returncode != 0:
    _emit({ "outcome": _OUT_SKIPPED, "reason": "fetch_failed" })
    return 0
  # waiver: git CLI vocabulary, not a domain constant
  head = _git(repo, "rev-parse", "HEAD").stdout.strip()
  # waiver: git CLI vocabulary, not a domain constant
  fetched = _git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()
  # guard: already at the fetched commit — nothing to merge
  if head == fetched:
    _emit({ "outcome": _OUT_NOOP })
    return 0
  # waiver: git CLI vocabulary, not a domain constant
  base = _git(repo, "merge-base", "HEAD", "FETCH_HEAD").stdout.strip()
  # guard: only strictly-behind fast-forwards — ahead and diverged both leave the checkout alone
  if base != head:
    _emit({ "outcome": _OUT_SKIPPED, "reason": _REASON_NOT_BEHIND })
    return 0

  # the merge itself may still lose a freshly taken lock — a failed ff is a skip, not an error
  # waiver: git CLI vocabulary, not a domain constant
  merge = _git(repo, "merge", "--ff-only", "FETCH_HEAD")
  if merge.returncode != 0:
    _emit({ "outcome": _OUT_SKIPPED, "reason": "merge_failed" })
    return 0
  _emit({ "outcome": _OUT_PULLED, "from": head, "to": fetched })
  return 0
