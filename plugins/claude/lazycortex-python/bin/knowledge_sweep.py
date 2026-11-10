#!/usr/bin/env python3

from __future__ import annotations

from typing import Literal

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import pcf  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The three places a sweep scope can come from, and the outcomes of the commit verb
ScopeSource = Literal["explicit", "domains-globs", "all-python"]
CommitStatus = Literal["committed", "noop", "commit-skipped", "refused"]


# The reserved parking group: never a dictionary entry and never a refile target
RESERVED_GROUP = "unfiled"

# The commit subject the sweep lands its edits under; fixed, so downstream routines can recognise the commit
COMMIT_SUBJECT = "docs(py): backfill Domain/Contract knowledge markers"

# File name of the pre-run snapshot inside the git dir
SNAPSHOT_NAME = "lazy-python.knowledge-sweep.json"

# Scope sources, in precedence order
SOURCE_EXPLICIT: ScopeSource = "explicit"
SOURCE_DOMAINS_GLOBS: ScopeSource = "domains-globs"
SOURCE_ALL_PYTHON: ScopeSource = "all-python"

# Block kinds the inventory reports
KIND_DOMAIN = "domain"
KIND_CONTRACT = "contract"

# Copies of the header patterns in lazycortex-wiki's domains.py (a copy, not an import: plugin boundary);
# a test pins the literals equal
_DOMAIN_HEADER_RE = re.compile(r"^\s*#\s*Domain\s*\(\s*([A-Za-z0-9_.-]+)\s*\)\s*:")
_CONTRACT_HEADER_RE = re.compile(r"^\s*#\s*Contract:\s*$")
_BLOCK_TITLE_RE = re.compile(r"^\s*#\s*#\s*(.+?)\s*$")

# A block-continuation line, and the comment prefix stripped from a body line
_COMMENT_LINE_RE = re.compile(r"^\s*#")
_COMMENT_PREFIX_RE = re.compile(r"^\s*# ?")

# One group-name segment: the characters the Domain header pattern admits, minus the dot that separates segments
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# A line split that keeps each line's own terminator, so a rewrite reproduces the file byte for byte
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+$")

# The heading a newly created dictionary opens with
_DICTIONARY_TITLE = "# Domain groups"

# The dictionary markers: a group heading, its tag line, a comment line
_HEADING_PREFIX = "## "
_TAGS_PREFIX = "Tags:"
_HTML_COMMENT_PREFIX = "<!--"

# Git-dir entries whose presence marks a merge, rebase, cherry-pick, or revert in progress
_TRANSACTION_MARKERS = ( "MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD" )

# Exit codes of the CLI
_EXIT_OK = 0
_EXIT_REFUSED = 1
_EXIT_USAGE = 2

# Read from stdin instead of a file
_STDIN_ARG = "-"

# The refusal payload of each verb: its own keys, empty, plus the reason
_REFUSAL_KEYS: dict[str, dict[str, object]] = {
  "scope": { "files": [], "source": None, "dictionary": None, "dictionary_exists": False, "snapshot": None },
  "inventory": { "blocks": [], "groups": {}, "unfiled": [], "unknown_groups": {} },
  "dictionary-apply": {
    "added": [], "renamed": [], "removed": [], "reglossed": [], "created": False, "touched_paths": [],
  },
  "refile-headers": { "rewritten": [], "touched_paths": [] },
  "commit": { "sha": None, "paths": [], "held": [] },
}

# ----------------------------------------------------------------------------------------
class SweepRefusedError(Exception):
  """
  Refusal of a sweep verb, carrying a machine-readable reason.

  Signals that a verb cannot proceed, either because the repository state forbids it or because an input document is
  malformed.

  Attributes:
    reason: Machine-readable refusal code the skill branches on.
    detail: Human-readable specifics of the refusal.
  """

  def __init__(self, reason: str, *, detail: str = "") -> None:
    """
    Create a refusal from a reason code and optional specifics.

    Args:
      reason: Machine-readable refusal code.
      detail: Human-readable specifics of the refusal.
    """
    super().__init__(f"{reason}: {detail}" if detail else reason)

    # the machine-readable refusal code the skill branches on, and the human-readable specifics
    self.reason: str = reason
    self.detail: str = detail


# ----------------------------------------------------------------------------------------
@dataclass
class Scope:
  """
  Set of Python files a sweep covers, together with where that selection came from.

  Attributes:
    files: Repo-relative paths of the files in scope, sorted.
    source: Origin of the selection: explicit paths, configured domain code globs, or every Python file.
  """

  files: list[str]
  source: ScopeSource


# ----------------------------------------------------------------------------------------
@dataclass
class Block:
  """
  Knowledge block found in a source file.

  A `Domain(...)` or `Contract:` comment block, located by file and line.

  Attributes:
    path: Repo-relative path of the file holding the block.
    line: 1-based line of the block's header.
    kind: Block kind, domain or contract.
    group: Dictionary group named in a domain block's header.
    title: Title line of a domain block.
    body: Block text without the comment prefixes.
  """

  path: str
  line: int
  kind: str
  group: str | None
  title: str | None
  body: str


# ----------------------------------------------------------------------------------------
@dataclass
class Inventory:
  """
  Knowledge blocks in scope and how they are filed against the dictionary.

  Attributes:
    blocks: Every block in scope order.
    groups: Dictionary groups mapped to their one-line glosses.
    unfiled: Domain blocks parked in the reserved group.
    unknown_groups: Domain blocks filed under a group the dictionary does not list, keyed by that group.
  """

  blocks: list[Block]
  groups: dict[str, str]
  unfiled: list[Block]
  unknown_groups: dict[str, list[Block]]


