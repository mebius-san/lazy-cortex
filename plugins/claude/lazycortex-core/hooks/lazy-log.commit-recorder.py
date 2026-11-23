#!/usr/bin/env python3

"""
PostToolUse hook that records every successful git commit to `.logs/commits.jsonl`.

Fires after any `Bash` command containing a `git commit` invocation (leading, chained like
`git add … && git commit … && git push`, or flag-prefixed like `git -C dir commit`) or after
`mcp__git__git_commit`. Writes one JSON line of commit metadata per commit. The file is the raw commit
feed that `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary` search, and that the daemon's
journal rotation keeps.

The line goes to the journal of the repository that received the commit: for a `Bash` commit, the
directory its `git -C` options name, else the last `cd` before it in the same chain or subshell; for an
MCP commit, its `repo_path`; otherwise the session's working directory. A relative `git -C`, `cd` or
`repo_path` resolves from the session's working directory, which is the payload's `cwd` when that is a
non-empty string. The call is replayed from that directory and from the hook process's own working directory;
of the replays that lead to an existing directory, the first whose repository has a fresh `HEAD` is taken,
else the first inside a git working tree, else the first one. When no replay leads to an existing directory,
the starting directories that exist are weighed the same way, and when none exists, the session's working
directory itself is used. A commit whose directory cannot be resolved, such as one reached through a shell
expansion or `cd -`, is taken to run in the session's working directory. That repository's `hooks.disabled`
decides whether the hook runs.

Notes:
  - No LLM call, no network, fast (~50ms).
  - Runs git read commands in the receiving directory; when that directory holds no readable commit,
    writes one diagnostic line naming it to stderr and records nothing.
  - Never blocks the commit outcome. A journalling failure — an unwritable journal directory or
    lock file, a lock still held past the wait budget, or a failed append — is recorded as an
    incident in the repository's error ledger at `.runtime/errors.jsonl` instead.
  - The read-then-append window is serialised on a sibling lock file, so concurrent runs on one
    commit leave exactly one entry.
  - Creates the `.logs/` directory if missing.
  - Works whether the commit was invoked via `Bash` or via the `mcp__git__git_commit` tool.
"""

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import contextlib
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import TextIO

  from collections.abc import Iterator


# Resolve the sibling bin/ dir so the enablement gate is importable.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import error_ledger  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import hook_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from constants import HookKey, HookName, IncidentKey, IncidentKind, IncidentPhase  # noqa: E402

# Pick the platform's file-lock module: fcntl does not exist on Windows, msvcrt exists only there.
# waiver: platform literal; the lock attempt below branches on the same test
if sys.platform == "win32":
  import msvcrt
else:
  import fcntl


# Freshness window for the failure-path HEAD check: a HEAD younger than this is treated as
# produced by the just-finished chain (the commit succeeded, a later segment failed).
HEAD_FRESHNESS_SECONDS = 60

# Wait budget for the commit-journal lock. A holder does one read-then-append pass, so genuine
# contention clears in milliseconds; a stall past the budget means the holder is wedged, and the
# entry is recorded as lost rather than waited on while the observed tool call hangs.
JOURNAL_LOCK_TIMEOUT_SECONDS = 5.0
JOURNAL_LOCK_POLL_SECONDS = 0.05

# Incident coordinates for a journalling failure. The key folds repeats of one cause into a single
# incident, and the three causes stay separate so an unwritable directory never merges with a stall.
JOURNAL_INCIDENT_PREFIX = "commit-journal"
CAUSE_DIR_UNWRITABLE = "journal_dir_unwritable"
CAUSE_LOCK_TIMEOUT = "journal_lock_timeout"
CAUSE_WRITE_FAILED = "journal_write_failed"

# Tool names of the two calls that can create a commit.
BASH_TOOL = "Bash"
MCP_COMMIT_TOOL = "mcp__git__git_commit"

