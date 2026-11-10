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
- They commit under an explicit pathspec, never the shared index as a
  whole: the path argument, plus the extra paths and icon repaints that
  `commit_mechanical` folds in.
- The commit subject is taken from the `message` argument verbatim;
  the `Doc-Review-Phase` trailer is appended in the commit body,
  separated by a blank line.
- The author identity for the commit is set per-call via the `-c`
  flag so concurrent commits under different bot identities don't
  fight over `git config`.

Trailer format — every commit carries exactly one `Doc-Review-Phase`
trailer:

    Doc-Review-Phase: <phase>

Phases used by each commit kind:

- :func:`commit_mechanical` — phase `mechanical`. Used for bootstrap,
  banner-tick, scaffold-strip commits, and the coordinator's own
  `# History` / question / command writes.
- :func:`commit_final` — phase `finalize`.

:func:`read_history_for_file` returns most-recent-first list of commit records
with the parsed trailer.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from errors import GitOpsError  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from keys import BotIdentity, EnvVar, JobKey, Paths, Phase, Plugin, Trailer  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping, Sequence


# -------------------------------------------------------- data structures


@dataclass
class CommitRecord:
  """
  Single commit entry returned by `read_history_for_file`.

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
        env={**os.environ, **(env or {})}, encoding = "utf-8",
    )
  except subprocess.CalledProcessError as error:
    raise GitOpsError(
        f"git command failed: {' '.join(args)}\n"
        f"  stdout: {error.stdout!r}\n  stderr: {error.stderr!r}"
    ) from error
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

  # Domain(review.lifecycle):
  # # Commit phase vocabulary
  # Every commit the review system makes carries exactly one phase token recording which
  # step of the review cycle produced it. A mechanical commit — bootstrap, a banner repaint,
  # a scaffold strip, the coordinator's own history and command writes — carries no writer
  # identity, since no round advanced. A finalize commit closes the cycle and carries no
  # writer identity either. A commit with no phase token at all was not made by the review
  # system.

  # subject first, then the phase trailer set off by a blank line
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
    extra_paths: tuple[str, ...] = (),
) -> str:
  """
  Stage `path` and commit it — plus `extra_paths` — under an explicit pathspec.

  The checkout's index is shared with concurrent writers (routines, expert subprocesses,
  the operator), so the commit always names its paths: a bare commit would snapshot
  whatever the index happens to hold and publish a stranger's parked work.

  Args:
    repo: Absolute path to the repository root.
    path: Absolute path to the file being committed.
    author: Mapping with `name` and `email` keys for the commit author identity.
    message_text: Full commit message, trailers included.
    extra_paths: Repo-relative paths already staged by the caller, folded into the
      commit's pathspec alongside `path`.

  Returns:
    Full SHA of the newly created commit.
  """

  # Domain(runtime.git-safety):
  # # A review commit never snapshots the shared index
  # The checkout's index is shared with routines, expert subprocesses and the operator, so
  # whatever it holds at commit time is not the review system's to publish. A review commit
  # therefore carries exactly the document it commits plus the extra paths its caller staged
  # for it. Content anyone else has staged stays in the index, unpublished.

  # stage the document, then commit under the explicit pathspec
  # waiver: git CLI vocabulary
  _run_git(repo, "add", "--", str(path.relative_to(repo)))
  _run_git(
      repo, *_author_flags(author),
      # waiver: git CLI vocabulary
      "commit", "-q", "-m", message_text,
      "--", str(path.relative_to(repo)), *extra_paths,
  )
  # waiver: git CLI vocabulary
  return _run_git(repo, "rev-parse", "HEAD")


# ----------------------------------------------------------- commit_* api


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin version string.

  Args:
    name: Version string as the install registry records it.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


# waiver: external Claude Code registry path, not an internal key
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"


def installed_plugin_root(name: str) -> Path | None:
  """
  Resolve a plugin's installed source root from Claude Code's plugin registry.

  The registry (`~/.claude/plugins/installed_plugins.json`) records one entry per project and
  version that installed the plugin, each naming its `installPath`; the highest recorded version
  wins. The plugin cache itself is never searched: it keeps every version ever installed, so a walk
  across it returns copies the registry no longer names.

  Args:
    name: Plugin name without its `@<marketplace>` suffix.

  Returns:
    The recorded install root when it exists on disk, else None.
  """
  registry = Path.home() / _INSTALLED_PLUGINS_REL
  try:
    data = json.loads(registry.read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return None
  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  # waiver: field of Claude Code's external registry schema, not an internal key
  plugins = data.get("plugins", data) if isinstance(data, dict) else {}
  records = [
    rec
    for key, entries in plugins.items() if key.split("@", 1)[0] == name
    # waiver: field of Claude Code's external registry schema, not an internal key
    for rec in (entries or []) if isinstance(rec, dict) and rec.get("installPath")
  ]
  # guard: the plugin was never installed on this machine
  if not records:
    return None
  # waiver: fields of Claude Code's external registry schema, not internal keys
  best = max(records, key = lambda rec: _version_sort_key(str(rec.get("version", ""))))
  # waiver: field of Claude Code's external registry schema, not an internal key
  root = Path(str(best["installPath"]))
  return root if root.is_dir() else None


def resolve_core_cli() -> Path | None:
  """
  Find the `lazycortex-core` CLI binary.

  Returns:
    The path to the resolved binary, preferring `$LAZYCORTEX_PLUGIN_DIRS` over the dev-vault sibling
    tree and that over the install registry, or `None` when no lookup finds one.
  """
  # env stage — the plugin source trees the runtime daemon exports come first
  for entry in os.environ.get(EnvVar.PLUGIN_DIRS, "").split(os.pathsep):
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not entry:
      continue
    cli = Path(entry) / Paths.BIN_DIR / Plugin.CORE
    if cli.is_file():
      return cli

  # dev-vault stage — this file sits at plugins/claude/lazycortex-review/bin/, so core's own bin/ is two
  # levels up and back down the sibling tree; it precedes the registry (§ 2b) so a checkout runs the
  # sources at hand rather than whatever version happens to be installed
  sibling = Path(__file__).resolve().parents[2] / Plugin.CORE / Paths.BIN_DIR / Plugin.CORE
  if sibling.is_file():
    return sibling

  # registry stage — the install root Claude Code's plugin registry records for core
  root = installed_plugin_root(Plugin.CORE)

  # guard: core was never installed on this machine — nothing further to try
  if root is None:
    return None
  cli = root / Paths.BIN_DIR / Plugin.CORE
  return cli if cli.is_file() else None


def require_core_cli() -> Path:
  """
  Resolve the `lazycortex-core` CLI file, or fail.

  Returns:
    Path of the core CLI file.

  Raises:
    RuntimeError: When none of the three lookup stages finds a core CLI; the message names all three.
  """
  cli = resolve_core_cli()

  # guard: no lookup stage found a binary — whatever the caller needs from core cannot happen
  if cli is None:
    raise RuntimeError(
        "lazycortex-core CLI not resolvable: $LAZYCORTEX_PLUGIN_DIRS yields no match, no "
        "dev-vault sibling tree carries bin/lazycortex-core, and the plugin registry records no "
        "lazycortex-core install with a bin/lazycortex-core entry."
    )
  return cli


def repaint_inline(repo: Path, paths: list[str]) -> list[str]:
  """
  Repaint icon frontmatter for `paths` via the obsidian plugin's `sync-paths` op.

  Resolves the `lazycortex-obsidian` CLI through `$LAZYCORTEX_PLUGIN_DIRS` (the blessed
  cross-plugin contract), falling back to the dev-vault sibling tree and then to the install
  root Claude Code's plugin registry records, and asks it to refresh the named repo-relative notes, so the
  caller can fold the repainted files into the commit it is about to make — no separate icons
  commit, no operator-edit wake from one.

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
  for entry in os.environ.get(EnvVar.PLUGIN_DIRS, "").split(os.pathsep):
    # guard: empty segments appear when the variable is unset or ends with a separator
    if not entry:
      continue
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    candidate = Path(entry) / "bin" / "lazycortex-obsidian"
    if candidate.is_file():
      cli = candidate
      break

  # dev-vault fallback — a checkout runs the sources at hand, never an installed copy (§ 2b);
  # this file sits at plugins/claude/lazycortex-review/bin/, so the sibling tree is two levels up
  if cli is None:
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    sibling = Path(__file__).resolve().parents[2] / "lazycortex-obsidian/bin/lazycortex-obsidian"
    if sibling.is_file():
      cli = sibling

  # registry fallback — a session (hook, skill) has no daemon export to walk
  if cli is None:
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    root = installed_plugin_root("lazycortex-obsidian")
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    installed = None if root is None else root / "bin" / "lazycortex-obsidian"
    if installed is not None and installed.is_file():
      cli = installed

  # guard: no obsidian plugin on this host — repaint silently unavailable
  if cli is None:
    return []

  # run the repaint and read back which notes actually changed
  try:
    proc = subprocess.run(
        # waiver: the obsidian CLI's subcommand vocabulary, owned by lazycortex-obsidian
        [sys.executable, str(cli), "sync-paths", *paths],
        cwd=repo, capture_output=True, text=True, check=False, encoding = "utf-8",
    )

    # guard: a failing worker must never block the caller's commit
    if proc.returncode != 0:
      return []
    # waiver: the obsidian CLI's JSON result vocabulary, owned by lazycortex-obsidian
    touched = json.loads(proc.stdout.strip().splitlines()[-1]).get("touched", [])
  except (OSError, ValueError, IndexError):
    return []
  return [p for p in touched if isinstance(p, str)]