# ----------------------------------------------------------------------------------------
@dataclass
class DictionaryOps:
  """
  Edits requested against the domain-groups dictionary.

  Groups the additions, renames, removals, and gloss replacements a caller asks for in one request.

  Attributes:
    add: Pairs of a new group name and its gloss.
    rename: Old group name mapped to its new name.
    remove: Names of the groups to drop.
    gloss: Group name mapped to its replacement gloss.
  """

  add: list[tuple[str, str]] = field(default_factory = list)
  rename: dict[str, str] = field(default_factory = dict)
  remove: list[str] = field(default_factory = list)
  gloss: dict[str, str] = field(default_factory = dict)

  @classmethod
  def from_json(cls, data: object) -> DictionaryOps:
    """
    Build the edit set from a decoded ops document.

    Args:
      data: Decoded JSON value, expected to be an object with the optional keys `add`, `rename`, `remove`, `gloss`.

    Returns:
      The validated edit set.

    Raises:
      SweepRefusedError: If the document is not an object, carries an unknown key, or holds a value of the wrong
        shape.
    """
    # guard: the ops document is a JSON object, nothing else
    if not isinstance(data, dict):
      raise SweepRefusedError("invalid_input", detail = "ops must be a JSON object")
    unknown = set(data) - { "add", "rename", "remove", "gloss" }

    # guard: an unknown key is a typo the caller would otherwise never learn about
    if unknown:
      raise SweepRefusedError("invalid_input", detail = f"unknown ops keys: {sorted(unknown)}")

    # each `add` entry names a group and its gloss
    add: list[tuple[str, str]] = []
    for entry in _expect_list(data.get("add", []), "add"):
      # guard: an add entry is an object carrying both strings
      if not isinstance(entry, dict) or not isinstance(entry.get("group"), str) \
          or not isinstance(entry.get("gloss"), str):
        raise SweepRefusedError("invalid_input", detail = "each add entry needs string `group` and `gloss`")
      add.append(( entry["group"], entry["gloss"] ))

    # the remaining three keys are plain string maps and a string list
    rename = _expect_str_map(data.get("rename", {}), "rename")
    gloss = _expect_str_map(data.get("gloss", {}), "gloss")
    remove = _expect_list(data.get("remove", []), "remove")

    # guard: every removed group is named by a string
    if not all(isinstance(group, str) for group in remove):
      raise SweepRefusedError("invalid_input", detail = "remove must list strings")
    return cls(add = add, rename = rename, remove = list(remove), gloss = gloss)

  def is_empty(self) -> bool:
    """
    Report whether the edit set requests no change.

    Returns:
      True when no addition, rename, removal, or gloss replacement is requested.
    """
    return not ( self.add or self.rename or self.remove or self.gloss )


# ----------------------------------------------------------------------------------------
@dataclass
class DictionaryResult:
  """
  Outcome of applying dictionary edits.

  Attributes:
    added: Groups that were added.
    renamed: Renames that were applied, each written as `old->new`.
    removed: Groups that were removed.
    reglossed: Groups whose gloss was replaced.
    created: Whether the dictionary file was created by the run.
    touched_paths: Paths of the files the run wrote.
  """

  added: list[str] = field(default_factory = list)
  renamed: list[str] = field(default_factory = list)
  removed: list[str] = field(default_factory = list)
  reglossed: list[str] = field(default_factory = list)
  created: bool = False
  touched_paths: list[str] = field(default_factory = list)


# ----------------------------------------------------------------------------------------
@dataclass
class Assignment:
  """
  Instruction to file one Domain block under a given group.

  Attributes:
    path: Repo-relative path of the file holding the block.
    line: 1-based line of the block's header.
    group: Group to file the block under.
  """

  path: str
  line: int
  group: str


# ----------------------------------------------------------------------------------------
@dataclass
class RefileResult:
  """
  Outcome of refiling Domain block headers.

  Attributes:
    rewritten: One record per rewritten header, with its path, line, old group, and new group.
    touched_paths: Repo-relative paths of the files the run rewrote.
  """

  rewritten: list[dict] = field(default_factory = list)
  touched_paths: list[str] = field(default_factory = list)


# ----------------------------------------------------------------------------------------
@dataclass
class CommitResult:
  """
  Outcome of the commit verb.

  Attributes:
    status: Whether the commit landed, had nothing to commit, was skipped, or was refused.
    sha: Hash of the created commit.
    paths: Paths the commit carries, or would carry had it not been skipped or refused.
    held: Paths left out because the operator had them dirty before the run and the run changed them again.
    reason: Machine-readable refusal code.
    detail: Human-readable specifics of the refusal.
  """

  status: CommitStatus
  sha: str | None = None
  paths: list[str] = field(default_factory = list)
  held: list[str] = field(default_factory = list)
  reason: str | None = None
  detail: str | None = None


# ----------------------------------------------------------------------------------------
@dataclass
class _Entry:
  """
  Dictionary group entry located among the dictionary's lines.

  Attributes:
    group: Group name taken from the entry's heading.
    heading: Index of the heading line.
    gloss: Index of the gloss line.
  """

  group: str
  heading: int
  gloss: int | None


def _expect_list(value: object, key: str) -> list:
  """
  Return a copy of a decoded JSON array, refusing any other value.

  Args:
    value: Decoded JSON value to check.
    key: Name of the document key the value came from, used in the refusal message.

  Returns:
    Copy of the list.

  Raises:
    SweepRefusedError: If the value is not a list.
  """
  # guard: the key holds a JSON array
  if not isinstance(value, list):
    raise SweepRefusedError("invalid_input", detail = f"`{key}` must be a list")
  return list(value)


def _expect_str_map(value: object, key: str) -> dict[str, str]:
  """
  Return a copy of a decoded JSON object whose keys and values are all strings.

  Args:
    value: Decoded JSON value to check.
    key: Name of the document key the value came from, used in the refusal message.

  Returns:
    Copy of the mapping.

  Raises:
    SweepRefusedError: If the value is not a string-to-string mapping.
  """
  # guard: the key holds a string-to-string map
  if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
    raise SweepRefusedError("invalid_input", detail = f"`{key}` must map strings to strings")
  return dict(value)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
  """
  Run a git command in the repository and return the finished process.

  Args:
    repo: Directory to run git in.
    args: Git arguments following the `git` executable.
    check: Whether a non-zero exit is a refusal rather than a result to inspect.

  Returns:
    Finished process with its output captured as text.

  Raises:
    SweepRefusedError: If `check` is set and git exits non-zero.
  """
  proc = subprocess.run(
    [ "git", *args ], cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
  )

  # guard: a failed git call the caller depends on is a refusal, never a silent empty answer
  if check and proc.returncode != 0:
    raise SweepRefusedError("git_failed", detail = f"git {' '.join(args)}: {proc.stderr.strip()}")
  return proc


def _query_git_paths(repo: Path, *args: str) -> list[str]:
  """
  List the paths a git command prints as NUL-separated output.

  Args:
    repo: Directory to run git in.
    args: Git arguments following the `git` executable.

  Returns:
    Paths in the order git printed them.

  Raises:
    SweepRefusedError: If git exits non-zero.
  """
  # NUL-separated output keeps paths with spaces or non-ASCII characters unquoted
  return [ path for path in _git(repo, *args).stdout.split("\0") if path ]


def _split_lines(text: str) -> list[str]:
  """
  Split text into lines that keep their own terminators.

  Args:
    text: Text to split.

  Returns:
    Lines whose concatenation reproduces the text exactly.
  """
  return _LINE_RE.findall(text)


def _read_text(path: Path) -> str:
  """
  Read a UTF-8 file without translating its line endings.

  Args:
    path: File to read.

  Returns:
    File content as written.
  """
  # newline="" keeps CRLF and lone CR as they are, so a rewrite never normalises line endings
  with open(path, encoding = "utf-8", newline = "") as handle:
    return handle.read()