# Shell control operators and grouping characters; a token made only of these ends one simple command.
SHELL_OPERATOR_CHARS = "();|&\n"
# Characters the tokenizer splits out of words: the operators plus the redirection signs.
SHELL_PUNCTUATION_CHARS = SHELL_OPERATOR_CHARS + "<>"
# Blanks that separate words; a newline is left out so it ends a command the way `;` does.
SHELL_BLANKS = " \t\r"
# Characters that start a shell expansion; a directory argument holding one is known to the shell alone.
SHELL_EXPANSION_CHARS = "$`"
# A leading `NAME=value` word sets the environment of the command after it.
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
# A `git … commit` invocation anywhere in a command line. Each repeated group tolerates one flag between `git`
# and `commit`, with or without a separate value (`-C dir`, `-C "dir with space"`, `-c k=v`); a quoted flag or
# value may hold whitespace.
COMMIT_INVOCATION = re.compile(
  r"\bgit\b(?:\s+-(?:\"[^\"]*\"|'[^']*'|[^\s\"'])+(?:\s+(?:\"[^\"]*\"|'[^']*'|[^-\s]\S*))?)*\s+commit\b",
)

# Command and subcommand words that place and identify a commit.
CD_COMMAND = "cd"
# The `cd` argument that returns to the previous directory, which only the shell remembers.
CD_PREVIOUS = "-"
GIT_COMMAND = "git"
COMMIT_VERB = "commit"
# The git global option that moves git into another directory before it runs.
GIT_DIR_OPTION = "-C"
# Other git global options that take their value as the next word.
GIT_VALUE_OPTIONS = frozenset({ "-c", "--git-dir", "--work-tree", "--namespace", "--config-env" })


def read_commit_info(repo_dir: Path) -> dict | None:
  """
  Return a dictionary describing the `HEAD` commit of a repository, or `None` when no commit is reachable.

  Notes:
    - Runs read-only `git` subprocesses with `repo_dir` as their working directory.

  Args:
    repo_dir: A directory inside the repository whose `HEAD` is read.

  Returns:
    A mapping with the repository root and the commit's identity, message, changed files and change counts.
    Changed files carry their names as git holds them, with a replacement character in place of any byte
    that is no text; a rename or copy is recorded as `old => new` with both full paths. The root keeps such
    bytes undecoded. `None` when `repo_dir` is missing or not inside a git repository, when no commit exists
    yet, or when `git` is not on the executable search path.
  """
  # the path is taken as bytes and decoded here: text mode would turn a carriage return inside it into a line feed
  try:
    root = os.fsdecode(subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
    )).strip()
  except (subprocess.CalledProcessError, OSError):
    return None

  # sha, iso-date, author, subject — joined by NUL so subjects containing tabs survive intact
  try:
    raw = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%H%x00%cI%x00%an <%ae>%x00%s" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
      text = True, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    )
    # waiver: inline numeric literal (maxsplit count), not a domain constant
    sha, date, author, subject = raw.split("\x00", 3)
  except (subprocess.CalledProcessError, ValueError, OSError):
    return None

  # branch the commit landed on; a detached HEAD or missing git leaves it blank
  try:
    branch = subprocess.check_output(
      [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
      text = True, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    ).strip()
  except (subprocess.CalledProcessError, OSError):
    branch = ""

  # commit body below the subject line — trailers and prose the history searches later read
  try:
    body = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%b" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
      text = True, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    )
  except (subprocess.CalledProcessError, OSError):
    body = ""

  # file stats from numstat, NUL-separated so no name is ever quoted or split: each record is insertions,
  # deletions and the name; the output is taken as bytes and decoded here, so a carriage return inside a
  # name stays one and a byte that is not UTF-8 survives as a surrogate escape
  try:
    numstat = os.fsdecode(subprocess.check_output(
      [ "git", "show", "--numstat", "-z", "--format=", "HEAD" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
    ))
  except (subprocess.CalledProcessError, OSError):
    numstat = ""

  # accumulate per-file stats; binary files report "-" instead of a number and contribute zero
  files = []
  total_ins = 0
  total_del = 0
  # waiver: git's NUL record separator, not a domain constant
  records = iter(numstat.split("\0"))
  for record in records:
    # the two counts and the name are tab-separated; only the first two tabs separate, a name may hold more
    # waiver: inline numeric literal (splits after the two count columns), not a domain constant
    parts = record.lstrip("\n").split("\t", 2)
    # guard: a record without both counts and a name column is no file entry
    # waiver: inline numeric literal (numstat column count), not a domain constant
    if len(parts) != 3:
      continue
    ins_raw, del_raw, path = parts

    # a rename or copy leaves the name column empty and gives the old and the new name as the next two records
    if not path:
      old_name = next(records, "")
      path = f"{old_name} => {next(records, '')}"

    # the journal only shows the name, and its file is strict UTF-8 text, so an escaped byte is
    # rendered as a replacement character
    # waiver: stdlib codec and decode-error mode names, not domain constants
    files.append(path.encode("utf-8", "surrogateescape").decode("utf-8", "replace"))
    total_ins += int(ins_raw) if ins_raw.isdigit() else 0
    total_del += int(del_raw) if del_raw.isdigit() else 0

  # one flat record per commit — the shape the ledger line is serialised from
  return {
    "root": root,
    "sha": sha,
    "date": date,
    "author": author,
    "branch": branch,
    "subject": subject,
    "body": body.strip(),
    "files": files,
    "insertions": total_ins,
    "deletions": total_del,
  }


def is_head_fresh(repo_dir: Path) -> bool:
  """
  Report whether a repository's `HEAD` commit was created within the freshness window.

  Notes:
    - Runs a read-only `git` subprocess with `repo_dir` as its working directory.

  Args:
    repo_dir: A directory inside the repository whose `HEAD` is checked.

  Returns:
    True when the committer timestamp of `HEAD` lies within `HEAD_FRESHNESS_SECONDS` of the
    current wall clock. False when the timestamp is older, when the repository has no reachable
    `HEAD` (or `repo_dir` is missing), or when `git` is not on the executable search path.
  """
  try:
    raw = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%ct" ],
      stderr = subprocess.DEVNULL, cwd = repo_dir,
      text = True, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    ).strip()
    committed_at = int(raw)
  except (subprocess.CalledProcessError, OSError, ValueError):
    return False
  return abs(time.time() - committed_at) <= HEAD_FRESHNESS_SECONDS


