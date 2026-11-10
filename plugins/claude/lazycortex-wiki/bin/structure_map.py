from __future__ import annotations

import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import wiki_job_response as _job_response  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Operation keys of the structure protocol's result format.
_OP = "op"
_OP_ENTER = "enter"
_OP_UPDATE = "update"
_OP_REMOVE = "remove"
_OP_PATH = "path"
_OP_DESCRIPTION = "description"

# One map entry: indentation, the bullet, the path, the separator, the description.
_ENTRY = re.compile(r"^(?P<indent> *)- (?P<path>\S+) — (?P<description>.*)$")
_G_INDENT = "indent"
_G_PATH = "path"
_G_DESCRIPTION = "description"
_INDENT_STEP = "  "
_SEP = " — "
_DIR_SUFFIX = "/"
_NL = "\n"


# ----------------------------------------------------------------------------------------
class StructureMap:
  """
  Editor of the project-structure map's text.

  Turns a batch of enter, update and remove operations on described paths into the map's new text. Each entry is
  a line `<indent>- <path> — <description>`; a directory's entries nest one level under it, and siblings follow
  the order of their paths. The file on disk is never written — the caller receives the text and lands it.

  Guarantees:
    - A batch that is refused leaves no partial result: a `JobRefusedError` is raised and no text is returned.
    - An unknown operation, or an operation whose anchor entry is absent or occurs more than once, is refused as a
      technical failure.
    - A missing map is refused as a logical failure and is never recreated.
  """

  # Contract:
  # A batch is applied whole or not at all. When any move or operation is refused,
  # the caller receives a `JobRefusedError` and no map text.

  # Contract:
  # An unknown operation, and an operation whose anchor entry is absent from the map
  # or occurs in it more than once, are refused with the technical category.

  # Contract:
  # A missing map file is refused with the logical category, never the technical one,
  # and the map is never recreated.

  def __init__(self, *, path: Path) -> None:
    """
    Bind the editor to one map file.

    Args:
      path: Path of the map file the operations apply to.
    """
    # the map file the operations apply to
    self._path = Path(path)

  def apply(self, operations: list[dict], *, moves: list[tuple[str, str]] | None = None) -> str:
    """
    Return the map text after the directory moves and the operations are applied.

    Guarantees:
      - The entry of a moved directory keeps its description under the new directory path.

    Notes:
      - The map file is only read; writing the result is the caller's job.

    Args:
      operations: Operations in order; each carries an `op` of enter, update or remove, a `path`, and for enter
        and update a `description`.
      moves: Pairs of old and new directory prefixes, applied before the operations.

    Returns:
      The complete new map text.

    Raises:
      JobRefusedError: With the logical category when the map file is missing; with the technical category when an
        operation is unknown or an entry it anchors to is absent or occurs more than once.
    """

    # Contract:
    # The entry of a moved directory carries its description over unchanged
    # to the new directory path.

    # Domain(wiki.structure):
    # # Where a map entry goes
    # A map entry sits under the nearest entry that describes one of its parent directories, one level of
    # indentation deeper, and an entry with no such parent sits at the top level. Among the entries under one
    # parent the order is the order of their paths, the same order a full rebuild produces, so an incremental
    # change and a rebuild agree on where a line belongs. Removing an entry removes that one line: the entries
    # under it leave only by their own removal. The map is never repaired by guesswork — an entry an operation
    # would anchor to that appears more than once stops the write, and a missing map is never recreated, since
    # one incremental entry would present a single path as the whole repository.
    # When a directory is renamed, the version history reports only the files that moved, so the directory's
    # own entry would keep naming a path that no longer exists while the new directory went undescribed. The
    # entry of a vanished directory therefore follows the rename to its new name, description and all.

    # guard: a missing map is never recreated
    if not self._path.is_file():
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_LOGICAL, reason = f"structure map not found: {self._path}",
      )

    # the map's current lines are what every operation edits
    lines = TextFile(path = self._path).read().splitlines()

    # a vanished directory's entry moves first, so the entries entered below nest under its new name
    for old_dir, new_dir in moves or []:
      self._move_dir(lines, old_dir, new_dir)

    # each operation edits the line list; a refusal anywhere refuses the whole batch
    for operation in operations:
      kind = operation.get(_OP)
      path = str(operation.get(_OP_PATH, ""))
      description = str(operation.get(_OP_DESCRIPTION, ""))
      if kind == _OP_ENTER:
        self._enter(lines, path, description)
      elif kind == _OP_UPDATE:
        index = self._index_of(lines, path)
        lines[index] = self._render(self._indent(lines[index]), path, description)
      elif kind == _OP_REMOVE:
        del lines[self._index_of(lines, path)]
      else:
        raise _job_response.JobRefusedError(
          category = _job_response.CATEGORY_TECHNICAL, reason = f"unknown map operation: {kind!r}",
        )

    # the map is line-oriented and ends with a newline
    return _NL.join(lines) + _NL

  def _move_dir(self, lines: list[str], old_dir: str, new_dir: str) -> None:
    """
    Carry the entries of a renamed directory over to its new path, descriptions intact.

    Args:
      lines: Map lines, edited in place.
      old_dir: Directory path, with trailing slash, that no longer exists.
      new_dir: Directory path, with trailing slash, that replaces it.
    """
    # every directory entry at or under the vanished directory, parents before children
    moved = [
      (index, match.group(_G_PATH), match.group(_G_DESCRIPTION))
      for index, match in self._entries(lines)
      if match.group(_G_PATH).endswith(_DIR_SUFFIX) and match.group(_G_PATH).startswith(old_dir)
    ]

    # guard: nothing to move, or the new directory is already described
    if not moved or any(self._count(lines, new_dir + path[len(old_dir):]) for _, path, _ in moved):
      return

    # drop the old lines bottom-up, then enter each under its new name, parents first
    for index, _, _ in sorted(moved, reverse = True):
      del lines[index]
    for _, path, description in sorted(moved, key = lambda item: len(item[1])):
      self._enter(lines, new_dir + path[len(old_dir):], description)

  def _enter(self, lines: list[str], path: str, description: str) -> None:
    """
    Describe a path in the map, at its place under the nearest described parent directory.

    Args:
      lines: Map lines, edited in place.
      path: Path to describe.
      description: Description of the path.

    Raises:
      JobRefusedError: With the technical category when an entry the new line anchors to occurs more than once.
    """
    # a path already described exactly once is updated in place rather than described twice
    if self._count(lines, path) == 1:
      index = self._index_of(lines, path)
      lines[index] = self._render(self._indent(lines[index]), path, description)
      return

    # the nearest described parent directory decides the depth and the sibling set
    parent = self._parent(lines, path)
    if parent is None:
      indent = ""
      start, end = 0, len(lines)
    else:
      # the parent is an anchor too: a duplicated parent entry refuses the write
      self._index_of(lines, self._path_at(lines, parent))
      indent = self._indent(lines[parent]) + _INDENT_STEP
      start, end = parent + 1, self._subtree_end(lines, parent)

    # insert before the first sibling whose path sorts after the new one, else after the parent's subtree;
    # a top-level entry with no later sibling goes right after the last entry line, ahead of any trailing
    # lines that are not entries
    position = end
    for index in range(start, end):
      match = _ENTRY.match(lines[index])
      # only the parent's direct children are siblings; any other line is passed over
      if match is None or match.group(_G_INDENT) != indent:
        continue
      if match.group(_G_PATH) > path:
        # the sibling the line goes before is the anchor: a duplicated anchor refuses the write
        self._index_of(lines, match.group(_G_PATH))
        position = index
        break
    if parent is None and position == end:
      position = self._last_entry(lines) + 1
    lines.insert(position, self._render(indent, path, description))

  def _parent(self, lines: list[str], path: str) -> int | None:
    """
    Find the nearest described directory that contains a path.

    Args:
      lines: Map lines.
      path: Path whose parent is sought.

    Returns:
      Line index of the deepest described directory entry above the path, or None when there is none.
    """
    best: int | None = None
    best_length = -1

    # the longest described directory the path lies under
    for index, match in self._entries(lines):
      candidate = match.group(_G_PATH)
      if candidate.endswith(_DIR_SUFFIX) and path.startswith(candidate) and path != candidate:
        if len(candidate) > best_length:
          best, best_length = index, len(candidate)
    return best

  def _subtree_end(self, lines: list[str], parent: int) -> int:
    """
    Find where the entries nested under a directory entry end.

    Args:
      lines: Map lines.
      parent: Line index of the directory entry.

    Returns:
      Index of the first line after the directory's nested entries.
    """
    depth = len(self._indent(lines[parent]))

    # the subtree runs over the following entries indented deeper than the parent
    end = parent + 1
    while end < len(lines):
      match = _ENTRY.match(lines[end])
      # a non-entry line or an entry at the parent's depth or shallower closes the subtree
      if match is None or len(match.group(_G_INDENT)) <= depth:
        break
      end += 1
    return end

  def _last_entry(self, lines: list[str]) -> int:
    """
    Find the last entry line of the map.

    Args:
      lines: Map lines.

    Returns:
      Index of the last entry line, or of the last line when the map holds no entry.
    """
    # the index of the last entry line, or of the last line when the map holds no entry yet
    indexes = [ index for index, _ in self._entries(lines) ]
    return indexes[-1] if indexes else len(lines) - 1

  def _index_of(self, lines: list[str], path: str) -> int:
    """
    Locate the one entry that describes a path.

    Args:
      lines: Map lines.
      path: Path of the entry.

    Returns:
      Line index of the entry.

    Raises:
      JobRefusedError: With the technical category when the entry is absent or occurs more than once.
    """
    count = self._count(lines, path)

    # guard: an entry an operation anchors to must appear exactly once
    if count != 1:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"entry {path!r} {'is absent from' if count == 0 else 'occurs more than once in'} the map",
      )
    return next(index for index, match in self._entries(lines) if match.group(_G_PATH) == path)

  def _count(self, lines: list[str], path: str) -> int:
    """
    Count the entries that describe a path.

    Args:
      lines: Map lines.
      path: Path of the entries.

    Returns:
      Number of matching entries.
    """
    return sum(1 for _, match in self._entries(lines) if match.group(_G_PATH) == path)

  @staticmethod
  def _path_at(lines: list[str], index: int) -> str:
    """
    Read the path of the entry on a line.

    Args:
      lines: Map lines.
      index: Line index.

    Returns:
      The entry's path, or an empty string when the line is not an entry.
    """
    match = _ENTRY.match(lines[index])
    return match.group(_G_PATH) if match is not None else ""

  @staticmethod
  def _entries(lines: list[str]) -> list[tuple[int, re.Match[str]]]:
    """
    List the entry lines of the map.

    Args:
      lines: Map lines.

    Returns:
      Pairs of line index and parsed entry, in line order; lines that are not entries are skipped.
    """
    return [ (index, match) for index, line in enumerate(lines) if (match := _ENTRY.match(line)) is not None ]

  @staticmethod
  def _indent(line: str) -> str:
    """
    Read the indentation of an entry line.

    Args:
      line: Map line.

    Returns:
      The line's leading indentation, or an empty string when the line is not an entry.
    """
    match = _ENTRY.match(line)
    return match.group(_G_INDENT) if match is not None else ""

  @staticmethod
  def _render(indent: str, path: str, description: str) -> str:
    """
    Format one map entry line.

    Args:
      indent: Leading indentation of the entry.
      path: Path the entry describes.
      description: Description of the path; surrounding whitespace is dropped.

    Returns:
      The entry line.
    """
    return f"{indent}- {path}{_SEP}{description.strip()}"