def _atomic_write(path: Path, text: str) -> None:
  """
  Write text to a file so that a reader never sees a partly written file.

  Notes:
    - Creates missing parent directories.
    - An existing file keeps its permission bits.
    - A failed write leaves the target as it was.

  Args:
    path: File to write.
    text: Full new content, written without line-ending translation.
  """
  path.parent.mkdir(parents = True, exist_ok = True)

  # a temp file beside the target, then a rename: a reader never sees a half-written file
  fd, tmp_name = tempfile.mkstemp(dir = str(path.parent), prefix = f".{path.name}.", suffix = ".tmp")
  try:
    with os.fdopen(fd, "w", encoding = "utf-8", newline = "") as handle:
      handle.write(text)

    # the replacement keeps the original's permission bits
    if path.exists():
      os.chmod(tmp_name, path.stat().st_mode & 0o7777)
    os.replace(tmp_name, path)
  # a failed write leaves the target as it was and no temp file behind
  except BaseException:
    if os.path.exists(tmp_name):
      os.unlink(tmp_name)
    raise


def _rel(repo: Path, path: Path) -> str:
  """
  Express a path relative to the repository when it lies inside it.

  Args:
    repo: Repository root.
    path: Path to express.

  Returns:
    Posix repo-relative path, or the path as given when it lies outside the repository.
  """
  # a path inside the repo is reported repo-relative; one outside it stays absolute
  try:
    return path.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return str(path)


def _load_settings(repo: Path) -> dict:
  """
  Load the repository's settings file, treating a missing or unusable one as empty.

  Args:
    repo: Repository root.

  Returns:
    Settings mapping, empty when the file is missing, unreadable, malformed, or not a JSON object.
  """
  settings = repo / pcf.LAZY_SETTINGS_REL

  # guard: no settings file configures nothing
  if not settings.is_file():
    return {}
  try:
    data = json.loads(settings.read_text(encoding = "utf-8"))
  # unreadable or malformed settings configure nothing
  except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    return {}
  return data if isinstance(data, dict) else {}


def resolve_scope(repo: Path, explicit: list[str]) -> Scope:
  """
  Select the files a sweep covers.

  Uses the explicit paths when given, otherwise the code globs configured for the domain tooling, otherwise every
  tracked Python file. Files the checker excludes from checking are never in scope.

  Args:
    repo: Repository root.
    explicit: Repo-relative paths named by the operator, empty to use the configured scope.

  Returns:
    Scope with its sorted files and the source that won.

  Raises:
    SweepRefusedError: If git cannot list the files.
  """

  # Domain(repo.file-enumeration):
  # # Where a knowledge sweep looks
  # A sweep covers one scope chosen by precedence, first hit wins: the paths the operator named,
  # then the code globs the domain tooling is configured to read, then every tracked Python file.
  # Whichever wins, a path the checker excludes from checking is left out too, so the sweep never
  # marks a file the checks will never look at. The winning source is reported, because a file
  # missing from the sweep may be excluded or simply outside the configured globs.

  # the winning source and the candidate files it yields
  source: ScopeSource
  if explicit:
    source = SOURCE_EXPLICIT
    candidates = _query_git_paths(
      repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *explicit,
    )
  else:
    # walk wiki -> domains -> code, treating any non-object level as unconfigured
    code: object = _load_settings(repo)
    for key in ( "wiki", "domains", "code" ):
      code = code.get(key) if isinstance(code, dict) else None
    globs = [ glob for glob in code if isinstance(glob, str) and glob ] if isinstance(code, list) else []
    if globs:
      source = SOURCE_DOMAINS_GLOBS
      # `:(glob)` gives `*` a one-component reach and `**` a zero-or-more-components reach
      candidates = _query_git_paths(repo, "ls-files", "-z", "--", *( f":(glob){glob}" for glob in globs ))
    else:
      source = SOURCE_ALL_PYTHON
      candidates = _query_git_paths(repo, "ls-files", "-z", "--", "*.py")

  # the checker's exclusions apply on top of whichever source won; matched against the repo-relative path,
  # since a substring of the checkout's own location would otherwise drop every file
  configured = [ sub for sub in pcf.load_config(str(repo)).get("exclude", []) if isinstance(sub, str) and sub ]
  excludes = [ *pcf.HARDCODED_EXCLUDES, *configured ]
  files = sorted({
    path for path in candidates
    if path.endswith(".py") and not any(sub in path for sub in excludes)
  })
  return Scope(files = files, source = source)


def _parse_entries(lines: list[str]) -> list[_Entry]:
  """
  Locate the group entries a dictionary declares.

  Args:
    lines: Dictionary lines with their terminators.

  Returns:
    Entries in file order; the reserved group never appears among them.
  """

  # Domain(wiki.domains):
  # # How the dictionary declares a group
  # Each entry is announced by its own `## <group>` heading, and the first prose line beneath it is
  # the group's one-line gloss; sub-headings, tag lines and comments are not prose. The reserved
  # parking group is never an entry, even when the file lists it.

  # sweep the lines: a heading opens an entry, the first prose line under it is its gloss
  entries: list[_Entry] = []
  current: _Entry | None = None
  for idx, raw in enumerate(lines):
    line = raw.strip()

    # a group heading opens a new entry; the reserved group opens none
    if line.startswith(_HEADING_PREFIX):
      group = line[len(_HEADING_PREFIX):].strip()
      current = None if group == RESERVED_GROUP else _Entry(group = group, heading = idx, gloss = None)
      if current is not None:
        entries.append(current)
      continue

    # prose outside an entry, blank lines, sub-headings, tag lines and comments carry no gloss
    if current is None or current.gloss is not None or not line \
        or line.startswith(( "#", _TAGS_PREFIX, _HTML_COMMENT_PREFIX )):
      continue
    current.gloss = idx
  return entries


def read_groups(dictionary: Path) -> dict[str, str]:
  """
  Read the groups a dictionary declares together with their glosses.

  Args:
    dictionary: Path of the dictionary file.

  Returns:
    Group names mapped to gloss text, empty when the file does not exist; a group with no prose has an empty gloss.
  """
  # guard: no dictionary file lists no group
  if not dictionary.is_file():
    return {}

  # the parsed entries, each mapped to its gloss text
  lines = _split_lines(_read_text(dictionary))
  return {
    entry.group: lines[entry.gloss].strip() if entry.gloss is not None else ""
    for entry in _parse_entries(lines)
  }


def _comment_lines(text: str) -> set[int]:
  """
  Find the lines of source text that consist solely of a comment.

  Args:
    text: Python source text.

  Returns:
    1-based line numbers, empty when the text does not tokenize.
  """
  # the tokenizer separates real comments from string literals and docstrings that merely look like them
  try:
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
  # a file that does not tokenize has no comment the sweep can trust
  except (tokenize.TokenError, IndentationError, SyntaxError):
    return set()

  # 1-based numbers of the lines whose only content is a comment
  return {
    token.start[0] for token in tokens
    if token.type == tokenize.COMMENT and token.line.lstrip().startswith("#")
  }