def record_failure(root: str, cause: str, detail: str) -> None:
  """
  Record one commit-journalling failure as an incident in the repository's error ledger.

  Args:
    root: Absolute path to the repository root whose ledger receives the incident.
    cause: The cause token naming which part of the journalling step failed.
    detail: One-line human-readable description of the failure, including the underlying error.
  """
  # the ledger swallows its own failures, so an unrecordable incident still cannot fail the commit
  error_ledger.record(Path(root), {
    IncidentKey.INCIDENT: f"{JOURNAL_INCIDENT_PREFIX}:{cause}",
    IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.PLUGIN_ERROR,
    IncidentKey.CAUSE: cause,
    IncidentKey.DETAIL: detail,
    # waiver: the hook's own canonical name doubles as the actor label; IncidentActor names daemon subsystems only
    IncidentKey.ACTOR: HookName.COMMIT_RECORDER,
  })


def try_lock(lock: TextIO) -> None:
  """
  Make one non-blocking attempt to take an exclusive lock on the given file.

  Args:
    lock: An open, writable file object to lock.

  Raises:
    OSError: Another holder already has the lock, or the lock could not be taken.
  """
  # one non-blocking attempt; both platforms raise OSError while another holder has the lock
  # waiver: platform literal matches the import branch above
  if sys.platform == "win32":
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
  else:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_lock(lock: TextIO) -> None:
  """
  Release the exclusive lock this process holds on an open lock file.

  Notes:
    - No action is needed on POSIX, where closing the file releases the lock; on Windows the lock
      is released explicitly by this call.

  Args:
    lock: An open, writable file object whose exclusive lock this process holds.
  """
  # Windows frees a byte-range lock on close only after an unspecified delay, so unlock it now;
  # closing the file releases a POSIX flock immediately
  # waiver: platform literal matches the import branch above
  if sys.platform == "win32":
    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def wait_for_lock(lock: TextIO) -> bool:
  """
  Take an exclusive lock on an open lock file, waiting up to the journal lock budget.

  Args:
    lock: An open, writable file object to lock.

  Returns:
    True once the lock is held by this process. False when the wait budget elapsed with the lock
    still held elsewhere, in which case nothing is locked.
  """
  # poll rather than block: a wedged holder must not keep the observed tool call waiting forever
  deadline = time.time() + JOURNAL_LOCK_TIMEOUT_SECONDS
  while True:
    try:
      try_lock(lock)
      return True
    except OSError:
      # guard: budget spent — leave the lock unheld so the caller records a dropped entry
      if time.time() >= deadline:
        return False
      time.sleep(JOURNAL_LOCK_POLL_SECONDS)


