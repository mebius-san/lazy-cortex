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

import os
from pathlib import Path

import domains as _domains
import nodes as _nodes
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# File encoding used throughout this module.
_ENCODING = "utf-8"

# Surface id of the generated domain-spec doc tree — not a configured wiki scope.
_SURFACE_DOMAINS = "domains"

# Key under which `TagOps.collect` reports the per-axis value lists.
COLLECT_AXES = "axes"

# Dictionary markdown markers: the heading that opens an axis section, and a value bullet.
_AXIS_HEADING = "## "
_VALUE_BULLET = "- "


# ────────────────────────────────────────────────────────────────────────────
def dictionary_rel(repo: Path) -> str:
  """
  Return the repo-relative path of the tag-values dictionary.

  Args:
    repo: Absolute repository root that owns `.claude/lazy.settings.json`.

  Returns:
    The `wiki.tags.dictionary` value from settings, or the default path
    `docs/tags.md` when unset, malformed, or the settings file itself
    is missing or unparsable. The dictionary is advisory — its absence on
    disk is not an error for this reader.
  """
  # the reader lives in scope.py so domains.py can reach it without importing this module
  return _scope.dictionary_rel(repo)


# ────────────────────────────────────────────────────────────────────────────
def dictionary_values(repo: Path) -> dict[str, list[str]]:
  """
  Read the per-axis value lists recorded in the tag-values dictionary.

  Args:
    repo: Absolute repository root that owns the dictionary file.

  Returns:
    A dict `{<axis>: [<value>, ...]}` built from the dictionary's `## <axis>`
    sections and their `- <value> — <gloss>` bullets, values de-duplicated and
    in file order. Empty when the file does not exist — the dictionary is
    advisory, so its absence is not an error.
  """

  # Domain(wiki.taxonomy):
  # # Why the dictionary outlives the values in use
  # A census of an axis can only report the values nodes carry right now, so a value that was canonised and
  # then fell out of use disappears from it entirely — and the next classification, seeing no trace of it,
  # coins a synonym and the drift starts over. The dictionary is what keeps that decision alive: it records
  # the settled vocabulary independently of who currently wears it, which is exactly what a fresh judgement
  # needs to anchor to. It advises rather than binds — nothing is refused for being absent from it.

  dictionary = Path(repo) / dictionary_rel(repo)
  # guard: the dictionary is advisory — an absent file simply contributes nothing
  if not dictionary.is_file():
    return {}

  # guard: the dictionary is advisory — an undecodable or unreadable file contributes nothing
  # rather than halting every classify dispatch that reads it
  try:
    text = dictionary.read_text(encoding = _ENCODING)
  except (OSError, UnicodeDecodeError):
    return {}

  # walk the file top-down: each heading opens the section its following bullets belong to
  out: dict[str, list[str]] = {}
  axis: str | None = None
  for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith(_AXIS_HEADING):
      axis = stripped[len(_AXIS_HEADING):].strip()
      out.setdefault(axis, [])
      continue
    # guard: a bullet before the first heading names no axis, and prose names no value
    if axis is None or not stripped.startswith(_VALUE_BULLET):
      continue
    parts = stripped[len(_VALUE_BULLET):].split()
    # guard: an empty bullet carries no value
    if not parts:
      continue
    # the value is the bullet's first token; the em-dash gloss after it is for human readers
    if parts[0] not in out[axis]:
      out[axis].append(parts[0])
  return out


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

  # Markdown extension filter used when enumerating the domains surface.
  _MD_EXT = ".md"

  # Max example summaries kept per tag value in a `collect` result.
  _MAX_EXAMPLES = 2

  # collect-result dict keys.
  _K_SCOPE    = "scope"
  _K_AXES     = COLLECT_AXES
  _K_VALUE    = "value"
  _K_COUNT    = "count"
  _K_EXAMPLES = "examples"

  # retag-result dict keys.
  _K_NODES_CHANGED = "nodes_changed"
  _K_TAGS_REMAPPED = "tags_remapped"

  def __init__(
    self,
    *,
    repo: Path,
    scope_id: str,
    cfg: dict,
    node_paths: list[Path] | None = None,
  ) -> None:
    """
    Initialise the tag operations for one scope.

    Args:
      repo: Absolute path to the repository root.
      scope_id: Scope identifier as configured in lazy.settings.json.
      cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
      node_paths: Fixed node enumeration to operate over instead of resolving
        `cfg` against a configured scope; used by `for_domains`. `None` for
        an ordinary scope-bound instance.
    """
    self._repo = repo
    self._scope_id = scope_id
    self._cfg = cfg
    self._node_paths = node_paths
    self._resolver = _scope.ScopeResolver(repo = repo)

  @classmethod
  def for_domains(cls, *, repo: Path) -> TagOps:
    """
    Construct tag operations over the generated domain-spec doc surface.

    Enumerates every markdown doc under `wiki.domains.output`, excluding the
    `domains.md` index, instead of resolving a configured wiki scope.

    Args:
      repo: Absolute repository root.

    Returns:
      A `TagOps` whose `collect`/`retag` calls report `scope: "domains"` and
      operate over the domain-spec output tree; enumerates zero nodes when
      `wiki.domains` is not configured or the output tree does not exist yet.
    """
    domain_cfg = _domains.DomainConfig.load(repo)
    node_paths = cls._domain_doc_paths(domain_cfg) if domain_cfg is not None else []
    return cls(repo = repo, scope_id = _SURFACE_DOMAINS, cfg = {}, node_paths = node_paths)

  # ── public ────────────────────────────────────────────────────────────────

  def collect(self) -> dict:
    """
    Survey the distinct tag values per axis across the scope.

    Guarantees:
      - Axes and their values are reported in sorted order, so two surveys of an unchanged scope return
        identical results.
      - The survey is read-only and never modifies any node in the scope.

    Returns:
      A dict `{"scope": <id>, "axes": {<axis>: [{"value", "count",
      "examples"}, ...]}}`. Axes and values are sorted; each value carries
      its node count and up to two example node summaries as light context.
    """

    # Contract:
    # Axes and their values are reported in sorted order; two surveys of an
    # unchanged scope MUST return identical results.

    # Contract:
    # The survey is read-only and NEVER modifies any node in the scope.

    # Domain(wiki.taxonomy):
    # # The value census of an axis
    # Normalising an axis is a judgement about meaning, and the evidence that judgement needs is a census: every
    # distinct value the axis holds, how many nodes carry it, and a couple of those nodes' summaries. The counts
    # expose the shape of the drift — a value worn by one node beside a near-synonym worn by thirty is the one to
    # fold, never the reverse — while the summaries say what the rare value was meant to mean, which its name alone
    # rarely settles. Axes and values are reported in a fixed order, so two censuses of an unchanged scope read the
    # same and only a real change in the taxonomy shows up as a difference.

    # tally the distinct values every axis holds across the scope
    axes: dict = {}
    for node_path in self._iter_node_paths():
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type — skip
      if node is None:
        continue
      summary = self._summary(node)
      for axis, value in self._axis_values(node):
        bucket = axes.setdefault(axis, {})
        entry = bucket.setdefault(value, { self._K_COUNT: 0, self._K_EXAMPLES: [] })
        entry[self._K_COUNT] += 1
        # keep a few distinct example summaries as light context
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

    Guarantees:
      - Only tags whose axis and value the map lists are rewritten; every other tag a node carries is left
        unchanged.
      - Collapsing an alias onto a value a node already carries leaves a single copy of that tag, never a
        duplicate.
      - A repeated call with the same alias map after a successful one changes nothing.

    Args:
      alias_map: `{<axis>: {<old-value>: <new-value>}}`.

    Returns:
      A dict `{"scope": <id>, "nodes_changed": <n>, "tags_remapped": <m>}`.
    """

    # Contract:
    # Only tags whose axis and value the alias map lists are rewritten; every
    # other tag a node carries MUST be left unchanged.

    # Contract:
    # Collapsing an alias onto a value a node already carries leaves a single
    # copy of that tag; a rewrite NEVER duplicates a tag.

    # Contract:
    # A repeated call with the same alias map after a successful one changes
    # nothing.

    # Domain(wiki.taxonomy):
    # # Normalising values within an axis
    # An axis drifts once several names accumulate for a single meaning. Normalisation settles the drift by
    # declaring one name canonical and every rival an alias of it, then rewriting each alias to the canonical name
    # wherever a node carries it. The decision is confined to one axis: the same name under another axis means
    # something else and is never touched, and neither is any value nobody declared an alias, so an axis can be
    # normalised without disturbing the rest of the taxonomy. Folding an alias onto a value a node already carries
    # leaves that node with one copy rather than two, and once every alias has been rewritten the same declaration
    # has nothing left to change.

    # count the nodes and tags the alias declaration actually rewrites
    nodes_changed = 0
    tags_remapped = 0
    for node_path in self._iter_node_paths():
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

  def _iter_node_paths(self) -> list[Path]:
    """
    Return the node paths this instance operates over.

    Returns:
      The fixed enumeration passed to the constructor when set (the
      `for_domains` surface); otherwise the configured scope's nodes,
      resolved fresh on every call.
    """
    # guard: a fixed enumeration overrides scope-config resolution
    if self._node_paths is not None:
      return self._node_paths
    return self._resolver.iter_nodes(self._cfg)

  @classmethod
  def _domain_doc_paths(cls, cfg: _domains.DomainConfig) -> list[Path]:
    """
    Enumerate every generated domain doc under the output tree, minus the index.

    Uses `os.walk` — stdlib `glob`/`rglob` are banned per the project tech
    conventions.

    Args:
      cfg: The repo's loaded domain-spec configuration.

    Returns:
      Sorted absolute paths of the output tree's markdown docs, excluding
      `domains.md`; empty when the output tree does not exist yet.
    """
    output_abs = cfg.repo / cfg.output
    index_abs = output_abs / _domains.INDEX_NAME
    # guard: output tree not generated yet — nothing to enumerate
    if not output_abs.is_dir():
      return []
    paths: list[Path] = []
    for base, _dirs, files in os.walk(str(output_abs)):
      for fname in files:
        # guard: only markdown docs carry tag-bearing frontmatter
        if not fname.endswith(cls._MD_EXT):
          continue
        abs_path = Path(base) / fname
        # guard: the index doc carries no per-group tags
        if abs_path == index_abs:
          continue
        paths.append(abs_path)
    return sorted(paths)

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
      # collect only the tags that carry both an axis and a value
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
      # rewrite the value when the alias map covers this axis
      if sep and axis in alias_map and value in alias_map[axis]:
        new_tag = f"{axis}/{alias_map[axis][value]}"
        hits += 1
      # keep the first occurrence of each tag so a collapse cannot duplicate
      if new_tag not in seen:
        seen.add(new_tag)
        out.append(new_tag)
    return out, hits