def _strip_body(line: str) -> str:
  """
  Remove the comment prefix and trailing whitespace from a block line.

  Args:
    line: Comment line of a knowledge block.

  Returns:
    Line text without the prefix.
  """
  return _COMMENT_PREFIX_RE.sub("", line.rstrip("\r\n"), count = 1).rstrip()


def _read_file_blocks(repo: Path, rel: str) -> list[Block]:
  """
  Collect the knowledge blocks of one source file.

  Args:
    repo: Repository root.
    rel: Repo-relative path of the file.

  Returns:
    Blocks in file order, empty when the file cannot be read as text.
  """
  try:
    text = _read_text(repo / rel)
  # an unreadable or non-text file yields no block
  except (OSError, UnicodeDecodeError):
    return []
  lines = [ line.rstrip("\r\n") for line in _split_lines(text) ]
  comments = _comment_lines(text)

  # Domain(pytool.marker-grammar):
  # # Where a knowledge block starts and ends
  # A knowledge block is a run of adjacent comment lines opened by a `Domain(<group>):` or bare
  # `Contract:` header. It runs while the following lines are comments and ends at the first line
  # that is not one, or at the next header of either kind. A Domain block's first body line, when it
  # is a `# # <title>` line, is its title. Text inside a string literal is never a block.

  # sweep the real comment lines: a header opens a block, adjacent comment lines extend it
  blocks: list[Block] = []
  idx = 0
  while idx < len(lines):
    domain = _DOMAIN_HEADER_RE.match(lines[idx]) if idx + 1 in comments else None
    contract = _CONTRACT_HEADER_RE.match(lines[idx]) if idx + 1 in comments and not domain else None

    # not a block header — keep sweeping
    if not domain and not contract:
      idx += 1
      continue
    start = idx
    idx += 1

    # the body: adjacent comment lines up to the next header of either kind
    body: list[str] = []
    while idx < len(lines) and idx + 1 in comments and _COMMENT_LINE_RE.match(lines[idx]) \
        and not _DOMAIN_HEADER_RE.match(lines[idx]) and not _CONTRACT_HEADER_RE.match(lines[idx]):
      body.append(lines[idx])
      idx += 1

    # a Domain block's leading `# # <title>` line is its title, not body
    title = _BLOCK_TITLE_RE.match(body[0]) if domain and body else None
    if title:
      body = body[1:]
    blocks.append(Block(
      path = rel,
      line = start + 1,
      kind = KIND_DOMAIN if domain else KIND_CONTRACT,
      group = domain.group(1) if domain else None,
      title = title.group(1) if title else None,
      body = "\n".join(_strip_body(line) for line in body),
    ))
  return blocks


def build_inventory(repo: Path, files: list[str], dictionary: Path) -> Inventory:
  """
  Collect the knowledge blocks of the given files and file them against the dictionary.

  Args:
    repo: Repository root.
    files: Repo-relative paths of the files in scope.
    dictionary: Path of the dictionary file.

  Returns:
    Inventory of the blocks, the dictionary groups, the parked blocks, and the blocks under unlisted groups.
  """
  # every block in scope order, and the dictionary it is filed against
  blocks = [ block for rel in files for block in _read_file_blocks(repo, rel) ]
  groups = read_groups(dictionary)

  # the two broken filings: parked blocks, and blocks under a group the dictionary does not list
  domain_blocks = [ block for block in blocks if block.kind == KIND_DOMAIN and block.group is not None ]
  unknown: dict[str, list[Block]] = {}
  for block in domain_blocks:
    if block.group != RESERVED_GROUP and block.group not in groups:
      unknown.setdefault(str(block.group), []).append(block)
  return Inventory(
    blocks = blocks,
    groups = groups,
    unfiled = [ block for block in domain_blocks if block.group == RESERVED_GROUP ],
    unknown_groups = unknown,
  )


def _validate_name(group: str) -> None:
  """
  Validate a dictionary group name.

  Args:
    group: Proposed group name.

  Raises:
    SweepRefusedError: If the name is the reserved group, has fewer than two segments, or has an empty or illegal
      segment.
  """

  # Domain(wiki.domains):
  # # What a dictionary group may be called
  # A group name is a dot hierarchy of at least two segments — the subject area, then the topic
  # inside it — each made of the characters a `Domain(…)` header admits. The reserved parking
  # group is never a name the dictionary may list.

  # guard: the reserved parking group is never listed
  if group == RESERVED_GROUP:
    raise SweepRefusedError("reserved_group", detail = f"`{RESERVED_GROUP}` is reserved and never listed")
  segments = group.split(".")

  # guard: a single segment names an area with no topic, or a topic with no area
  if len(segments) < 2:
    raise SweepRefusedError("single_segment", detail = f"`{group}` needs at least two dot-separated segments")

  # guard: every segment is non-empty and made of header-legal characters
  if not all(_SEGMENT_RE.match(segment) for segment in segments):
    raise SweepRefusedError("invalid_name", detail = f"`{group}` has an empty or illegal segment")


def _validate_gloss(group: str, gloss: str) -> None:
  """
  Validate a dictionary group gloss.

  Args:
    group: Group the gloss belongs to, used in the refusal message.
    gloss: Proposed gloss.

  Raises:
    SweepRefusedError: If the gloss is empty or spans more than one line.
  """
  # guard: a gloss is one non-empty line
  if not gloss.strip() or "\n" in gloss or "\r" in gloss:
    raise SweepRefusedError("invalid_gloss", detail = f"gloss for `{group}` must be one non-empty line")


def _newline_of(lines: list[str]) -> str:
  """
  Return the line terminator a file uses.

  Args:
    lines: File lines with their terminators.

  Returns:
    CRLF or LF as the first terminated line shows, LF when no line is terminated.
  """
  # the file's own line terminator, taken from its first terminated line
  for line in lines:
    if line.endswith("\r\n"):
      return "\r\n"
    if line.endswith("\n"):
      return "\n"
  return "\n"


def _build_entry_map(lines: list[str]) -> dict[str, _Entry]:
  """
  Index the dictionary entries by group name.

  Args:
    lines: Dictionary lines with their terminators.

  Returns:
    Entries keyed by group name.

  Raises:
    SweepRefusedError: If a group heading appears more than once.
  """
  entries = _parse_entries(lines)
  mapping = { entry.group: entry for entry in entries }

  # guard: a file that lists one heading twice has no single entry to edit
  if len(mapping) != len(entries):
    raise SweepRefusedError("duplicate_group", detail = "the dictionary lists a group heading more than once")
  return mapping