@contextlib.contextmanager
def journal_lock(path: str) -> Iterator[bool]:
  """
  Hold the commit journal's lock for the duration of the `with` block.

  Args:
    path: Absolute path of the lock file to take the lock on; created when missing.

  Yields:
    True when the lock is held for the body of the block, False when the wait budget elapsed
    without it. The lock is released when the block exits, however it exits.

  Raises:
    OSError: The lock file could not be opened for writing.
  """
  # waiver: stdlib file-mode / encoding literals, not domain constants
  with open(path, "w", encoding = "utf-8") as lock:
    locked = wait_for_lock(lock)
    try:
      yield locked
    finally:
      # release explicitly: closing the file frees a POSIX lock at once, a Windows one only eventually
      if locked:
        release_lock(lock)


def _expand_dir(base: Path | None, target: str) -> Path | None:
  """
  Return the directory a shell or git argument names, read relative to a base directory.

  Args:
    base: The directory a relative argument is resolved against, or `None` when it is unknown.
    target: The directory argument as written; only a leading `~` is expanded, never an environment variable.

  Returns:
    The named directory; an absolute argument replaces the base. `None` when the argument holds a shell
    expansion (`$` or a backtick) only the shell can resolve, or when it is relative and the base is unknown.
  """
  # guard: a `$` or backtick expansion is resolved by the shell alone, so the directory is unknown
  if any(char in target for char in SHELL_EXPANSION_CHARS):
    return None

  # an absolute argument stands on its own; a relative one needs a known base
  named = Path(os.path.expanduser(target))
  if named.is_absolute():
    return named
  return base / named if base is not None else None


def _remove_shell_comments(command: str) -> str:
  """
  Return a shell command line with its comments removed.

  Reads comments the way bash does: an unquoted `#` that starts a word opens a comment running to the end of its
  line. A `#` inside a word, inside quotes, or escaped is literal text.

  Args:
    command: The shell command line as written.

  Returns:
    The command without the text of each comment; the newline that ends a comment is kept.
  """
  # an unquoted `#` that starts a word opens a comment running to the end of its line, as in bash
  kept: list[str] = []
  quote = ""
  escaped = False
  in_comment = False
  for idx, char in enumerate(command):
    # comment text is dropped up to, not including, the newline that ends it
    if in_comment and char != "\n":
      continue
    in_comment = False

    # a backslash escapes the next character outside single quotes; a quote opens or closes a quoted span
    if escaped:
      escaped = False
    elif char == "\\" and quote != "'":
      escaped = True
    elif quote:
      quote = "" if char == quote else quote
    elif char in "'\"":
      quote = char
    elif char == "#" and (idx == 0 or command[idx - 1] in SHELL_BLANKS + SHELL_PUNCTUATION_CHARS):
      in_comment = True
      continue
    kept.append(char)

  # the command as the shell reads it, comments gone
  return "".join(kept)


def _parse_git_words(words: list[str], cwd: Path | None) -> tuple[str | None, Path | None]:
  """
  Return the subcommand of a `git` simple command and the directory git runs it in.

  Args:
    words: The words of one simple command, starting with the `git` word.
    cwd: The directory the command runs in, or `None` when it is unknown.

  Returns:
    The subcommand word, or `None` when the words run out before one, and the directory after applying
    every `-C` option. The directory is `None` when it is unknown: `cwd` is unknown, or a `-C` value holds
    a shell expansion or is relative to an unknown directory.
  """
  # git applies each `-C` on top of the previous one, starting from the directory git is run in
  target = cwd
  args = iter(words[1:])
  for word in args:
    # the first word that is no option is the subcommand
    if not word.startswith("-"):
      return word, target

    # `-C` moves git, an empty value leaves it in place; other valued options skip their value
    if word == GIT_DIR_OPTION:
      if value := next(args, ""):
        target = _expand_dir(target, value)
    elif word in GIT_VALUE_OPTIONS:
      next(args, None)

  # the words ran out before any subcommand
  return None, target


