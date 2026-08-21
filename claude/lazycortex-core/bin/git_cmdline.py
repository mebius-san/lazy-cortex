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

  Guarantees:
    - No pathspec is ever misread as an option's value: every token following a bare `--`
      lands here verbatim regardless of its own shape, and a short option that does not accept
      a value never consumes the token that follows it as that value.

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

  # Contract:
  # No pathspec is ever misread as an option's value: every token following a bare `--` lands
  # here verbatim regardless of its own shape, and a short option that does not accept a value
  # never consumes the token after it as that value — that token stays a pathspec.

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

  # Domain(guard.git-staging):
  # # Command substitution is opaque to the invoking command
  # A command substitution is expanded by the shell before the invoked program ever sees it, and the
  # result always arrives as a single word regardless of the punctuation, quoting, or newlines the
  # substitution's own body contains. Any analysis of a command line for the invocations it carries can
  # treat a substitution as one opaque placeholder word without losing information relevant to
  # classifying the invocation — only its presence matters, never its contents. This covers the common
  # pattern of building a long message from a substituted here-document, which would otherwise defeat
  # any attempt to split the command line into words.

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


def _split_unquoted_lines(command: str) -> list[str]:
  """
  Split a Bash command on the newlines that actually separate invocations.

  A newline inside a quoted word belongs to that word — the multi-paragraph commit message of
  `git commit -m "subject<newline><newline>body" -- a.py` is one argument, and cutting it at the
  blank line leaves both halves carrying an unbalanced quote. Only newlines outside quoting
  separate one invocation from the next.

  Args:
    command: The command with substitutions already elided.

  Returns:
    The command's lines, with quoted newlines preserved inside their line. An unterminated quote
    leaves the remainder as one line, so the tokeniser still refuses it and the caller fails closed.
  """
  lines: list[str] = []
  current: list[str] = []
  quote: str | None = None
  i = 0
  while i < len(command):
    ch = command[i]
    # guard: a backslash escapes the next character outside single quotes
    if ch == "\\" and quote != "'" and i + 1 < len(command):
      current.append(command[i:i + 2])
      i += 2
      continue
    if quote is None and ch in "'\"":
      quote = ch
    elif ch == quote:
      quote = None
    # guard: an unquoted newline ends the line; a quoted one is part of the word
    if ch == "\n" and quote is None:
      lines.append("".join(current))
      current = []
      i += 1
      continue
    current.append(ch)
    i += 1
  lines.append("".join(current))
  return lines


