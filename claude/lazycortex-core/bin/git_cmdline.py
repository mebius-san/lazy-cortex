"""
Shell-command parser for the git verbs the staging guard cares about.

The guard has to decide whether a Bash command snapshots the shared git index. That question
cannot be answered by a leading-verb regex: `git commit -m "fix -- stuff"` carries a `--` inside
a quoted message, `git add x && git commit` hides the commit behind a chain, and `-am` bundles a
message option into a short-flag cluster.

Public surface: parse_segments, is_indexful_commit, adds_content. A command this module cannot
tokenize yields None so callers can fail closed.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# --- Option tables ------------------------------------------------------------

# Characters shlex reports as standalone punctuation tokens. A token made only of these ends the
# current invocation: chains (`&&`, `;`, `|`), subshells, and redirections alike.
_SEPARATOR_CHARS = set("&|;()<>")

# Stand-in for an elided command substitution. The shell hands a quoted substitution to the command
# as one word, so one placeholder word is a faithful reduction.
_SUBSTITUTION_PLACEHOLDER = "SUBSTITUTION"

# Global `git` options consuming a following token, e.g. `git -C dir commit`.
_GIT_GLOBAL_WITH_ARG = {
  "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix",
}

# Long options whose value lives in the following token when not attached with `=`.
_LONG_WITH_ARG = {
  "--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date",
  "--cleanup", "--template", "--fixup", "--squash", "--trailer", "--pathspec-from-file",
  "--chmod",
}

# Short options whose value is either attached (`-mfix`) or the following token (`-m fix`).
# `-S` / `-u` are absent deliberately: git only accepts their values attached, so a following
# token is a pathspec, not an argument.
_SHORT_WITH_ARG = { "m", "F", "C", "c", "t" }

# Commit flags that fold the whole index (or the whole worktree) into the snapshot.
_INDEXFUL_COMMIT_FLAGS = { "-a", "--all", "-i", "--include" }

# Pathspecs that cover the whole tree — an indexful commit in disguise.
WHOLE_TREE_PATHSPECS = { ".", "./", ":/", ":/.", "*", "..", "../" }

# `git add` flags that register a path without staging its content.
_INTENT_TO_ADD_FLAGS = { "-N", "--intent-to-add" }

AMEND_FLAGS = { "--amend" }


# --- Types --------------------------------------------------------------------

@dataclass(frozen = True)
class GitSegment:
  """
  One `git <verb>` invocation extracted from a Bash command line.

  Attributes:
    verb: The git subcommand (`add`, `commit`, `rm`, `mv`, `reset`, ...); empty when the
      invocation carried no subcommand at all.
    flags: Every option token belonging to the subcommand, normalised so a bundled short
      cluster appears as its individual `-x` members and a `--long=value` form appears as
      `--long`.
    pathspecs: Positional arguments left after option consumption, in command order.
    repo_dir: Value of the global `-C <dir>` option when the invocation carried one, naming the
      repository the command actually targets. None when the invocation runs against the caller's
      working directory.
  """
  verb: str
  flags: tuple[str, ...]
  pathspecs: tuple[str, ...]
  repo_dir: str | None = None


# --- Tokenising ---------------------------------------------------------------

def _elide_substitutions(command: str) -> str:
  """
  Replace every command substitution with a single placeholder word.

  A substitution is opaque to the invoked command — the shell expands it and hands the result over
  as one word. Reducing it to a placeholder lets the rest of the line tokenise, which matters
  because the house form for a long commit message is `git commit -m "$(cat <<'EOF' … EOF)"`:
  the heredoc body carries newlines, quotes, and `--` that would otherwise defeat the tokeniser
  and force the whole command into the fail-closed path.

  Args:
    command: The raw Bash command as delivered by Claude Code.

  Returns:
    The command with each `$(...)` and backtick substitution replaced by one placeholder word. An
    unbalanced substitution is left verbatim so tokenisation still fails and the caller fails
    closed.
  """
  out: list[str] = []
  i = 0
  while i < len(command):
    if command.startswith("$(", i):
      end = _matching_paren(command, i + 2)
      # guard: unbalanced — leave it verbatim so the tokeniser still refuses the command
      if end is None:
        return command
      out.append(_SUBSTITUTION_PLACEHOLDER)
      i = end + 1
      continue
    if command[i] == "`":
      end = command.find("`", i + 1)
      # guard: unterminated backtick — same fail-closed treatment
      if end < 0:
        return command
      out.append(_SUBSTITUTION_PLACEHOLDER)
      i = end + 1
      continue
    out.append(command[i])
    i += 1
  return "".join(out)


def _matching_paren(command: str, start: int) -> int | None:
  """
  Find the index of the `)` closing a substitution opened before `start`.

  Args:
    command: The raw Bash command.
    start: Index of the first character inside the substitution.

  Returns:
    Index of the closing parenthesis, or None when the substitution is unbalanced.
  """
  depth = 1
  i = start
  while i < len(command):
    if command.startswith("$(", i):
      depth += 1
      i += 2
      continue
    if command[i] == "(":
      depth += 1
    elif command[i] == ")":
      depth -= 1
      # guard: this parenthesis closes the outermost substitution
      if depth == 0:
        return i
    i += 1
  return None


def _chunks(command: str) -> list[list[str]] | None:
  """
  Split a Bash command string into per-invocation token lists.

  Command substitutions are elided to a placeholder word first, then lines are separated so a
  multi-line script does not collapse into one invocation, then each line is tokenised with shell
  quoting rules and split on chain separators. Tokenisation runs with `punctuation_chars` so
  `git add x; git commit` separates even without whitespace around the `;`, and a redirection
  target never reads as a pathspec.

  Args:
    command: The raw Bash command as delivered by Claude Code.

  Returns:
    A list of token lists, one per invocation, or None when the string cannot be tokenised
    (unbalanced quotes).
  """
  out: list[list[str]] = []
  # Substitutions are elided across the whole string first — a heredoc inside one spans lines.
  for line in _elide_substitutions(command).splitlines():
    lexer = shlex.shlex(line, posix = True, punctuation_chars = True)
    lexer.whitespace_split = True
    try:
      tokens = list(lexer)
    except ValueError:
      return None
    current: list[str] = []
    for tok in tokens:
      # guard: a punctuation-only token ends this invocation
      if tok and set(tok) <= _SEPARATOR_CHARS:
        out.append(current)
        current = []
        continue
      current.append(tok)
    out.append(current)
  return [ c for c in out if c ]


def _strip_global_options(tokens: list[str]) -> tuple[list[str], str | None]:
  """
  Drop the `git` executable token and any global options preceding the subcommand.

  Args:
    tokens: Token list of one invocation whose first token is the `git` executable.

  Returns:
    A pair `(rest, repo_dir)` where `rest` starts at the subcommand (empty when the invocation
    carried none) and `repo_dir` is the `-C <dir>` value when one was given. The directory
    matters because it names the repository the command actually targets, which need not be the
    one the caller is standing in.
  """
  rest = tokens[1:]
  repo_dir: str | None = None
  i = 0
  while i < len(rest):
    tok = rest[i]
    # guard: reached the subcommand
    if not tok.startswith("-"):
      return rest[i:], repo_dir
    name = tok.split("=", 1)[0]
    attached = "=" in tok
    # waiver: git CLI vocabulary, not a domain constant
    if name == "-C":
      repo_dir = tok.split("=", 1)[1] if attached else (rest[i + 1] if i + 1 < len(rest) else None)
    # `-C dir` / `-c k=v` style: the value is the next token unless attached with `=`.
    if name in _GIT_GLOBAL_WITH_ARG and not attached:
      i += 2
      continue
    i += 1
  return [], repo_dir


def _consume_options(tokens: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
  """
  Separate option tokens from positional arguments in a subcommand's argument list.

  Args:
    tokens: The subcommand's arguments, i.e. everything after the verb.

  Returns:
    A pair `(flags, pathspecs)` where `flags` holds every option in normalised form and
    `pathspecs` holds the positional arguments in command order. Everything after a bare `--`
    is a pathspec regardless of its shape.
  """
  flags: list[str] = []
  paths: list[str] = []
  i = 0
  while i < len(tokens):
    tok = tokens[i]
    # guard: end-of-options marker — every remaining token is a pathspec
    if tok == "--":
      paths.extend(tokens[i + 1:])
      break
    # guard: positional argument
    if not tok.startswith("-") or tok == "-":
      paths.append(tok)
      i += 1
      continue
    if tok.startswith("--"):
      name = tok.split("=", 1)[0]
      flags.append(name)
      i += 2 if (name in _LONG_WITH_ARG and "=" not in tok) else 1
      continue
    i += _consume_short_cluster(tok, flags)
  return tuple(flags), tuple(paths)


def _consume_short_cluster(tok: str, flags: list[str]) -> int:
  """
  Expand one short-option cluster into individual flags and report how many tokens it spans.

  Args:
    tok: A single-dash option token, possibly bundling several short options (`-am`).
    flags: Accumulator the expanded `-x` members are appended to.

  Returns:
    The number of tokens the cluster consumes — 2 when a value-taking option ends the cluster
    without an attached value, 1 otherwise.
  """
  for pos, ch in enumerate(tok[1:], start = 1):
    flags.append(f"-{ch}")
    # guard: this option takes a value — attached remainder, else the following token
    if ch in _SHORT_WITH_ARG:
      return 1 if tok[pos + 1:] else 2
  return 1


# --- Public surface -----------------------------------------------------------

def parse_segments(command: str) -> list[GitSegment] | None:
  """
  Extract every `git <verb>` invocation from a Bash command line.

  Args:
    command: The raw Bash command as delivered by Claude Code.

  Returns:
    One `GitSegment` per git invocation, in command order — empty when the command invokes no
    git at all. None when the command cannot be tokenised, so the caller can fail closed.
  """
  chunks = _chunks(command)
  # guard: command could not be tokenised — caller must fail closed
  if chunks is None:
    return None
  segments: list[GitSegment] = []
  for tokens in chunks:
    # guard: invocation is not git
    # waiver: git CLI vocabulary, not a domain constant
    if tokens[0].rsplit("/", 1)[-1] != "git":
      continue
    rest, repo_dir = _strip_global_options(tokens)
    # guard: bare `git` with no subcommand
    if not rest:
      segments.append(GitSegment(verb = "", flags = (), pathspecs = (), repo_dir = repo_dir))
      continue
    flags, paths = _consume_options(rest[1:])
    segments.append(
      GitSegment(verb = rest[0], flags = flags, pathspecs = paths, repo_dir = repo_dir)
    )
  return segments


def is_indexful_commit(segment: GitSegment) -> bool:
  """
  Report whether a `git commit` segment snapshots content the caller did not name explicitly.

  A commit is indexful when it folds in the whole index or worktree (`-a`, `-i`), when it names
  no pathspec at all, or when its pathspec covers the whole tree. `--amend` without a pathspec
  is not classified here — an amend may legitimately reword the previous commit against a clean
  index, which only the caller can check.

  Args:
    segment: A parsed segment whose `verb` is `commit`.

  Returns:
    True when the commit would sweep in foreign staged content, False when every committed path
    is named explicitly.
  """
  # guard: -a / -i fold the whole index or worktree into the snapshot
  if any(f in _INDEXFUL_COMMIT_FLAGS for f in segment.flags):
    return True
  # guard: a whole-tree pathspec is an indexful commit in disguise
  if any(p in WHOLE_TREE_PATHSPECS for p in segment.pathspecs):
    return True
  return not segment.pathspecs


def adds_content(segment: GitSegment) -> bool:
  """
  Report whether a `git add` segment stages file content rather than only registering a path.

  Args:
    segment: A parsed segment whose `verb` is `add`.

  Returns:
    True for any form that writes content into the index; False for the intent-to-add form,
    which records the path without its content.
  """
  return not any(f in _INTENT_TO_ADD_FLAGS for f in segment.flags)


def is_amend(segment: GitSegment) -> bool:
  """
  Report whether a segment carries the amend flag.

  Args:
    segment: A parsed segment.

  Returns:
    True when the segment rewrites the previous commit rather than creating a new one.
  """
  return any(f in AMEND_FLAGS for f in segment.flags)
