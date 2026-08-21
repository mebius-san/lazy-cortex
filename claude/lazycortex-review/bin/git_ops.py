"""Local-only git operations for lazy-review.

The module's surface is intentionally narrow: every public function
either reads the local repository's history for one file or writes
exactly one local commit carrying a single `Doc-Review-Phase` trailer
under a caller-supplied git author identity. The module NEVER touches
the remote (no push / pull / fetch / rebase / reset --hard) — that is
`lazycortex-core`'s job, run around every routine tick.

Commit functions all share the same shape:

- They expect the working tree to already reflect the desired state
  (mutated by `body.py` / `banner.py`).
- They stage the single path argument (`git add <path>`) and commit
  it; nothing else is added.
- The commit subject is taken from the `message` argument verbatim;
  the `Doc-Review-Phase` trailer is appended in the commit body,
  separated by a blank line.
- The author identity for the commit is set per-call via the `-c`
  flag so concurrent commits under different bot identities don't
  fight over `git config`.

Trailer format — every commit carries exactly one `Doc-Review-Phase`
trailer; readers parse the value via :func:`parse_phase_trailer`:

    Doc-Review-Phase: <phase>[; expert=<flat-name>][; round=<N>]

Phases used by each commit kind:

- :func:`commit_review_round` — `main` or `section` with paired
  `expert=` and `round=` segments. The phase is supplied by the
  caller and matches the writer's role.
- :func:`commit_empty` — same phase / expert / round as
  `commit_review_round` but with an empty diff (`--allow-empty`).
  Used when an agent returned `outcome: empty` so the next tick
  can move past this writer.
- :func:`commit_mechanical` — phase `mechanical`. Used for bootstrap,
  banner-tick, scaffold-strip commits, and the coordinator's own
  `# History` / question / command writes.
- :func:`commit_final` — phase `finalize`.

:func:`history_for_file` returns most-recent-first list of commit records
with the parsed trailer, ready for the state machine to scan.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from errors import GitOpsError
from keys import BotIdentity, JobKey, Phase, Trailer

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping, Sequence


# -------------------------------------------------------- data structures


@dataclass
class CommitRecord:
  """
  Single commit entry returned by `history_for_file`.

  Callers inspect the parsed trailers to classify each commit by phase and expert without
  re-running git commands.

  Attributes:
    sha: Full 40-character commit SHA.
    author_name: Git author name as recorded in the commit.
    author_email: Git author email as recorded in the commit.
    subject: First line of the commit message.
    body: Full commit message body including the subject line.
    trailers: Parsed key-value trailers from the commit body, keyed by trailer name.
  """

  sha: str
  author_name: str
  author_email: str
  subject: str
  body: str
  trailers: dict[str, str] = field(default_factory=dict)


# ----------------------------------------------------------- internals


def _run_git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    capture: bool = True,
) -> str:
  """
  Run a `git` command against `repo` and return its stripped stdout.

  Args:
    repo: Absolute path to the repository root.
    args: Positional `git` arguments, in order.
    env: Extra environment variables to overlay on the current process environment.
    capture: Whether to capture stdout/stderr; when `False`, output is inherited.

  Returns:
    The command's stdout with surrounding whitespace stripped.

  Raises:
    GitOpsError: If the `git` command exits with a non-zero status.
  """
  cmd = ["git", "-C", str(repo), *args]
  try:
    proc = subprocess.run(
        cmd,
        check=True,
        capture_output=capture,
        text=True,
        # waiver: stdlib encoding/mode idiom
        env={**__import__("os").environ, **(env or {})},
    )
  except subprocess.CalledProcessError as exc:
    raise GitOpsError(
        f"git command failed: {' '.join(args)}\n"
        f"  stdout: {exc.stdout!r}\n  stderr: {exc.stderr!r}"
    ) from exc
  return (proc.stdout or "").strip()


def _build_message(
    subject: str,
    trailers: Sequence[tuple[str, str]],
) -> str:
  """
  Assemble a commit message from a subject line and trailer key-value pairs.

  Args:
    subject: Commit subject line.
    trailers: Trailer key-value pairs appended after a blank line separating them from the subject.

  Returns:
    The formatted commit message, terminated by a newline.
  """
  parts = [subject]
  if trailers:
    parts.append("")  # blank line separating body from trailers
    for k, v in trailers:
      parts.append(f"{k}: {v}")
  return "\n".join(parts) + "\n"


def _author_flags(author: Mapping[str, str]) -> list[str]:
  """
  Return git `-c` config overrides for a one-shot commit under the named identity.

  Returns:
    List of `-c key=value` strings setting `user.name`, `user.email`, and
    `commit.gpgsign`, suitable for passing directly to a `git` invocation.
  """
  name = author.get(JobKey.NAME, BotIdentity.NAME)
  email = author.get(JobKey.EMAIL, BotIdentity.EMAIL)
  return [
      "-c", f"user.name={name}",
      "-c", f"user.email={email}",
      "-c", "commit.gpgsign=false",
  ]


def _add_and_commit(
    repo: Path,
    path: Path,
    *,
    author: Mapping[str, str],
    message_text: str,
    allow_empty: bool = False,
) -> str:
  """
  Stage `path` and commit with the given message and author identity.

  Returns:
    Full SHA of the newly created commit.
  """
  if path is not None and not allow_empty:
    # waiver: git CLI vocabulary
    _run_git(repo, "add", "--", str(path.relative_to(repo)))
  elif path is not None:
    # `allow_empty` paired with a path means "stage it if anything
    # changed; allow empty if nothing did".
    # waiver: git CLI vocabulary
    _run_git(repo, "add", "--", str(path.relative_to(repo)))
  commit_args = [*_author_flags(author), "commit", "-q", "-m", message_text]
  if allow_empty:
    # waiver: git CLI vocabulary
    commit_args.append("--allow-empty")
  _run_git(repo, *commit_args)
  # waiver: git CLI vocabulary
  return _run_git(repo, "rev-parse", "HEAD")


# --------------------------------------------------- Doc-Review-Phase trailer


def _phase_trailer(
    phase: str,
    *,
    expert: str | None = None,
    round_: int | None = None,
) -> str:
  """
  Format the `Doc-Review-Phase` trailer value.

  Returns:
    Trailer value string: `<phase>` optionally followed by `; expert=<name>`
    and `; round=<N>` segments.
  """
  parts = [phase]
  if expert:
    parts.append(f"expert={expert}")
  if round_ is not None:
    parts.append(f"round={round_}")
  return "; ".join(parts)


def parse_phase_trailer(trailers: Mapping[str, str]) -> tuple[str, str, int | None]:
  """
  Parse the `Doc-Review-Phase` trailer into its component fields.

  Returns:
    Tuple of `(phase, expert, round_)` where `phase` is the empty string when
    no trailer is present (operator commit), `expert` is the empty string when
    the trailer carries no `expert=` segment, and `round_` is `None` when the
    trailer carries no `round=` segment or the value is not parseable as an int.
  """
  raw = trailers.get(Trailer.PHASE, "")
  if not raw:
    return "", "", None
  segments = [s.strip() for s in raw.split(";")]
  phase = segments[0]
  expert = ""
  round_: int | None = None
  for segment in segments[1:]:
    # waiver: regex / format fragment, not a domain key
    if segment.startswith("expert="):
      # waiver: regex / format fragment, not a domain key
      expert = segment[len("expert="):]
    # waiver: regex / format fragment, not a domain key
    elif segment.startswith("round="):
      try:
        # waiver: regex / format fragment, not a domain key
        round_ = int(segment[len("round="):])
      except ValueError:
        round_ = None
  return phase, expert, round_


# ----------------------------------------------------------- commit_* api


def repaint_inline(repo: Path, paths: list[str]) -> list[str]:
  """
  Repaint icon frontmatter for `paths` via the obsidian plugin's `sync-paths` op.

  Resolves the `lazycortex-obsidian` CLI through `$LAZYCORTEX_PLUGIN_DIRS` (the blessed
  cross-plugin contract) and asks it to refresh the named repo-relative notes, so the
  caller can fold the repainted files into the commit it is about to make — no separate
  icons commit, no operator-edit wake from one.

  Notes:
    - Best-effort by design: a consumer without the obsidian plugin, an unset environment,
      or a failing worker yields an empty list and never raises.

  Args:
    repo: Absolute path to the repository root.
    paths: Repo-relative POSIX paths of the notes about to be committed.

  Returns:
    Repo-relative paths whose frontmatter the repaint actually changed; empty when the
    repaint was unavailable, failed, or changed nothing.
  """
  # guard: nothing to repaint — skip the subprocess entirely
  if not paths:
    return []

  # walk the plugin-dir registry for the obsidian CLI; absence means no repaint here
  cli = None
  for entry in os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep):
    # guard: empty segments appear when the variable is unset or ends with a separator
    if not entry:
      continue
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    candidate = Path(entry) / "bin" / "lazycortex-obsidian"
    if candidate.is_file():
      cli = candidate
      break
  # guard: no obsidian plugin on this host — repaint silently unavailable
  if cli is None:
    return []

  # run the repaint and read back which notes actually changed
  try:
    proc = subprocess.run(
        # waiver: the obsidian CLI's subcommand vocabulary, owned by lazycortex-obsidian
        [str(cli), "sync-paths", *paths],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    # guard: a failing worker must never block the caller's commit
    if proc.returncode != 0:
      return []
    # waiver: the obsidian CLI's JSON result vocabulary, owned by lazycortex-obsidian
    touched = json.loads(proc.stdout.strip().splitlines()[-1]).get("touched", [])
  except (OSError, ValueError, IndexError):
    return []
  return [p for p in touched if isinstance(p, str)]


def commit_review_round(
    repo: Path,
    path: Path,
    *,
    round_: int,
    expert: str,
    author: Mapping[str, str],
    history_message: str,
    phase: str = Phase.MAIN,
) -> str:
  """
  Commit the working-tree state of `path` under `expert`'s identity with the review-round phase trailer.

  `phase` is one of `main` or `section`; recorded along with `expert` and `round_` in the single
  `Doc-Review-Phase` trailer.

  Returns:
    Full SHA of the new commit.
  """
  trailers = [
      (Trailer.PHASE, _phase_trailer(phase, expert=expert, round_=round_)),
  ]
  return _add_and_commit(
      repo, path,
      author=author,
      message_text=_build_message(history_message, trailers),
  )


def commit_mechanical(
    repo: Path,
    path: Path,
    *,
    author: Mapping[str, str],
    message: str,
) -> str:
  """
  Commit a dispatcher-side mechanical edit (bootstrap, banner repaint, scaffold strip).

  The commit also carries the icon repaint for the committed note when the obsidian
  plugin is available — one commit, payload and paint together.

  Returns:
    Full SHA of the new commit.
  """
  # fold the note's icon repaint into this same commit so no separate icons commit follows
  for extra in repaint_inline(repo, [str(path.relative_to(repo))]):
    # waiver: git CLI vocabulary
    _run_git(repo, "add", "--", extra)

  # the mechanical-phase trailer marks the commit as the system's own for the recogniser
  trailers = [("Doc-Review-Phase", Phase.MECHANICAL)]
  return _add_and_commit(
      repo, path,
      author=author,
      message_text=_build_message(message, trailers),
  )


def commit_empty(
    repo: Path,
    *,
    round_: int,
    expert: str,
    author: Mapping[str, str],
    message: str,
    phase: str = Phase.MAIN,
) -> str:
  """
  Commit an empty commit recording that `expert` completed round `round_` with no content change.

  `phase` is one of `main` or `section`; see `commit_review_round`.

  Returns:
    Full SHA of the new commit.
  """
  trailers = [
      (Trailer.PHASE, _phase_trailer(phase, expert=expert, round_=round_)),
  ]
  # No path → don't stage; --allow-empty drives the commit through.
  commit_args = [
      *_author_flags(author),
      "commit", "-q", "--allow-empty",
      "-m", _build_message(message, trailers),
  ]
  _run_git(repo, *commit_args)
  # waiver: git CLI vocabulary
  return _run_git(repo, "rev-parse", "HEAD")


def commit_final(
    repo: Path,
    path: Path,
    *,
    author: Mapping[str, str],
    message: str,
) -> str:
  """
  Commit the finalized state of `path` with a `finalize` phase trailer.

  Args:
    repo: Absolute path to the repository root.
    path: Absolute path to the file being committed.
    author: Mapping with `name` and `email` keys for the commit author identity.
    message: Commit subject line.

  Returns:
    Full SHA of the new commit.
  """
  trailers = [("Doc-Review-Phase", Phase.FINALIZE)]
  return _add_and_commit(
      repo, path,
      author=author,
      message_text=_build_message(message, trailers),
  )


# ------------------------------------------------------- history_for_file


_TRAILER_RE = __import__("re").compile(r"^([A-Za-z][\w-]*):\s+(.*)$")


def _parse_trailers(body: str) -> dict[str, str]:
  """
  Pull trailer lines off the bottom of the commit body.

  A real trailer block is a contiguous run of `Key: value` lines at the end of the body,
  preceded by a blank line that separates them from the subject / body prose. Commits that
  are entirely trailer-shaped (a one-line subject like `add: doc`) are rejected to avoid
  misreading the subject as a trailer.

  Returns:
    Dict of trailer key-value pairs, or an empty dict when no valid trailer block is found.
  """
  lines = body.splitlines()
  collected: list[tuple[str, str]] = []
  i = len(lines) - 1
  while i >= 0 and lines[i].strip() == "":
    i -= 1
  while i >= 0:
    match = _TRAILER_RE.match(lines[i])
    if not match:
      break
    collected.append((match.group(1), match.group(2)))
    i -= 1
  if not collected:
    return {}
  # Must be preceded by a blank-line separator AND by at least one
  # non-empty content line before that blank (otherwise the
  # "trailers" are really the whole body).
  if i < 0 or lines[i].strip() != "":
    return {}
  return dict(reversed(collected))


_GIT_LOG_FORMAT = "%H%x00%an%x00%ae%x00%s%x00%B%x1e"


def history_for_file(repo: Path, path: Path) -> list[CommitRecord]:
  """
  Return commits touching `path`, most recent first.

  `path` may not exist on disk (deleted / never created); an empty list is returned in that case.

  Returns:
    List of `CommitRecord` entries in reverse-chronological order, or an empty list when no
    commits touch `path`.
  """
  rel = str(path.relative_to(repo)) if path.is_absolute() else str(path)
  out = _run_git(
      repo,
      # waiver: git CLI vocabulary
      "log",
      f"--format={_GIT_LOG_FORMAT}",
      "--",
      rel,
  )
  if not out:
    return []
  records: list[CommitRecord] = []
  # Records are separated by the record-separator byte (0x1e); inside
  # one record, fields are separated by NUL (0x00).
  for chunk in out.split("\x1e"):
    # waiver: the loop variable is deliberately rebound — each chunk is normalised in place before use
    chunk = chunk.strip("\n")  # noqa: PLW2901
    # guard: the record-separator split yields an empty trailing chunk — skip it rather than emit an empty record
    if not chunk:
      continue
    # waiver: inline numeric literal, not a domain constant
    parts = chunk.split("\x00", 4)
    # guard: skip records that lack all five NUL-delimited fields — a truncated chunk would unpack-crash below
    # waiver: inline numeric literal, not a domain constant
    if len(parts) < 5:
      continue
    sha, an, ae, subject, body = parts
    records.append(
        CommitRecord(
            sha=sha,
            author_name=an,
            author_email=ae,
            subject=subject,
            body=body,
            trailers=_parse_trailers(body),
        )
    )
  return records