def parse_commit_dir(command: str, session_dir: Path) -> Path | None:
  """
  Return the directory the first `git commit` of a shell command runs in.

  Shell comments in the command are ignored as bash ignores them, so a commit or `cd` written inside a comment
  is never taken for a real one. Only the text up to and including the commit verb is read, so the commit
  message, a heredoc and later segments never affect the result; an apostrophe there cannot break resolution.

  Args:
    command: The shell command line of a `Bash` call.
    session_dir: The directory the command starts in.

  Returns:
    The directory named by the commit's `git -C` options, else by the last `cd` before it in the same
    chain or subshell, else `session_dir`. `None` when the command holds no `git commit`, when the text
    before the commit verb cannot be split into words, or when the commit's directory is unknown because a
    `git -C` or `cd` argument holds a shell expansion or the commit follows `cd -`.
  """

  # Domain(log.commit-journal):
  # # Directory a shell commit is made in
  # A commit belongs to the repository it was made in, which is not necessarily the session's own.
  # Within one git invocation, each "change directory first" option applies on top of the previous one,
  # starting from the directory git is run in; an empty value leaves the directory in place.
  # Without such an option, the last directory change before the commit in the same chain decides.
  # A parenthesised subshell starts in its parent's directory and gives it back when it closes.
  # Leading environment assignments before a command are not the command itself.
  # A directory argument whose value only the shell knows makes the directory unknown: one holding an expansion
  # (a variable or a command substitution), or a return to the previous directory. Such an argument is never
  # taken literally, and variables are never expanded from the hook's own environment; only the home-directory
  # shorthand is expanded. An absolute argument after that makes the directory known again; a relative one
  # leaves it unknown. A commit made from an unknown directory is placed in the session's directory.
  # Comments are read as the shell reads them. A comment starts only at an unquoted hash mark that begins a word
  # and runs to the end of its line; the line break still ends the command. A hash mark inside a word or inside
  # quotes is an ordinary character. A directory change or a commit written inside a comment never counts, and a
  # commit written inside a comment is never the first commit.
  # Only the command text up to and including the first commit invocation decides where the commit is made. The
  # commit's message, any inline document fed to it and everything after it never count, so their wording, quotes
  # or apostrophes cannot change the answer.

  # comments are removed by the shell's own rule before the commit is looked for, so a commented-out one never counts
  uncommented = _remove_shell_comments(command)

  # guard: no `git … commit` in the command, so there is no commit to place
  if (commit := COMMIT_INVOCATION.search(uncommented)) is None:
    return None

  # only the text up to the commit verb places the commit, so its message, a heredoc and later segments are never
  # split; the split follows the shell, quotes included, with the tokenizer's own comment rule switched off
  lexer = shlex.shlex(uncommented[:commit.end()], posix = True, punctuation_chars = SHELL_PUNCTUATION_CHARS)
  lexer.whitespace_split = True
  lexer.whitespace = SHELL_BLANKS
  lexer.commenters = ""

  # guard: an unbalanced quote leaves the command unsplittable, so no directory can be read from it
  try:
    tokens = list(lexer)
  except ValueError:
    return None

  # walk the simple commands in order, tracking the directory each one runs in; `None` marks it unknown
  cwd: Path | None = session_dir
  outer: list[Path | None] = []
  words: list[str] = []
  for token in [ *tokens, ";" ]:
    # a word, a quoted word or a redirection belongs to the current simple command
    if not token or not set(token) <= set(SHELL_OPERATOR_CHARS):
      words.append(token)
      continue

    # an operator ends the simple command: a `cd` moves the directory, a `git … commit` is the answer
    # and `cd -` returns to a directory only the shell remembers, so it leaves the directory unknown
    head = list(itertools.dropwhile(ENV_ASSIGNMENT.match, words))
    if head == [ CD_COMMAND ]:
      cwd = Path.home()
    elif head and head[0] == CD_COMMAND:
      cwd = None if head[1] == CD_PREVIOUS else _expand_dir(cwd, head[1])
    elif head and os.path.basename(head[0]) == GIT_COMMAND:
      subcommand, git_dir = _parse_git_words(head, cwd)
      if subcommand == COMMIT_VERB:
        return git_dir
    words = []

    # a subshell starts in its parent's directory and hands it back when it closes
    for char in token:
      if char == "(":
        outer.append(cwd)
      elif char == ")" and outer:
        cwd = outer.pop()

  # no simple command was a commit
  return None


