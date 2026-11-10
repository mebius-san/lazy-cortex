from __future__ import annotations

import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import nodes as _nodes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class NeighbourFinder:
  """
  Finder of the nodes directly linked to a wiki node.

  Answers, for one markdown node, which other nodes of its wiki scope it is tied to through `# See also`
  sections, in either direction: the nodes it links to and the nodes that link to it.

  Notes:
    - Reads files only; nothing in the repository is written.
  """

  # Keys of the payload `find` returns.
  _KEY_PATH       = "path"
  _KEY_SCOPE      = "scope"
  _KEY_NEIGHBOURS = "neighbours"

  def __init__(self, repo: Path) -> None:
    """
    Create a finder for the wiki scopes configured in a repository.

    Args:
      repo: Repository root; scopes are resolved and result paths are expressed relative to it.
    """

    self._repo = repo.resolve()
    self._resolver = _scope.ScopeResolver(repo = self._repo)

  def find(self, path: str) -> dict:
    """
    Return the scope and the one-hop neighbours of a markdown node.

    A path that no wiki scope claims, including one its scope's frontmatter filter rejects or the scope's
    topics index, has no neighbourhood and is reported with no scope and no neighbours.

    Guarantees:
      - The neighbours are repo-relative paths, sorted and free of duplicates.
      - A neighbour is either a target of the node's own `# See also` section that exists on disk, or a node of
        the same scope whose `# See also` section links to the node.
      - The node itself is never listed among its neighbours.

    Args:
      path: Repo-relative path of an existing markdown node.

    Returns:
      A mapping with `path` (the path as given), `scope` (the scope id, or `None` when no scope claims the
      path) and `neighbours` (the list of neighbour paths, empty when there is no scope).
    """

    rel = Path(path).as_posix()
    result = self._resolver.resolve_scope_by_path(rel)

    # guard: no scope claims the path — it has no wiki neighbourhood
    if result is None:
      return { self._KEY_PATH: path, self._KEY_SCOPE: None, self._KEY_NEIGHBOURS: [] }
    scope_id, cfg = result

    # forward edges: the node's own See-also targets that name a real file
    found = { t for t in self._targets(self._repo / rel) if (self._repo / t).is_file() }

    # backward edges: every node of the same scope whose See-also points here
    for node_path in self._resolver.find_all_nodes(cfg):
      if rel in self._targets(node_path):
        found.add(node_path.relative_to(self._repo).as_posix())

    # a node is never its own neighbour
    found.discard(rel)
    return { self._KEY_PATH: path, self._KEY_SCOPE: scope_id, self._KEY_NEIGHBOURS: sorted(found) }

  def _targets(self, node_path: Path) -> set[str]:
    """
    Return the link targets of a node's `# See also` section.

    Args:
      node_path: Path of the node file.

    Returns:
      Repo-relative target paths; empty when the file is not a markdown node.
    """

    node = _nodes.node_for(node_path)

    # guard: only a markdown node carries a `# See also` section
    if not isinstance(node, _nodes.MarkdownNode):
      return set()
    return node.see_also_targets