def commit_mechanical(
    repo: Path,
    path: Path,
    *,
    author: Mapping[str, str],
    message: str,
    extra_paths: tuple[str, ...] = (),
) -> str:
  """
  Commit a mechanical edit made by the review system itself (bootstrap, banner repaint, scaffold strip).

  The commit also carries the icon repaint for the committed note when the obsidian
  plugin is available — one commit, payload and paint together — plus every path named in
  `extra_paths`: the attachments a landing put beside the document ride the document's own
  commit rather than a second one.

  Args:
    repo: Absolute path to the repository root.
    path: Absolute path to the document being committed.
    author: Mapping with `name` and `email` keys for the commit author identity.
    message: Commit subject, written verbatim.
    extra_paths: Repo-relative paths to commit alongside `path`.

  Returns:
    Full SHA of the new commit.
  """

  # Domain(review.coordinator):
  # # Icon repaint rides the mechanical commit
  # A note's icon repaint is folded into the same commit as the mechanical edit that
  # triggered it rather than committed on its own. A separate commit would carry a foreign
  # identity the coordinator does not recognize as one of the review system's own, and an
  # unrecognized identity reads as an operator edit — waking the coordinator over a change
  # nobody made. Riding the same commit keeps the repaint invisible to wake detection.

  # fold the note's icon repaint and the landed attachments into this same commit so no
  # separate commit — and no operator-edit wake off a foreign identity — follows
  repainted = repaint_inline(repo, [str(path.relative_to(repo)), *extra_paths])
  extras = tuple(dict.fromkeys([*extra_paths, *repainted]))
  for extra in extras:
    # waiver: git CLI vocabulary
    _run_git(repo, "add", "--", extra)

  # the mechanical-phase trailer marks the commit as the system's own for the recogniser
  trailers = [(Trailer.PHASE, Phase.MECHANICAL)]
  return _add_and_commit(
      repo, path,
      author=author,
      message_text=_build_message(message, trailers),
      extra_paths=extras,
  )


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
  trailers = [(Trailer.PHASE, Phase.FINALIZE)]
  return _add_and_commit(
      repo, path,
      author=author,
      message_text=_build_message(message, trailers),
  )


# ------------------------------------------------------- read_history_for_file


_TRAILER_RE = re.compile(r"^([A-Za-z][\w-]*):\s+(.*)$")


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


def read_history_for_file(repo: Path, path: Path) -> list[CommitRecord]:
  """
  Return commits touching `path`, most recent first.

  `path` may not exist on disk (deleted / never created); an empty list is returned in that case.

  Guarantees:
    - Commits are ordered most-recent-first.

  Returns:
    List of `CommitRecord` entries in reverse-chronological order, or an empty list when no
    commits touch `path`.
  """

  # Contract:
  # Returned commits are ordered most-recent-first (reverse-chronological).

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