def find_receiving_dir(payload: dict) -> Path:
  """
  Return the directory of the repository that received the commit a hook payload reports.

  Notes:
    - The call is replayed from the payload's `cwd` first, then from the hook process's working directory.
    - Without a payload `cwd` that is a non-empty string, only the hook process's working directory is used.
    - The candidates are the replays that lead to an existing directory, without repeats and in replay order;
      when there is none, they are the starting directories that exist.
    - The first candidate whose repository has a fresh `HEAD` is returned; else the first candidate inside a git
      working tree; else the first candidate; else the session directory: the payload `cwd` when that is a
      non-empty string, else the hook process's working directory.
    - Runs read-only `git` subprocesses with each candidate as their working directory.
    - The session directory returned without a candidate is not checked to exist; callers report one that holds
      no readable commit.

  Args:
    payload: The Claude Code hook payload parsed from stdin.

  Returns:
    For `mcp__git__git_commit`, the `repo_path` the call names; for `Bash`, the directory the command's
    commit runs in; otherwise the starting directory. Relative paths resolve from the starting directory
    that the replay used. A commit whose directory is unresolved yields that starting directory. Among several
    candidates the one with a fresh `HEAD` is preferred, then one inside a git working tree. When there is no
    candidate, the session directory itself.
  """

  # Domain(log.commit-journal):
  # # Repository that receives a commit
  # A commit made through the git tool names its repository directly.
  # Relative directories resolve from the session's current directory. That directory is reported after the
  # command ran, so a relative change of directory may already be applied in it: the command is replayed from
  # the reported directory and from the hook's own starting directory. Replays that lead nowhere are dropped, since
  # a directory that does not exist cannot have received a commit; when none leads anywhere, the starting
  # directories themselves are the candidates.
  # A commit made from an unknown directory is placed in the directory the replay starts from.
  # A commit just made leaves its repository with a fresh latest commit, so the first candidate whose repository
  # has a fresh latest commit wins. The first existing directory is not reliable: the reported directory may be
  # sampled before or after the command's own change of directory, and a step up out of the repository would
  # land on its parent. Without a fresh latest commit, the first candidate inside a repository wins; else the
  # first candidate; else the session's own directory.

  # the directories the call is replayed from, in order: the payload `cwd`, then the hook process's own
  # waiver: external-format hook-payload field name, not an internal key
  session_cwd = payload.get("cwd")
  starts = [ Path(session_cwd), Path.cwd() ] if isinstance(session_cwd, str) and session_cwd else [ Path.cwd() ]

  # the replays that lead to an existing directory, in order and without repeats; a missing one cannot have
  # received the commit
  candidates = list(dict.fromkeys(
    found for start in starts if (found := _replay_commit_dir(payload, start)).is_dir()
  ))

  # guard: no replay leads to an existing directory, so the starting directories themselves are the candidates
  if not candidates:
    candidates = list(dict.fromkeys(start for start in starts if start.is_dir()))

  # Decision: the commit's own fresh HEAD picks the candidate, not the first existing directory — the payload
  # `cwd` may be sampled before or after the command's own `cd`, so replaying from it can land on a directory
  # the commit never touched, such as the parent of the repository after `cd ..`

  # the commit just made leaves its repository with a fresh HEAD
  if (fresh := next((found for found in candidates if is_head_fresh(found)), None)) is not None:
    return fresh

  # without a fresh HEAD, a candidate inside a repository wins; else the first candidate, or the session
  # directory, is the one the diagnostic names
  return next(
    (found for found in candidates if _is_inside_repo(found)),
    candidates[0] if candidates else starts[0],
  )


def _is_inside_repo(directory: Path) -> bool:
  """
  Report whether a directory lies inside a git working tree.

  Notes:
    - Runs a read-only `git` subprocess with `directory` as its working directory.

  Args:
    directory: The directory to check.

  Returns:
    True when git finds a working tree around `directory`; False otherwise, including when `git` is missing.
  """
  try:
    subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL, cwd = directory,
    )
  except (subprocess.CalledProcessError, OSError):
    return False
  return True