def _chunks(command: str) -> list[list[str]] | None:
  """
  Split a Bash command string into per-invocation token lists.

  Command substitutions are elided to a placeholder word first, then unquoted newlines separate
  lines so a multi-line script does not collapse into one invocation while a multi-paragraph
  commit message stays one argument, then each line is tokenised with shell quoting rules and
  split on chain separators. Tokenisation runs with `punctuation_chars` so `git add x; git commit`
  separates even without whitespace around the `;`, and a redirection target never reads as a
  pathspec.

  Args:
    command: The raw Bash command as delivered by Claude Code.

  Returns:
    A list of token lists, one per invocation, or None when the string cannot be tokenised
    (unbalanced quotes).
  """
  out: list[list[str]] = []
  # Substitutions are elided across the whole string first — a heredoc inside one spans lines.
  for line in _split_unquoted_lines(_elide_substitutions(command)):
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

  # Domain(guard.git-staging):
  # # Global option value binding
  # Some options that appear before the subcommand name take a value from the very next word on the
  # command line; others are switches that carry no value at all. Telling the two apart is required to
  # locate where the subcommand name itself begins, since a value word must never be mistaken for the
  # subcommand, and a switch must never be treated as consuming the word that follows it.

  # Domain(guard.git-staging):
  # # Explicit repository targeting overrides the working directory
  # When an invocation names an explicit target repository or working tree, it operates against that
  # named location instead of the directory the caller currently stands in. Any judgment about what the
  # invocation actually affects, including whether it touches a shared index at all, must be made
  # against the named target, never assumed to be the caller's own working directory.

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

  # Domain(guard.git-staging):
  # # Long option value binding
  # A long option's value can be attached to the same word with an equals sign, or given as the
  # following word. When the value is attached, no further word belongs to that option; when it is not,
  # the very next word is consumed as the value rather than treated as a positional argument.

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

  # Domain(guard.git-staging):
  # # Short option clusters and their value binding
  # Several single-letter switches can be bundled into one dash-prefixed word. Within such a cluster,
  # only the specific letters that accept a value ever consume one, and only when that letter is the
  # last member of the cluster — the value is either the remainder of the same word or the following
  # word. A handful of legal short options in this family never take their value from a following word
  # at all; the underlying command-line syntax only accepts their value attached to the same word.
  # Excluding those letters from the value-consuming set keeps a word that follows one of them
  # classified as an ordinary positional argument rather than being swallowed as that option's value.

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

  Guarantees:
    - Every git invocation on the command line is represented exactly once, in the same
      left-to-right order the invocations appear in the command; none is dropped, merged with
      a neighboring invocation, or reordered.
    - Never raises and never returns a partial or best-effort result on unparsable input: when
      the command line cannot be tokenised, parsing returns None so the caller can fail closed.

  Args:
    command: The raw Bash command as delivered by Claude Code.

  Returns:
    One `GitSegment` per git invocation, in command order — empty when the command invokes no
    git at all. None when the command cannot be tokenised, so the caller can fail closed.
  """

  # Contract:
  # A malformed command line never raises and never yields a partial or best-effort segment
  # list. Whenever the line cannot be tokenised — unbalanced quotes, or an unterminated command
  # substitution or backtick — parsing refuses outright and returns None, so the caller can fail
  # closed instead of acting on an incomplete read of the command.

  chunks = _chunks(command)
  # guard: command could not be tokenised — caller must fail closed
  if chunks is None:
    return None

  # Contract:
  # Every git invocation present in the command line is returned exactly once, in the same
  # left-to-right order the invocations appear in the command. No invocation is dropped, merged
  # with a neighboring one, or reordered.

  # accumulate one segment per git invocation found in the command
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

  Guarantees:
    - Never classifies `--amend` on its own; a rewrite of the previous commit without a pathspec
      is judged only by `is_amend`, a separate and independent call.

  Args:
    segment: A parsed segment whose `verb` is `commit`.

  Returns:
    True when the commit would sweep in foreign staged content, False when every committed path
    is named explicitly.
  """

  # Contract:
  # This predicate NEVER classifies `--amend`. A commit that rewrites the previous commit
  # without naming a pathspec is not reported as indexful by this function; a caller that cares
  # about amend semantics MUST call `is_amend` separately — the two judgments are independent
  # and neither implies the other.

  # Domain(guard.git-staging):
  # # What makes a commit indexful
  # A commit is indexful — capable of sweeping in content the caller never explicitly named — under any
  # of three conditions: it folds the whole index or the whole working tree into the snapshot regardless
  # of what was staged, it names a pathspec covering the entire tree (equivalent to naming nothing), or
  # it names no pathspec at all, which commits whatever already sits in the index. Rewriting the previous
  # commit is not judged by this criterion on its own — doing so without a pathspec can be a legitimate
  # reword against an already-clean index, and only the caller, not the command line alone, can know
  # whether the index was clean beforehand.

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

  # Domain(guard.git-staging):
  # # Intent-to-add registers a path without its content
  # Staging a new path does not always mean staging that path's content. One staging form only records
  # that the path now exists — the file becomes tracked, but none of its bytes enter the shared index —
  # while every other staging form copies the file's current content into the index immediately. The
  # distinction matters wherever the concern is what content a shared index actually carries: the
  # registration-only form is safe to perform freely, while every other form commits real bytes that
  # another party did not necessarily intend to share yet.

  return not any(f in _INTENT_TO_ADD_FLAGS for f in segment.flags)


def is_amend(segment: GitSegment) -> bool:
  """
  Report whether a segment carries the amend flag.

  Guarantees:
    - Says nothing about whether the commit is indexful; call `is_indexful_commit` separately
      to determine that — the two judgments are independent.

  Args:
    segment: A parsed segment.

  Returns:
    True when the segment rewrites the previous commit rather than creating a new one.
  """

  # Contract:
  # This predicate says nothing about whether the commit is indexful. A caller that needs that
  # judgment MUST call `is_indexful_commit` separately — the two judgments are independent and
  # neither implies the other.

  # report whether the amend flag is present
  return any(f in AMEND_FLAGS for f in segment.flags)