def _require_entry(mapping: dict[str, _Entry], group: str) -> _Entry:
  """
  Look up the entry of a listed group.

  Args:
    mapping: Entries keyed by group name.
    group: Group to look up.

  Returns:
    Entry of the group.

  Raises:
    SweepRefusedError: If the group is the reserved group or is not listed.
  """
  # guard: the reserved parking group is never an entry an op could edit
  if group == RESERVED_GROUP:
    raise SweepRefusedError("reserved_group", detail = f"`{RESERVED_GROUP}` is reserved and never listed")

  # guard: an op on a group the dictionary does not list has nothing to edit
  if group not in mapping:
    raise SweepRefusedError("unknown_group", detail = f"`{group}` is not listed in the dictionary")
  return mapping[group]


def _is_blank(line: str) -> bool:
  """
  Report whether a line holds only whitespace.

  Args:
    line: Line to test.

  Returns:
    True when the line is empty or whitespace.
  """
  return not line.strip()


def _remove_entry(lines: list[str], entry: _Entry) -> list[str]:
  """
  Drop an entry's heading and gloss together with the blank lines that separate it from its neighbours.

  Args:
    lines: Dictionary lines with their terminators.
    entry: Entry to remove.

  Returns:
    Lines without the entry.
  """
  # the entry's own lines: the heading through its gloss
  start = entry.heading
  end = ( entry.gloss if entry.gloss is not None else entry.heading ) + 1

  # the blank lines after it go with it; for the last entry, the blank lines before it instead
  after = end
  while after < len(lines) and _is_blank(lines[after]):
    after += 1
  if after < len(lines):
    end = after
  else:
    while start > 0 and _is_blank(lines[start - 1]):
      start -= 1
  return lines[:start] + lines[end:]


def apply_dictionary(dictionary: Path, ops: DictionaryOps) -> DictionaryResult:
  """
  Apply a set of edits to the dictionary file.

  Guarantees:
    - The edit set is all-or-nothing: if any edit is refused, the file is left exactly as it was.
    - Lines that no edit changes, adds, or removes are written back byte for byte, line endings included.

  Notes:
    - Edits apply in a fixed order: renames, removals, gloss replacements, additions.
    - A missing file is created when an edit adds a group; it opens with the `# Domain groups` heading, then a blank
      line, then the entries.

  Args:
    dictionary: Path of the dictionary file.
    ops: Edits to apply.

  Returns:
    Outcome of the edits; empty, with no file written, when the edit set requests nothing.

  Raises:
    SweepRefusedError: If an edit names the reserved or an unlisted group, gives an invalid name or gloss, or would
      list a group twice.
  """

  # Contract:
  # The edit set is applied all-or-nothing: when any edit is refused, the dictionary file is left exactly as it was,
  # with no partial result on disk.
  # Every line that no edit changes, adds, or removes is preserved byte for byte, line endings included.

  # guard: no ops leave the file untouched
  if ops.is_empty():
    return DictionaryResult()

  # the file as lines with their terminators, so every untouched line is written back byte for byte;
  # a missing file starts from the dictionary heading alone
  exists = dictionary.is_file()
  lines = _split_lines(_read_text(dictionary)) if exists else [ f"{_DICTIONARY_TITLE}\n" ]
  newline = _newline_of(lines)
  result = DictionaryResult(created = not exists)

  # renames rewrite the heading line only; the gloss stays
  mapping = _build_entry_map(lines)
  for old, new in ops.rename.items():
    entry = _require_entry(mapping, old)
    _validate_name(new)

    # guard: a rename onto a listed group would list it twice
    if new in mapping:
      raise SweepRefusedError("duplicate_group", detail = f"`{new}` is already listed")
    terminator = lines[entry.heading][len(lines[entry.heading].rstrip("\r\n")):]
    lines[entry.heading] = f"{_HEADING_PREFIX}{new}{terminator}"
    mapping = _build_entry_map(lines)
    result.renamed.append(f"{old}->{new}")

  # removals drop an entry's heading and gloss, one at a time against the shrinking file
  for group in ops.remove:
    lines = _remove_entry(lines, _require_entry(mapping, group))
    mapping = _build_entry_map(lines)
    result.removed.append(group)

  # gloss edits rewrite the gloss line, or add one under a heading that had none
  for group, text in ops.gloss.items():
    entry = _require_entry(mapping, group)
    _validate_gloss(group, text)
    if entry.gloss is None:
      lines[entry.heading + 1:entry.heading + 1] = [ newline, f"{text}{newline}" ]
    else:
      terminator = lines[entry.gloss][len(lines[entry.gloss].rstrip("\r\n")):] or newline
      lines[entry.gloss] = f"{text}{terminator}"
    mapping = _build_entry_map(lines)
    result.reglossed.append(group)

  # additions append at the end, one blank line apart from whatever precedes them
  for group, text in ops.add:
    _validate_name(group)
    _validate_gloss(group, text)

    # guard: a listed group is never added a second time
    if group in mapping:
      raise SweepRefusedError("duplicate_group", detail = f"`{group}` is already listed")
    if lines and not lines[-1].endswith(( "\n", "\r" )):
      lines[-1] += newline
    if lines and not _is_blank(lines[-1]):
      lines.append(newline)
    lines.extend([ f"{_HEADING_PREFIX}{group}{newline}", newline, f"{text}{newline}" ])
    mapping = _build_entry_map(lines)
    result.added.append(group)

  # every op validated: write once
  _atomic_write(dictionary, "".join(lines))
  result.touched_paths = [ str(dictionary) ]
  return result