def _replay_commit_dir(payload: dict, session_dir: Path) -> Path:
  """
  Return the directory a hook payload's commit lands in when its call starts in a given directory.

  Args:
    payload: The Claude Code hook payload parsed from stdin.
    session_dir: The directory the call is taken to start in; relative `cd`, `git -C` and `repo_path` values
      resolve from it.

  Returns:
    For `mcp__git__git_commit`, the `repo_path` the call names; for `Bash`, the directory the command's
    commit runs in; otherwise `session_dir`. `session_dir` is also returned when the commit's directory is
    unresolved. The directory is returned whether or not it exists.
  """
  # an MCP commit names its repository outright
  # waiver: external-format hook-payload field name, not an internal key
  if payload.get("tool_name", "") == MCP_COMMIT_TOOL:
    # waiver: external-format hook-payload and MCP tool-argument names, not internal keys
    repo_path = payload.get("tool_input", {}).get("repo_path")
    return session_dir / os.path.expanduser(repo_path) if isinstance(repo_path, str) and repo_path else session_dir

  # a shell command places its commit through `git -C` and `cd`
  # waiver: external-format hook-payload field names, not internal keys
  return parse_commit_dir(payload.get("tool_input", {}).get("command", ""), session_dir) or session_dir


def is_commit_call(payload: dict) -> bool:
  """
  Report whether a hook payload names a tool call that creates a commit, judged from the tool input alone.

  Args:
    payload: The Claude Code hook payload parsed from stdin, carrying `tool_name` and `tool_input`.

  Returns:
    True for an `mcp__git__git_commit` call and for a `Bash` call whose command holds a commit invocation
    anywhere (leading, chained, or flag-prefixed like `git -C dir commit`); False for every other call.
  """
  # the tool that made the call decides how a commit is recognised
  # waiver: external-format hook-payload field name, not an internal key
  tool_name = payload.get("tool_name", "")

  # an MCP commit call is a commit by definition
  if tool_name == MCP_COMMIT_TOOL:
    return True

  # Decision: a permissive text search, not a full shell parse — a quoted look-alike (`echo "git commit"`)
  # is an accepted false positive, since the commit read that follows still needs a real `HEAD` and the
  # journal's SHA dedup absorbs repeat and spurious firings

  # a shell call is a commit when its command runs the commit verb anywhere, chains included
  # waiver: external-format hook-payload field names, not internal keys
  command = payload.get("tool_input", {}).get("command", "")
  return tool_name == BASH_TOOL and COMMIT_INVOCATION.search(command) is not None


def is_recordable_commit(payload: dict, repo_dir: Path) -> bool:
  """
  Decide whether a commit call left a commit to record in the repository that received it.

  Notes:
    - A failed call runs a read-only `git` subprocess in `repo_dir` to check whether `HEAD` is fresh.

  Args:
    payload: The Claude Code hook payload parsed from stdin, carrying `hook_event_name`, `tool_name` and
      `tool_input`. A `PostToolUseFailure` event marks a call that failed.
    repo_dir: The directory of the repository that received the commit.

  Returns:
    True for a commit call that succeeded, and for a failed one whose `HEAD` in `repo_dir` is nonetheless
    fresh, so a successful commit followed by a failed push still records. False for a call that is no commit
    and for a failed one that left `HEAD` stale.
  """
  # guard: the call creates no commit at all
  if not is_commit_call(payload):
    return False

  # a failed call arrives as PostToolUseFailure, and in a chain the failure belongs to the LAST failed segment,
  # so a successful commit followed by a failed push must still record: a failed call records only when HEAD
  # is fresh (a genuinely failed commit leaves HEAD at the old one; the SHA dedup covers re-commit retries)
  # waiver: external Claude Code hook-event name, not a domain key
  return payload.get(HookKey.HOOK_EVENT_NAME) != "PostToolUseFailure" or is_head_fresh(repo_dir)


