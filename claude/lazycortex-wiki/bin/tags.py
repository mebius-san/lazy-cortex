"""
Tag-consistency primitives for lazycortex-wiki.

`TagOps` provides two deterministic, scope-level operations over a wiki scope's
topic tags. `collect` surveys the distinct axis values in use (with per-value
node counts and a couple of example summaries) — the input a tag-normalisation
judgement consumes. `retag` applies an axis-value alias map across every node's
tags. Both operate uniformly over markdown and code nodes; the markdown-vs-code
storage difference is hidden behind the node accessors.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import nodes as _nodes
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# ────────────────────────────────────────────────────────────────────────────
class TagOps:
  """
  Deterministic tag-consistency operations over one wiki scope.

  Construct with the repo root, scope id, and scope-config dict, then call
  `collect` to survey the distinct tag values per axis, or `retag` to apply an
  alias map across the scope's nodes.
  """

  # Namespace prefix on every wiki topic tag.
  _WIKI_PREFIX = "wiki/"

  # Max example summaries kept per tag value in a `collect` result.
  _MAX_EXAMPLES = 2

  # collect-result dict keys.
  _K_SCOPE    = "scope"
  _K_AXES     = "axes"
  _K_VALUE    = "value"
  _K_COUNT    = "count"
  _K_EXAMPLES = "examples"

  # retag-result dict keys.
  _K_NODES_CHANGED = "nodes_changed"
  _K_TAGS_REMAPPED = "tags_remapped"

  def __init__(self, *, repo: Path, scope_id: str, cfg: dict) -> None:
    """
    Initialise the tag operations for one scope.

    Args:
      repo: Absolute path to the repository root.
      scope_id: Scope identifier as configured in lazy.settings.json.
      cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
    """
    self._repo = repo
    self._scope_id = scope_id
    self._cfg = cfg
    self._resolver = _scope.ScopeResolver(repo = repo)

  # ── public ────────────────────────────────────────────────────────────────

  def collect(self) -> dict:
    """
    Survey the distinct tag values per axis across the scope.

    Returns:
      A dict `{"scope": <id>, "axes": {<axis>: [{"value", "count",
      "examples"}, ...]}}`. Axes and values are sorted; each value carries
      its node count and up to two example node summaries as light context.
    """
    axes: dict = {}
    for node_path in self._resolver.iter_nodes(self._cfg):
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type — skip
      if node is None:
        continue
      summary = self._summary(node)
      for axis, value in self._axis_values(node):
        bucket = axes.setdefault(axis, {})
        entry = bucket.setdefault(value, { self._K_COUNT: 0, self._K_EXAMPLES: [] })
        entry[self._K_COUNT] += 1
        # guard: keep a few distinct example summaries as light context
        if (
          summary
          and summary not in entry[self._K_EXAMPLES]
          and len(entry[self._K_EXAMPLES]) < self._MAX_EXAMPLES
        ):
          entry[self._K_EXAMPLES].append(summary)
    out_axes: dict = {}
    for axis in sorted(axes):
      out_axes[axis] = [
        {
          self._K_VALUE:    value,
          self._K_COUNT:    axes[axis][value][self._K_COUNT],
          self._K_EXAMPLES: axes[axis][value][self._K_EXAMPLES],
        }
        for value in sorted(axes[axis])
      ]
    return { self._K_SCOPE: self._scope_id, self._K_AXES: out_axes }

  def retag(self, alias_map: dict) -> dict:
    """
    Apply an axis-value alias map to every node's tags in the scope.

    A tag `<axis>/<old>` becomes `<axis>/<new>` when the map lists that value;
    tags the map does not mention are left unchanged. Values collapsed onto an
    existing one are de-duplicated. The write touches only the managed tag
    region, so a re-run with no further alias matches is a no-op.

    Args:
      alias_map: `{<axis>: {<old-value>: <new-value>}}`.

    Returns:
      A dict `{"scope": <id>, "nodes_changed": <n>, "tags_remapped": <m>}`.
    """
    nodes_changed = 0
    tags_remapped = 0
    for node_path in self._resolver.iter_nodes(self._cfg):
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type — skip
      if node is None:
        continue
      bare = self._bare_topics(node)
      remapped, hits = self._remap(bare, alias_map)
      # guard: nothing changed for this node — skip the write
      if remapped == bare:
        continue
      summary = self._summary(node)
      prefixed = [ f"{self._WIKI_PREFIX}{t}" for t in remapped ]
      node.apply_classify(wiki_summary = summary or "", topics = prefixed, connectors = None)
      nodes_changed += 1
      tags_remapped += hits
    return {
      self._K_SCOPE:         self._scope_id,
      self._K_NODES_CHANGED: nodes_changed,
      self._K_TAGS_REMAPPED: tags_remapped,
    }

  # ── helpers ───────────────────────────────────────────────────────────────

  @classmethod
  def _bare_topics(cls, node: _nodes.MarkdownNode | _nodes.CodeNode) -> list[str]:
    """
    Return a node's topic tags as bare `<axis>/<value>` strings.

    Returns:
      The node's topics with any `wiki/` namespace prefix stripped.
    """
    # guard: markdown stores prefixed `wiki/*` tags — strip the namespace
    if isinstance(node, _nodes.MarkdownNode):
      return [
        t[len(cls._WIKI_PREFIX):] if t.startswith(cls._WIKI_PREFIX) else t
        for t in node.wiki_tags
      ]
    return list(node.topics)

  @staticmethod
  def _summary(node: _nodes.MarkdownNode | _nodes.CodeNode) -> str | None:
    """
    Return a node's current one-line summary, or None when unset.

    Returns:
      The node's summary string, or None when it has none.
    """
    # guard: markdown and code expose the summary under different accessors
    if isinstance(node, _nodes.MarkdownNode):
      return node.wiki_summary
    return node.summary

  @classmethod
  def _axis_values(cls, node: _nodes.MarkdownNode | _nodes.CodeNode) -> list[tuple[str, str]]:
    """
    Return a node's well-formed `(axis, value)` topic pairs.

    Returns:
      The `(axis, value)` pairs split from the node's bare topics; tags
      without an axis/value split are omitted.
    """
    out: list[tuple[str, str]] = []
    for tag in cls._bare_topics(node):
      axis, sep, value = tag.partition("/")
      # guard: skip a tag with no axis/value split
      if sep and value:
        out.append((axis, value))
    return out

  @classmethod
  def _remap(cls, bare: list[str], alias_map: dict) -> tuple[list[str], int]:
    """
    Apply the alias map to bare topics, de-duplicating collapsed values.

    Args:
      bare: Bare `<axis>/<value>` topic strings.
      alias_map: `{<axis>: {<old-value>: <new-value>}}`.

    Returns:
      A tuple `(new_topics, hits)` — the remapped, order-preserving,
      de-duplicated topic list and the number of tags the map matched.
    """
    out: list[str] = []
    seen: set = set()
    hits = 0
    for tag in bare:
      axis, sep, value = tag.partition("/")
      new_tag = tag
      # guard: this axis/value is aliased
      if sep and axis in alias_map and value in alias_map[axis]:
        new_tag = f"{axis}/{alias_map[axis][value]}"
        hits += 1
      # guard: drop a duplicate produced by a collapse
      if new_tag not in seen:
        seen.add(new_tag)
        out.append(new_tag)
    return out, hits
