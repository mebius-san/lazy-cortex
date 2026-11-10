"""
Logic behind the `lazycortex-specs migrate-source-links` verb — moves the spec catalog's links into the repository's
own code off forge URLs and onto root links.

An earlier release linked a spec document to the product's code through the forge's web view and could pin those
links to a branch with a `spec_source_branches` key. The code now lives in the catalog's own repository, so this verb
turns every forge link into a file of this same repository into a `[<name>](/<path>)` root link, names a linked folder
as backticked text, leaves a link to a path no longer in the tree or into any other repository as it is, and drops the
retired key. It never commits.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The retired branch-pin key this verb removes from every document.
_BRANCHES_KEY = "spec_source_branches"

# An inline markdown link to a web URL: its display text, then a target without blanks or a title.
_LINK_RE = re.compile(r"\[(?P<text>[^\]\n]*)\]\((?P<url>https?://[^)\s]+)\)")
# The link's display-text group.
_TEXT_GROUP = "text"
# The link's URL group.
_URL_GROUP = "url"

# A run of backticks, which opens an inline code span and closes it at the next run of the same length.
_TICKS_RE = re.compile(r"`+")

# The view segments a forge's file or folder URL puts between `<owner>/<repo>` and the revision, longest first:
# GitLab, Gitea and Forgejo, then GitHub, sourcehut and Bitbucket.
_VIEW_PREFIXES = (
    ( "-", "blob" ), ( "-", "tree" ), ( "src", "branch" ), ( "src", "commit" ), ( "src", "tag" ),
    ( "blob", ), ( "tree", ), ( "src", ),
)

# The sourcehut host, whose view puts one more segment between the revision and the path.
_SOURCEHUT_HOST = "git.sr.ht"
# The segment sourcehut puts before the path.
_SOURCEHUT_ITEM = "item"

# A remote in scp form, `user@host:owner/repo`, which `urlsplit` cannot read.
_SCP_REMOTE_RE = re.compile(r"^[^@/\s]+@(?P<host>[^:/\s]+):(?P<path>.+)$")
# The scp remote's host group.
_HOST_GROUP = "host"
# The scp remote's path group.
_PATH_GROUP = "path"
# The marker of a remote written as a URL rather than in scp form.
_SCHEME_MARK = "://"
# The suffix a remote's repository name may carry.
_GIT_SUFFIX = ".git"

# The git commands that name the repository's remote: `origin` first, else the first remote listed.
_GIT = "git"
# The remote that stands for the repository when it exists.
_ORIGIN = "origin"
# The command printing one remote's URL.
_GET_URL = ( _GIT, "remote", "get-url" )
# The command listing every remote's name.
_LIST_REMOTES = ( _GIT, "remote" )

# The URL path separator.
_SLASH = "/"
# The line separator of the text `spec_paths.read_text` returns.
_LF = "\n"
# The suffix of the documents the verb walks.
_MD_SUFFIX = ".md"
# The encoding of git's output.
_ENCODING = "utf-8"
# The environment variable naming the repository root when `--cwd` is absent.
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's own wire-shape keys, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Move every forge link into the repository's own code onto a root link and drop the branch-pin key.

  Guarantees:
    - A forge link into a file of this repository becomes a root link keeping its display text, unless that text is
      empty or the URL itself, which gives way to the file's basename; a link into a folder becomes the backticked
      folder path.
    - A link to a missing path, into another repository, with more than one reading of its revision and path, inside
      a fenced code block or inside an inline code span is kept; a link in an indented code block is rewritten.
    - Only those links and the `spec_source_branches` key change, and a document with nothing to change is not
      written; a document with uniform line endings keeps them, while a mixed-ending one is written back with its
      first ending throughout.
    - A dry run writes nothing, and a second run over the result changes nothing.

  Notes:
    - Performs file I/O and runs git in the repository.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the markdown files of the spec catalog rewritten and those already current, each a
    list of paths relative to the settings root, in walk order.

  Raises:
    OSError: When git cannot be started or a document cannot be read or written.
    ValueError: When the settings file is not valid JSON.
    AttributeError: When the settings file holds JSON that is not an object.
  """

  # Contract:
  # Only forge links into this repository's own files or folders and the `spec_source_branches` key change, and a
  # link into another repository is never touched; every other line keeps its bytes, a uniform line ending included.
  # A dry run MUST write no file, and running the verb again over its own output MUST change nothing.

  settings_root = spec_paths.find_settings_root(repo)
  identity = _read_forge_identity(settings_root)
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # every markdown file under the content root, in a stable order
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    for name in sorted(filenames):

      # guard: only markdown files carry links and frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue

      # the document's text as it is and as the migration leaves it
      doc = Path(dirpath) / name
      text = spec_paths.read_text(doc)
      new_text = _migrate_text(text, root = settings_root, identity = identity)

      # guard: a document already current is reported and left unwritten
      rel = doc.relative_to(settings_root).as_posix()
      if new_text == text:
        result[_SKIPPED_KEY].append(rel)
        continue

      # a changed document is reported, and written unless the run is dry
      result[_CHANGED_KEY].append(rel)
      if not dry_run:
        spec_paths.write_text_atomic(doc, new_text)

  # the report the CLI prints for the migration step
  return result