def main() -> None:
  """
  Record the commit a hook payload reports in the journal of the repository that received it.

  Never fails the originating tool call: a journalling failure is recorded in that repository's error
  ledger instead of raised, and a receiving directory with no readable commit is reported on stderr.

  Guarantees:
    - The commit-journal read-then-append window is serialised across concurrent hook invocations.
    - Concurrent hook invocations for the same commit never leave a duplicate entry in the journal.
    - An entry the hook could not journal is recorded as an incident in the error ledger, never
      silently dropped.

  Notes:
    - Reads the hook payload from stdin; runs read-only `git` subprocesses only for a call that is a commit.
    - Appends to `<repo-root>/.logs/commits.jsonl` of the receiving repository, creating `.logs/` if missing.
    - Writes one line to stderr naming the receiving directory when it holds no readable commit.
    - Does nothing when the hook is not admitted, the call is no commit or left none, or the receiving
      repository's `hooks.disabled` names the hook.
  """
  # first action, a pure env check: an allow-list that does not name the hook ends an expert spawn here
  # guard: an allow-list regime that does not name this hook
  if not hook_gate.is_admitted(HookName.COMMIT_RECORDER):
    return

  # the hook payload names the tool call that just finished
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    return

  # guard: the tool input names no commit; checked before any directory is resolved, so no git runs for it
  if not is_commit_call(payload):
    return

  # the commit lands in the repository the call names, which need not be the session's
  repo_dir = find_receiving_dir(payload)

  # guard: payload is not a recordable commit
  if not is_recordable_commit(payload, repo_dir):
    return

  # Domain(log.commit-journal):
  # # Receiving repository governs recording
  # The repository that received the commit alone decides whether the commit is recorded: its own block-list
  # of hooks applies, and the settings of the session's repository have no say.
  # When the directory resolved as the receiving one holds no readable commit, for instance because it is not a
  # repository, the hook names that directory in a diagnostic and records nothing.

  # guard: hook disabled by the receiving repository's settings; the session repository's have no say
  if not hook_gate.is_enabled(HookName.COMMIT_RECORDER, cwd = repo_dir):
    return

  # read the commit straight from git rather than trusting the command line
  info = read_commit_info(repo_dir)

  # guard: no commit readable in the receiving directory; name it on stderr instead of exiting silently
  if info is None:
    sys.stderr.write(
      f"{HookName.COMMIT_RECORDER}: no commit readable in {repo_dir} "
      f"(not a git repository, no HEAD, or git missing); nothing recorded\n",
    )
    return

  # the repo root locates the ledger and is dropped from the record itself
  # waiver: one-off commit-record schema field name, not a reusable domain key
  root = info.pop("root")
  # waiver: filesystem path idiom (run-log directory), not a domain constant
  logs_dir = os.path.join(root, ".logs")
  try:
    os.makedirs(logs_dir, exist_ok = True)
  except OSError as error:
    record_failure(root, CAUSE_DIR_UNWRITABLE, f"cannot create the journal directory: {error}")
    return

  # the ledger downstream recall reads from
  # waiver: filesystem filename idiom (commit-ledger file), not a domain constant
  path = os.path.join(logs_dir, "commits.jsonl")

  # Contract:
  # Concurrent hook invocations observing the same commit never leave a duplicate entry
  # for that commit SHA in the journal file. An entry the hook could not journal is
  # recorded as an incident in the error ledger rather than silently dropped.

  # the read-then-append window below is serialised on this lock: two hooks firing on one commit
  # would otherwise each miss the other's line and append a duplicate, and the journal directory is
  # synced, so an unguarded append is not atomic on its own
  try:
    # waiver: lock-file suffix idiom (companion to the commit-ledger file), not a domain constant
    with journal_lock(path + ".lock") as locked:
      # guard: the holder outlived the wait budget — drop the entry, but leave it observable
      if not locked:
        # waiver: one-off commit-record schema field name, not a reusable domain key
        record_failure(root, CAUSE_LOCK_TIMEOUT, f"journal lock held elsewhere; dropped {info['sha']}")
        return

      # idempotency: don't append the same SHA twice (useful if the hook fires multiple times
      # somehow — e.g., for both Bash and MCP on the same commit)
      try:
        with open(path, encoding = "utf-8") as f:
          for line in f:
            try:
              entry = json.loads(line)
            except ValueError:
              continue

            # guard: SHA already recorded — skip duplicate append
            # waiver: one-off commit-record schema field name, not a reusable domain key
            if entry.get("sha") == info["sha"]:
              return
      except OSError:
        # an unreadable journal leaves nothing to dedup against; the append below reports the rest
        pass

      # append one JSON line; a write failure degrades to a missing entry, never a failed commit
      try:
        with open(path, "a", encoding = "utf-8") as f:
          f.write(json.dumps(info) + "\n")
      except OSError as error:
        record_failure(root, CAUSE_WRITE_FAILED, f"cannot append to the journal: {error}")
        return
  except OSError as error:
    record_failure(root, CAUSE_DIR_UNWRITABLE, f"cannot open the journal lock: {error}")
    return


if __name__ == "__main__":
  # noinspection PyBroadException
  try:
    main()
  # waiver: hook must never fail the tool call it observes — any crash degrades to a silent no-op
  except Exception:
    pass
  sys.exit(0)