def refile_headers(repo: Path, files: list[str], dictionary: Path, *,
                   renames: dict[str, str], assign: list[Assignment]) -> RefileResult:
  """
  Move Domain blocks to other dictionary groups by rewriting the group name in their header lines.

  Only the group name inside the header changes.

  Guarantees:
    - The refile is all-or-nothing: a refile that cannot be applied in full is not applied at all.
    - A refused target or assignment writes no file.
    - A write that fails part-way restores every file already rewritten to its original content.

  Args:
    repo: Repository root.
    files: Repo-relative paths of the files in scope.
    dictionary: Path of the dictionary file.
    renames: Old group name mapped to the new one, applied to every block filed under the old group.
    assign: Per-block target groups, taking precedence over renames.

  Returns:
    Headers rewritten and files touched.

  Raises:
    SweepRefusedError: If a target is the reserved or an unlisted group, an assignment misses a Domain header in
      scope, or one header is assigned two different groups.
  """

  # Contract:
  # A refile is applied all-or-nothing: when a target or an assignment is refused, no file is written,
  # and when a write fails part-way, every file already rewritten is restored to its original content
  # before the failure propagates.

  # Domain(pytool.marker-grammar):
  # # Refiling moves a block, it never rewrites it
  # Refiling a knowledge block changes the group name inside its header and nothing else: the
  # indentation, the comment prefix, the spacing inside the parentheses, any tags after the colon,
  # the title line and the body stay exactly as written. A block may only move to a group the
  # dictionary lists, never back into the reserved parking group.

  groups = read_groups(dictionary)

  # every target must be a listed group, and never the parking slot
  for target in [ *renames.values(), *( item.group for item in assign ) ]:
    # guard: the parking slot is never a refile target
    if target == RESERVED_GROUP:
      raise SweepRefusedError("reserved_group", detail = f"`{RESERVED_GROUP}` is never a refile target")

    # guard: a block may only move into a group the dictionary lists
    if target not in groups:
      raise SweepRefusedError("unlisted_group", detail = f"`{target}` is not listed in the dictionary")

  # every Domain header in scope, keyed by its position
  headers = {
    ( block.path, block.line ): block
    for block in build_inventory(repo, files, dictionary).blocks if block.kind == KIND_DOMAIN
  }

  # the point assignments, each on a real header and none contradicting another
  targets: dict[tuple[str, int], str] = {}
  for item in assign:
    key = ( item.path, item.line )

    # guard: an assignment must land on a Domain header inside the scope
    if key not in headers:
      raise SweepRefusedError(
        "no_domain_header", detail = f"{item.path}:{item.line} is not a Domain header in scope",
      )

    # guard: one line cannot be sent to two groups
    if targets.get(key, item.group) != item.group:
      raise SweepRefusedError(
        "conflicting_assign", detail = f"{item.path}:{item.line} is assigned two different groups",
      )
    targets[key] = item.group

  # the rewrites: an assignment wins over a rename for its block
  plan: dict[str, list[tuple[int, str, str]]] = {}
  for key, block in headers.items():
    new = targets.get(key) or renames.get(str(block.group))
    if new and new != block.group:
      plan.setdefault(block.path, []).append(( block.line, str(block.group), new ))

  # every edit validated in memory first: rewrite the group-name span of each header line and nothing else
  result = RefileResult()
  rewrites: list[tuple[str, str, str]] = []
  for rel in sorted(plan):
    original = _read_text(repo / rel)
    lines = _split_lines(original)
    for line_no, old, new in plan[rel]:
      match = _DOMAIN_HEADER_RE.match(lines[line_no - 1])

      # guard: the inventory matched this header a moment ago; a file changed underneath stops the run
      if match is None:
        raise SweepRefusedError("file_changed", detail = f"{rel}:{line_no} no longer holds a Domain header")
      lines[line_no - 1] = lines[line_no - 1][:match.start(1)] + new + lines[line_no - 1][match.end(1):]
      result.rewritten.append({ "path": rel, "line": line_no, "old": old, "new": new })
    rewrites.append(( rel, original, "".join(lines) ))

  # the writes: a failure mid-way puts back every file already written before it propagates
  written: list[tuple[str, str]] = []
  try:
    for rel, original, text in rewrites:
      _atomic_write(repo / rel, text)
      written.append(( rel, original ))
  except BaseException:
    for rel, original in reversed(written):
      _atomic_write(repo / rel, original)
    raise
  result.touched_paths.extend(rel for rel, _, _ in rewrites)
  return result


def _query_git_dir_path(repo: Path, name: str) -> Path:
  """
  Resolve a path inside the repository's git directory.

  Args:
    repo: Repository root.
    name: Entry name inside the git directory.

  Returns:
    Absolute path of the entry.

  Raises:
    SweepRefusedError: If git cannot resolve the path.
  """
  path = Path(_git(repo, "rev-parse", "--git-path", name).stdout.strip())
  return path if path.is_absolute() else repo / path


def _query_changed(repo: Path, candidates: list[str]) -> list[str]:
  """
  List the candidate paths that differ from HEAD or are untracked and not ignored.

  Args:
    repo: Repository root.
    candidates: Repo-relative paths to test.

  Returns:
    Sorted subset of the candidates that changed.

  Raises:
    SweepRefusedError: If git exits non-zero.
  """
  # differs from HEAD (staged, unstaged, or intent-to-add) or is untracked and not ignored
  changed = set(_query_git_paths(repo, "diff", "--name-only", "--no-renames", "-z", "HEAD"))
  changed.update(_query_git_paths(repo, "ls-files", "-z", "--others", "--exclude-standard"))
  return sorted(changed & set(candidates))


def _query_hashes(repo: Path, paths: list[str]) -> dict[str, str]:
  """
  Hash the current content of files.

  Args:
    repo: Repository root.
    paths: Repo-relative paths to hash.

  Returns:
    Paths mapped to their git object hash, an empty string for a file that no longer exists.

  Raises:
    SweepRefusedError: If git exits non-zero.
  """
  # a deleted file hashes to the empty string
  present = [ path for path in paths if ( repo / path ).is_file() ]
  out = _git(repo, "hash-object", "--", *present).stdout.split() if present else []
  hashes = dict(zip(present, out, strict = True))
  return { path: hashes.get(path, "") for path in paths }


def _find_all_candidates(snap: dict) -> list[str]:
  """
  List the repo-relative paths a sweep run may change.

  Args:
    snap: Recorded snapshot of the run.

  Returns:
    Sorted scope files plus the dictionary when it lies inside the repository.
  """
  # a dictionary outside the repo is never part of a repo commit
  inside = [ snap["dictionary"] ] if not Path(snap["dictionary"]).is_absolute() else []
  return sorted({ *snap["files"], *inside })


def save_snapshot(repo: Path, scope: Scope, dictionary: Path) -> Path:
  """
  Record the scope, the dictionary, and the paths already dirty before a sweep run.

  Notes:
    - Writes the snapshot inside the git directory, outside the worktree and every commit.

  Args:
    repo: Repository root.
    scope: Scope the run covers.
    dictionary: Path of the dictionary file.

  Returns:
    Path of the snapshot file.

  Raises:
    SweepRefusedError: If git exits non-zero.
  """
  # what the run may touch, and which of it the operator already had dirty before the run started
  snap: dict[str, object] = { "files": scope.files, "source": scope.source, "dictionary": _rel(repo, dictionary) }
  snap["dirty_before"] = _query_hashes(repo, _query_changed(repo, _find_all_candidates(snap)))

  # the snapshot lives in the git dir, out of the worktree and out of every commit
  path = _query_git_dir_path(repo, SNAPSHOT_NAME)
  _atomic_write(path, json.dumps(snap, indent = 2) + "\n")
  return path


def load_snapshot(repo: Path) -> dict:
  """
  Load the snapshot the scope verb recorded.

  Args:
    repo: Repository root.

  Returns:
    Decoded snapshot.

  Raises:
    SweepRefusedError: If no snapshot exists or it cannot be read.
  """
  path = _query_git_dir_path(repo, SNAPSHOT_NAME)

  # guard: every verb after `scope` works on the scope the snapshot recorded
  if not path.is_file():
    raise SweepRefusedError("no_snapshot", detail = "run the `scope` verb first")
  try:
    return json.loads(path.read_text(encoding = "utf-8"))
  # a snapshot that cannot be read is as good as none
  except (OSError, json.JSONDecodeError) as error:
    raise SweepRefusedError("no_snapshot", detail = f"snapshot unreadable: {error}") from error