def _read_forge_identity(root: Path) -> tuple[str, tuple[str, ...]] | None:
  """
  Read the forge host and repository path the repository's own remote points at.

  Args:
    root: The repository root.

  Returns:
    The lower-cased host and the lower-cased path segments of the `origin` remote, else of the first remote listed;
    None when the directory is not a git repository, has no remote, or the remote names no forge repository.

  Raises:
    OSError: When git cannot be started.
  """
  url = _run_git(root, *_GET_URL, _ORIGIN)

  # guard: without `origin`, the first remote listed stands for the repository
  if url is None:
    remotes = (_run_git(root, *_LIST_REMOTES) or "").split()
    url = _run_git(root, *_GET_URL, remotes[0]) if remotes else None

  # guard: a repository without a remote has no forge links of its own
  if url is None:
    return None

  # an scp-form remote names its host before the colon, every other form is a URL
  scp = None if _SCHEME_MARK in url else _SCP_REMOTE_RE.match(url)
  parts = urlsplit(url)
  host, path = ( scp[_HOST_GROUP], scp[_PATH_GROUP] ) if scp else ( parts.hostname or "", parts.path )
  segments = tuple(seg.lower() for seg in path.strip(_SLASH).removesuffix(_GIT_SUFFIX).split(_SLASH) if seg)

  # a forge repository is a host and at least an owner and a name
  return ( host.lower(), segments ) if host and len(segments) >= 2 else None


def _run_git(root: Path, *args: str) -> str | None:
  """
  Run one git command in the repository and return what it printed.

  Args:
    root: The repository root the command runs in.
    *args: The full command line.

  Returns:
    The stripped stdout; None when the command exits non-zero or prints nothing.

  Raises:
    OSError: When git cannot be started.
  """
  proc = subprocess.run(list(args), cwd = str(root), capture_output = True, text = True, check = False,
                        encoding = _ENCODING)
  return proc.stdout.strip() or None if proc.returncode == 0 else None


def _migrate_text(text: str, *, root: Path, identity: tuple[str, tuple[str, ...]] | None) -> str:
  """
  Rewrite one document's forge links and drop its branch-pin key.

  Args:
    text: The full document text.
    root: The repository root the linked paths are looked up under.
    identity: The repository's own forge host and path segments, or None when it has none.

  Returns:
    The document text with the key gone and every rewritable link outside a fenced block and an inline code span
    rewritten; a link in an indented code block is rewritten too, since a list item's continuation lines share that
    indentation. The text comes back unchanged when neither applies.
  """
  text = spec_frontmatter.drop_key(text, _BRANCHES_KEY)

  # guard: a repository without a forge identity owns no forge link
  if identity is None:
    return text

  # the body's lines, with every line inside a code fence left alone
  _fm_text, end = spec_frontmatter.block(text)
  lines = text[end:].split(_LF)
  fenced = spec_frontmatter.fenced_lines(lines)

  # the frontmatter is carried over untouched ahead of the rewritten body
  rewritten = [ line if fenced[idx] else _rewrite_line(line, root = root, identity = identity)
                for idx, line in enumerate(lines) ]
  return text[:end] + _LF.join(rewritten)


def _rewrite_line(line: str, *, root: Path, identity: tuple[str, tuple[str, ...]]) -> str:
  """
  Rewrite the forge links of one body line that do not start inside an inline code span.

  Args:
    line: One body line outside a fenced block.
    root: The repository root the linked paths are looked up under.
    identity: The repository's own forge host and path segments.

  Returns:
    The line with every rewritable link outside a code span rewritten; a code span is read within the line only.
  """
  replace = functools.partial(_rewrite_link, root = root, identity = identity, spans = _find_code_spans(line))
  return _LINK_RE.sub(replace, line)


def _find_code_spans(line: str) -> list[tuple[int, int]]:
  """
  Find the inline code spans of one line.

  Args:
    line: The line to scan.

  Returns:
    The start and end offset of each span, its backtick runs included, in line order; a backtick run with no closing
    run of the same length opens no span.
  """
  spans: list[tuple[int, int]] = []
  scan = 0

  # each opener is closed by the next run of exactly its length, else it is literal text
  while ( opener := _TICKS_RE.search(line, scan) ) is not None:
    closer = next(( run for run in _TICKS_RE.finditer(line, opener.end()) if len(run[0]) == len(opener[0]) ), None)

    # guard: an opener without a closer is literal, so the scan moves past it
    if closer is None:
      scan = opener.end()
      continue

    # a closed span is recorded and the scan resumes after it
    spans.append(( opener.start(), closer.end() ))
    scan = closer.end()

  # the spans in line order
  return spans


