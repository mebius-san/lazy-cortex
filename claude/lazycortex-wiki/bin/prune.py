"""
Deterministic See-also prune for a deleted wiki node.

`NodePruner` walks every node in one scope, drops the See-also lines whose
link target resolves to the deleted file, and rebuilds the scope's
`topics.md`. Pure mechanics — no curator dispatch, no git operations
(the CLI wrapper owns the commit).

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract),
so all primitives used here are imported from within this plugin's own `bin/`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from pathlib import Path

import doctor as _doctor
import index as _index
import nodes as _nodes
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Cross-repo link prefix — such targets never resolve to a local deletion.
_CROSS_REPO_PREFIX = "@"

# Result dict keys.
_K_SCOPE        = "scope"
_K_DELETED      = "deleted"
_K_PRUNED_NODES = "pruned_nodes"
_K_INDEX        = "index"


# ----------------------------------------------------------------------------------------
class NodePruner:
  """
  Pruner of dangling See-also links to one deleted node within a single scope.

  Instances are single-use: construct one, call `prune`, then discard it.
  """

  def __init__(self, *, repo: Path | str, scope_id: str, cfg: dict) -> None:
    self._repo = Path(repo).resolve()
    self._scope_id = scope_id
    self._cfg = cfg
    self._resolver = _scope.ScopeResolver(repo = self._repo)

  # ── public ────────────────────────────────────────────────────────────────

  def prune(self, deleted_path: Path | str) -> dict:
    """
    Remove every See-also link to `deleted_path` and rebuild the topic index.

    Args:
      deleted_path: Absolute or repo-relative path of the deleted node.

    Returns:
      Dict shaped `{"scope": <id>, "deleted": <rel>, "pruned_nodes": [<rel>...],
      "index": <rel>}` — `pruned_nodes` lists the repo-relative paths of nodes
      whose See-also section lost at least one line, sorted; `index` is the
      repo-relative path of the rebuilt `topics.md`.
    """
    deleted = Path(deleted_path)
    deleted_abs = (deleted if deleted.is_absolute() else self._repo / deleted).resolve()
    pruned: list[str] = []

    for node_path in self._resolver.iter_nodes(self._cfg):
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type — skip
      if node is None:
        continue
      if self._prune_node(node, node_path, deleted_abs):
        pruned.append(node_path.relative_to(self._repo).as_posix())

    index_path = _index.TopicIndex(
      repo     = self._repo,
      cfg      = self._cfg,
      scope_id = self._scope_id,
    ).build()

    return {
      _K_SCOPE:        self._scope_id,
      _K_DELETED:      deleted_abs.relative_to(self._repo).as_posix(),
      _K_PRUNED_NODES: sorted(pruned),
      _K_INDEX:        index_path.relative_to(self._repo).as_posix(),
    }

  # ── helpers ───────────────────────────────────────────────────────────────

  def _prune_node(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    node_path: Path,
    deleted_abs: Path,
  ) -> bool:
    """
    Drop every See-also item on one node whose target resolves to `deleted_abs`.

    Args:
      node: Loaded node object (written in-place on a match).
      node_path: Absolute path of the node file.
      deleted_abs: Resolved absolute path of the deleted node.

    Returns:
      True when at least one line was dropped; False otherwise.
    """
    # waiver: intentional reuse of the doctor's private See-also primitives (same plugin bin/)
    # pylint: disable=protected-access
    items = _doctor._see_also_lines_from_node(node)
    node_dir = node_path.parent
    dropped = False
    for item in items:
      target, _gloss = _doctor._extract_link_target(item)
      # guard: empty or cross-repo target — cannot be this local deletion
      if not target or target.startswith(_CROSS_REPO_PREFIX):
        continue
      # guard: target does not resolve to the deleted file
      if not self._points_at(node_dir, target, deleted_abs):
        continue
      if isinstance(node, _nodes.MarkdownNode):
        _doctor._drop_see_also_line(node, target)
      else:
        _doctor._drop_code_see_also_line(node, target)
      dropped = True
    # pylint: enable=protected-access
    return dropped

  def _points_at(self, node_dir: Path, target: str, deleted_abs: Path) -> bool:
    """
    Return True when a See-also target string resolves to the deleted path.

    See-also targets are conventionally node-relative, but a repo-relative spelling is also
    accepted; both resolutions are checked.

    Args:
      node_dir: Directory of the node carrying the link.
      target: Raw link target string from the See-also item.
      deleted_abs: Resolved absolute path of the deleted node.

    Returns:
      True on a match under either resolution, False otherwise.
    """
    # guard: node-relative resolution matches
    if (node_dir / target).resolve() == deleted_abs:
      return True
    return (self._repo / target).resolve() == deleted_abs