def _in_transaction(repo: Path) -> bool:
  """
  Report whether a merge, rebase, cherry-pick, or revert is in progress.

  Args:
    repo: Repository root.

  Returns:
    True when the repository is in the middle of such an operation.
  """
  return any(_query_git_dir_path(repo, marker).exists() for marker in _TRANSACTION_MARKERS)


def commit(repo: Path) -> CommitResult:
  """
  Commit the paths the sweep changed, leaving out what the operator already had dirty.

  Notes:
    - A refusal is reported in the result status rather than raised.
    - The snapshot is dropped once the commit lands, has nothing to commit, or is skipped; a refusal keeps it so the
      caller can retry.

  Args:
    repo: Repository root.

  Returns:
    Outcome with the status, the commit hash and the committed paths when it landed, and any held-back paths.

  Raises:
    SweepRefusedError: If git fails outside the commit itself.
  """

  # Domain(runtime.git-safety):
  # # What the sweep commits
  # The sweep commits only what it changed: the files of its scope and its dictionary that differ
  # from HEAD now. A file the operator already had dirty before the run is never swept into the
  # commit — left out silently when the run did not change it, held back and reported when it did.
  # The index belongs to the operator, so staged content refuses the commit, and in a merge,
  # rebase, cherry-pick or revert the commit is skipped and the paths are reported instead.

  # guard: no snapshot, no record of what the run may commit
  try:
    snap = load_snapshot(repo)
  except SweepRefusedError as error:
    return CommitResult(status = "refused", reason = error.reason, detail = error.detail)

  # the run's changes, minus the operator's own pre-run edits
  dirty_before: dict[str, str] = snap.get("dirty_before", {})
  changed = _query_changed(repo, _find_all_candidates(snap))
  now = _query_hashes(repo, [ path for path in changed if path in dirty_before ])
  held = sorted(path for path, digest in now.items() if digest != dirty_before[path])
  paths = [ path for path in changed if path not in dirty_before ]
  snap_path = _query_git_dir_path(repo, SNAPSHOT_NAME)

  # guard: inside a transaction the commit is the operator's; report what would have gone in
  if _in_transaction(repo):
    snap_path.unlink(missing_ok = True)
    return CommitResult(status = "commit-skipped", paths = paths, held = held)

  # guard: staged content is the operator's and a pathspec commit would still race it; intent-to-add never blocks
  if _query_git_paths(repo, "diff", "--cached", "--name-only", "-z"):
    return CommitResult(status = "refused", paths = paths, held = held, reason = "staged_content",
                        detail = "the index holds staged content; commit or unstage it, then re-run `commit`")

  # guard: nothing the run changed is left to commit
  if not paths:
    snap_path.unlink(missing_ok = True)
    return CommitResult(status = "noop", held = held)

  # untracked paths enter the index as intent-to-add only, then the commit names every path
  untracked = set(_query_git_paths(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", *paths))
  if untracked:
    _git(repo, "add", "-N", "--", *sorted(untracked))
  proc = _git(repo, "commit", "-m", COMMIT_SUBJECT, "--", *paths, check = False)

  # guard: a refused commit (a hook, a lock) keeps the snapshot so the caller can retry
  if proc.returncode != 0:
    return CommitResult(status = "refused", paths = paths, held = held, reason = "commit_failed",
                        detail = ( proc.stderr or proc.stdout ).strip())

  # the commit landed: record it and drop the snapshot
  snap_path.unlink(missing_ok = True)
  return CommitResult(status = "committed", sha = _git(repo, "rev-parse", "HEAD").stdout.strip(), paths = paths,
                      held = held)


def _emit(payload: dict) -> None:
  """
  Print a payload as one JSON line on stdout.

  Args:
    payload: JSON-serialisable result of a verb.
  """
  print(json.dumps(payload, ensure_ascii = False))


def _read_json_arg(arg: str) -> object:
  """
  Decode a JSON document from a file or from stdin.

  Args:
    arg: File path, or `-` to read stdin.

  Returns:
    Decoded JSON value.

  Raises:
    OSError: If the file cannot be read.
    json.JSONDecodeError: If the content is not valid JSON.
  """
  raw = sys.stdin.read() if arg == _STDIN_ARG else Path(arg).read_text(encoding = "utf-8")
  return json.loads(raw)


def _query_repo_root(arg: str) -> Path:
  """
  Find the top-level directory of the git checkout containing a directory.

  Args:
    arg: Directory inside the target repository.

  Returns:
    Root of the checkout.

  Raises:
    SweepRefusedError: If the directory is not inside a git repository.
  """
  proc = subprocess.run(
    [ "git", "rev-parse", "--show-toplevel" ], cwd = arg, capture_output = True, text = True, check = False,
    encoding = "utf-8",
  )

  # guard: every verb works inside a git checkout
  if proc.returncode != 0:
    raise SweepRefusedError("not_a_repo", detail = f"{arg} is not inside a git repository")
  return Path(proc.stdout.strip())


def _snapshot_dictionary(repo: Path, snap: dict) -> Path:
  """
  Resolve the dictionary path a snapshot recorded.

  Args:
    repo: Repository root.
    snap: Recorded snapshot of the run.

  Returns:
    Absolute path of the dictionary.
  """
  path = Path(snap["dictionary"])
  return path if path.is_absolute() else repo / path


def _to_json_blocks(blocks: list[Block]) -> list[dict]:
  """
  Convert blocks to JSON-ready dictionaries.

  Args:
    blocks: Blocks to convert.

  Returns:
    One dictionary per block, in order.
  """
  return [ asdict(block) for block in blocks ]


def _cmd_scope(repo: Path, args: argparse.Namespace) -> tuple[int, dict]:
  """
  Resolve the sweep scope and its dictionary and record them for the later verbs.

  Args:
    repo: Repository root.
    args: Parsed command-line arguments.

  Returns:
    Exit code and the JSON payload to print.

  Raises:
    SweepRefusedError: If git cannot resolve the scope or the snapshot cannot be saved.
  """
  scope = resolve_scope(repo, list(args.paths))
  dictionary = pcf.resolve_dictionary(repo)
  path = save_snapshot(repo, scope, dictionary)
  return _EXIT_OK, {
    "status": "ok", "files": scope.files, "source": scope.source, "dictionary": _rel(repo, dictionary),
    "dictionary_exists": dictionary.is_file(), "snapshot": str(path),
  }


def _cmd_inventory(repo: Path, _args: argparse.Namespace) -> tuple[int, dict]:
  """
  Report the knowledge blocks of the recorded scope and how they are filed.

  Args:
    repo: Repository root.
    _args: Parsed command-line arguments, unused.

  Returns:
    Exit code and the JSON payload to print.

  Raises:
    SweepRefusedError: If no snapshot was recorded.
  """
  snap = load_snapshot(repo)
  inv = build_inventory(repo, list(snap["files"]), _snapshot_dictionary(repo, snap))
  return _EXIT_OK, {
    "status": "ok", "blocks": _to_json_blocks(inv.blocks), "groups": inv.groups,
    "unfiled": _to_json_blocks(inv.unfiled),
    "unknown_groups": { group: _to_json_blocks(blocks) for group, blocks in inv.unknown_groups.items() },
  }


def _cmd_dictionary_apply(repo: Path, args: argparse.Namespace) -> tuple[int, dict]:
  """
  Apply the dictionary edits from the ops document.

  Args:
    repo: Repository root.
    args: Parsed command-line arguments.

  Returns:
    Exit code and the JSON payload to print.

  Raises:
    SweepRefusedError: If the ops are malformed or an edit is refused.
  """
  ops = DictionaryOps.from_json(_read_json_arg(args.ops))
  result = apply_dictionary(_snapshot_dictionary(repo, load_snapshot(repo)), ops)
  payload = asdict(result)
  payload["touched_paths"] = [ _rel(repo, Path(path)) for path in result.touched_paths ]
  return _EXIT_OK, { "status": "applied" if result.touched_paths else "noop", **payload, "reason": None }


def _parse_refile_plan(data: object) -> tuple[dict[str, str], list[Assignment]]:
  """
  Validate a decoded refile plan and split it into renames and assignments.

  Args:
    data: Decoded JSON value, expected to be an object with the optional keys `renames` and `assign`.

  Returns:
    Group renames and per-block assignments.

  Raises:
    SweepRefusedError: If the plan or one of its entries has the wrong shape.
  """
  # guard: the plan is a JSON object
  if not isinstance(data, dict):
    raise SweepRefusedError("invalid_input", detail = "the refile plan must be a JSON object")
  renames = _expect_str_map(data.get("renames", {}), "renames")

  # each assignment names a path, a 1-based line, and a group
  assign: list[Assignment] = []
  for entry in _expect_list(data.get("assign", []), "assign"):
    # guard: an assignment carries a string path, an integer line, and a string group
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) \
        or not isinstance(entry.get("line"), int) or not isinstance(entry.get("group"), str):
      raise SweepRefusedError(
        "invalid_input", detail = "each assign entry needs string `path`, integer `line`, string `group`",
      )
    assign.append(Assignment(path = entry["path"], line = entry["line"], group = entry["group"]))
  return renames, assign


def _cmd_refile_headers(repo: Path, args: argparse.Namespace) -> tuple[int, dict]:
  """
  Rewrite the group in Domain headers according to the refile plan.

  Args:
    repo: Repository root.
    args: Parsed command-line arguments.

  Returns:
    Exit code and the JSON payload to print.

  Raises:
    SweepRefusedError: If the plan is malformed or a refile is refused.
  """
  renames, assign = _parse_refile_plan(_read_json_arg(args.plan))
  snap = load_snapshot(repo)
  result = refile_headers(repo, list(snap["files"]), _snapshot_dictionary(repo, snap),
                          renames = renames, assign = assign)
  return _EXIT_OK, { "status": "applied" if result.rewritten else "noop", **asdict(result), "reason": None }


def _cmd_commit(repo: Path, _args: argparse.Namespace) -> tuple[int, dict]:
  """
  Commit what the sweep changed.

  Args:
    repo: Repository root.
    _args: Parsed command-line arguments, unused.

  Returns:
    Exit code, non-zero when the commit was refused, and the JSON payload to print.

  Raises:
    SweepRefusedError: If git fails outside the commit itself.
  """
  result = commit(repo)
  return ( _EXIT_REFUSED if result.status == "refused" else _EXIT_OK ), asdict(result)


# The verb table the parser dispatches through
_COMMANDS = {
  "scope": _cmd_scope,
  "inventory": _cmd_inventory,
  "dictionary-apply": _cmd_dictionary_apply,
  "refile-headers": _cmd_refile_headers,
  "commit": _cmd_commit,
}


def _build_parser() -> argparse.ArgumentParser:
  """
  Build the command-line parser with one sub-command per verb.

  Returns:
    Configured argument parser.
  """
  parser = argparse.ArgumentParser(prog = "knowledge_sweep.py", description = "lazy-python.knowledge-sweep verbs")
  verbs = parser.add_subparsers(dest = "verb", required = True)

  # one sub-parser per verb, each taking the repo it works on
  scope = verbs.add_parser("scope", help = "resolve the sweep scope and the dictionary, write the snapshot")
  scope.add_argument("paths", nargs = "*", help = "explicit repo-relative paths; empty uses the configured scope")
  verbs.add_parser("inventory", help = "list Domain and Contract blocks in the snapshot's scope")
  apply = verbs.add_parser("dictionary-apply", help = "add, rename, remove, or regloss dictionary groups")
  apply.add_argument("ops", help = "ops JSON file, or - for stdin")
  refile = verbs.add_parser("refile-headers", help = "rewrite the group in Domain header lines")
  refile.add_argument("plan", help = "refile plan JSON file, or - for stdin")
  verbs.add_parser("commit", help = "commit what the sweep changed")
  for sub in verbs.choices.values():
    sub.add_argument("--repo", default = ".", help = "directory inside the target repository (default: cwd)")
  return parser


def main(argv: list[str]) -> int:
  """
  Run the knowledge-sweep command line.

  Notes:
    - Prints exactly one JSON line on stdout describing the outcome.

  Args:
    argv: Command-line arguments without the program name.

  Returns:
    Exit code: 0 on success, 1 when the verb is refused, 2 when an input document is malformed.
  """
  args = _build_parser().parse_args(argv)

  # dispatch the verb; a refusal becomes a JSON line with the verb's own keys and exit 1
  try:
    repo = _query_repo_root(args.repo)
    code, payload = _COMMANDS[args.verb](repo, args)
  except SweepRefusedError as error:
    code, payload = _EXIT_REFUSED, {
      "status": "refused", **_REFUSAL_KEYS[args.verb], "reason": error.reason, "detail": error.detail,
    }

    # a malformed input document is an argument error, not a refusal of the operation
    if error.reason == "invalid_input":
      code, payload = _EXIT_USAGE, { "status": "error", "reason": error.reason, "detail": error.detail }
  # an unreadable or unparseable input document is an argument error too
  except (OSError, json.JSONDecodeError) as error:
    code, payload = _EXIT_USAGE, { "status": "error", "reason": "invalid_input", "detail": str(error) }
  _emit(payload)
  return code


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