def _rewrite_link(match: re.Match[str], *, root: Path, identity: tuple[str, tuple[str, ...]],
                  spans: list[tuple[int, int]]) -> str:
  """
  Turn one matched forge link into its root form.

  Args:
    match: The matched markdown link.
    root: The repository root the linked path is looked up under.
    identity: The repository's own forge host and path segments.
    spans: The inline code spans of the line the link sits on.

  Returns:
    `[<text>](/<path>)` for a file, the operator's display text kept unless it is empty or the URL itself, which
    gives way to the file's basename; the backticked `<path>/` for a folder; the link as matched when it starts
    inside a code span or does not name exactly one path of this repository.
  """

  # guard: a link that starts inside a code span is literal text
  if any(start <= match.start() < end for start, end in spans):
    return match.group(0)

  # guard: a link into another repository, to a path no longer in the tree, or read more than one way is kept
  if ( found := _find_repo_path(match[_URL_GROUP], root = root, identity = identity) ) is None:
    return match.group(0)

  # a folder is named, never linked
  rel, target = found
  if target.is_dir():
    return f"`{unquote(rel)}/`"

  # a file keeps the author's text, unless that text was only the URL
  text = match[_TEXT_GROUP]
  return f"[{text if text and text != match[_URL_GROUP] else target.name}](/{rel})"


def _find_repo_path(url: str, *, root: Path, identity: tuple[str, tuple[str, ...]]) -> tuple[str, Path] | None:
  """
  Find the path of this repository a forge URL views.

  Args:
    url: The link's URL.
    root: The repository root the path is looked up under.
    identity: The repository's own forge host and path segments.

  Returns:
    The path as written in the URL and the file or folder it names in the tree, when exactly one split of the URL
    into revision and path names something inside the tree; None when the URL is not a forge view into this
    repository, when no split names a path in the tree, or when several do.
  """

  # Domain(unfiled):
  # # Forge view links into the repository's own code
  # A forge shows a file or a folder of a repository at an address made of the forge host, the owner and repository
  # name, a view marker, a revision and the path. The view marker differs per forge: GitLab writes `-/blob` or
  # `-/tree`, Gitea and Forgejo write `src/branch`, `src/commit` or `src/tag`, GitHub writes `blob` or `tree`,
  # Bitbucket writes `src`, and sourcehut writes `tree` and puts an `item` marker between the revision and the path.
  # An address belongs to this repository only when its host, owner and name match the repository's own remote. A
  # revision may itself contain slashes, so the address is read as revision plus path at every possible split, and it
  # counts only when exactly one split names a file or folder inside the working tree: none means the path is gone,
  # several mean the address is ambiguous, and either way the link is kept as written. A file becomes a link from the
  # repository root, a folder is named as text, since a link to a folder would make the note app create a note.

  host, own = identity
  parts = urlsplit(url)
  segments = [ seg for seg in parts.path.split(_SLASH) if seg ]

  # guard: a link into another host or another repository is never this repository's
  if ( parts.hostname or "" ).lower() != host or tuple(seg.lower() for seg in segments[:len(own)]) != own:
    return None

  # guard: only a file or folder view carries a path
  rest = tuple(segments[len(own):])
  if ( prefix := next(( view for view in _VIEW_PREFIXES if rest[:len(view)] == view ), None) ) is None:
    return None

  # every split of revision and path that names something inside the tree
  tail = rest[len(prefix):]
  tree = root.resolve()
  found: list[tuple[str, Path]] = []
  for cut in range(1, len(tail)):
    path = tail[cut:]

    # guard: sourcehut marks where the path starts, so a cut without the mark is no candidate
    if host == _SOURCEHUT_HOST and path[0] != _SOURCEHUT_ITEM:
      continue

    # past the sourcehut mark, the path proper begins
    if host == _SOURCEHUT_HOST:
      path = path[1:]

    # a decoded path that names something inside the tree is a candidate; one leading out of it never is
    target = root / unquote(_SLASH.join(path))
    if path and target.exists() and target.resolve().is_relative_to(tree):
      found.append(( _SLASH.join(path), target ))

  # only an unambiguous reading counts
  return found[0] if len(found) == 1 else None


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one document would change, 1 when none would.
    - Any failure exits 2 under every flag, never an answer `--check` gives.

  Notes:
    - Prints the result to stdout and a failure to stderr; a run without `--dry-run` or `--check` writes documents.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a document would change and 1 when none would; 0 otherwise; 2 on any failure.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one document would change, 1 when none would;
  # any failure MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-source-links")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: CLI boundary — malformed settings raise errors of any type from the shared readers, and an uncaught one
  # would exit 1, which `--check` and the migration step read as "nothing to do"
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-source-links: {error}\n")
    return _EXIT_FAILED

  # the migration step parses this JSON; only a check also answers through its exit code
  print(json.dumps(result))
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
