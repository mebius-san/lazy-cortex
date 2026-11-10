"""
Tag-consistency primitives for lazycortex-wiki.

Deterministic, scope-level operations that keep a wiki scope's topic tags and its advisory tag-values dictionary
consistent, uniformly over markdown and code nodes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import domains as _domains  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import explainers as _explainers  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import nodes as _nodes  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import scope as _scope  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# File encoding used throughout this module.
_ENCODING = "utf-8"

# Surface id of the generated domain-spec doc tree — not a configured wiki scope.
_SURFACE_DOMAINS = "domains"

# Key under which `TagOps.collect` reports the per-axis value lists.
COLLECT_AXES = "axes"
# Key naming one value entry's value in a `TagOps.collect` axis list.
COLLECT_VALUE = "value"

# Dictionary markdown markers: the heading that opens an axis section, and a value bullet.
_AXIS_HEADING = "## "
# Separator between a dictionary bullet's value and its gloss.
_GLOSS_SEP = " — "
# Line break the dictionary text is assembled with.
_NL = "\n"
_VALUE_BULLET = "- "


# ----------------------------------------------------------------------------------------
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
  return _scope.read_dictionary_rel(repo)


# ----------------------------------------------------------------------------------------
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

  # each axis keeps its values in file order; the glosses are for human readers
  return { axis: list(entries) for axis, entries in dictionary_entries(repo).items() }


# ----------------------------------------------------------------------------------------
def dictionary_entries(repo: Path) -> dict[str, dict[str, str]]:
  """
  Read the per-axis values of the tag-values dictionary together with their glosses.

  Args:
    repo: Absolute repository root that owns the dictionary file.

  Returns:
    A dict `{<axis>: {<value>: <gloss>}}` built from the dictionary's `## <axis>` sections and their
    `- <value> — <gloss>` bullets, in file order; a value repeated within an axis keeps its first gloss, and a
    value without a gloss maps to an empty string. Empty when the file is absent or unreadable — the dictionary
    is advisory, so neither case is an error.
  """
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
  out: dict[str, dict[str, str]] = {}
  axis: str | None = None
  for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith(_AXIS_HEADING):
      axis = stripped[len(_AXIS_HEADING):].strip()
      out.setdefault(axis, {})
      continue

    # guard: a bullet before the first heading names no axis, and prose names no value
    if axis is None or not stripped.startswith(_VALUE_BULLET):
      continue
    body = stripped[len(_VALUE_BULLET):]
    parts = body.split()

    # guard: an empty bullet carries no value
    if not parts:
      continue

    # the value is the bullet's first token; the first occurrence of a value keeps its gloss
    value = parts[0]
    if value not in out[axis]:
      _, sep, gloss = body.partition(_GLOSS_SEP)
      out[axis][value] = gloss.strip() if sep else ""
  return out


# ----------------------------------------------------------------------------------------
@dataclass
class RetagResult:
  """
  Outcome of applying an alias map to a scope's nodes.

  Reports how much a retag changed and which files it rewrote, so a caller can commit exactly those files.

  Attributes:
    nodes_changed: Number of nodes whose tags the alias map rewrote.
    tags_remapped: Number of tags the alias map matched across those nodes.
    changed_paths: Files of the rewritten nodes, in enumeration order.
  """

  # Nodes whose tags the alias map rewrote
  nodes_changed: int = 0
  # Tags the alias map matched across those nodes
  tags_remapped: int = 0
  # The files of the rewritten nodes, in enumeration order
  changed_paths: list[Path] = field(default_factory = list)


# ----------------------------------------------------------------------------------------
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

  # Collect-result dict keys.
  _K_SCOPE    = "scope"
  _K_AXES     = COLLECT_AXES
  _K_VALUE    = COLLECT_VALUE
  _K_COUNT    = "count"
  _K_EXAMPLES = "examples"

  # Retag-result dict keys.
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

    # emit the tally with axes and their values in sorted order, so the survey reads the same on every run
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
      - Rewrites nodes exactly as `retag_detailed` does; the result only omits the list of rewritten files.

    Args:
      alias_map: `{<axis>: {<old-value>: <new-value>}}`.

    Returns:
      A dict `{"scope": <id>, "nodes_changed": <n>, "tags_remapped": <m>}`.
    """

    # the dict form is the detailed result without its path list
    detailed = self.retag_detailed(alias_map)
    return {
      self._K_SCOPE:         self._scope_id,
      self._K_NODES_CHANGED: detailed.nodes_changed,
      self._K_TAGS_REMAPPED: detailed.tags_remapped,
    }

  def retag_detailed(self, alias_map: dict) -> RetagResult:
    """
    Apply an axis-value alias map to every node's tags and report the files it rewrote.

    Behaves exactly like `retag`, but additionally names each rewritten file so the caller can commit them.

    Guarantees:
      - The rewritten files are listed in node enumeration order, and only nodes that actually changed appear.
      - Only tags whose axis and value the map lists are rewritten; every other tag a node carries is left
        unchanged.
      - Collapsing an alias onto a value a node already carries leaves a single copy of that tag, never a
        duplicate.
      - A repeated call with the same alias map after a successful one changes nothing.
      - A node's summary and stored source hash are never changed; only the topic tags the map matches are
        rewritten.

    Args:
      alias_map: `{<axis>: {<old-value>: <new-value>}}`.

    Returns:
      The counts of changed nodes and remapped tags together with the paths of the changed nodes.
    """

    # Contract:
    # The changed paths name exactly the nodes whose tags were rewritten, in node
    # enumeration order; a node left unchanged NEVER appears, so callers can commit
    # precisely those files.

    # Contract:
    # Only tags whose axis and value the alias map lists are rewritten; every
    # other tag a node carries MUST be left unchanged.

    # Contract:
    # Collapsing an alias onto a value a node already carries leaves a single
    # copy of that tag; a rewrite NEVER duplicates a tag.

    # Contract:
    # A repeated call with the same alias map after a successful one changes
    # nothing.

    # Contract:
    # A retag NEVER changes a node's summary or its stored source hash; only the topic tags the
    # alias map matches are rewritten.

    # Domain(wiki.taxonomy):
    # # Normalising values within an axis
    # An axis drifts once several names accumulate for a single meaning. Normalisation settles the drift by
    # declaring one name canonical and every rival an alias of it, then rewriting each alias to the canonical name
    # wherever a node carries it. The decision is confined to one axis: the same name under another axis means
    # something else and is never touched, and neither is any value nobody declared an alias, so an axis can be
    # normalised without disturbing the rest of the taxonomy. Folding an alias onto a value a node already carries
    # leaves that node with one copy rather than two, and once every alias has been rewritten the same declaration
    # has nothing left to change.

    # count the nodes and tags the alias declaration actually rewrites, and keep the files it wrote
    result = RetagResult()
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

      # only the topics are rewritten: the summary stays, and so does the stored source hash, so an
      # operator edit made since the last curation still reads as pending
      prefixed = [ f"{self._WIKI_PREFIX}{tag}" for tag in remapped ]
      node.apply_classify(topics = prefixed, stamp_src_hash = False)
      result.nodes_changed += 1
      result.tags_remapped += hits
      result.changed_paths.append(node_path)
    return result

  def _iter_node_paths(self) -> list[Path]:
    """
    Return the node paths this instance operates over.

    Returns:
      The fixed enumeration passed to the constructor when set (the
      `for_domains` surface); otherwise the configured scope's nodes,
      resolved fresh on every call.
    """
    # a fixed enumeration overrides scope-config resolution
    if self._node_paths is not None:
      return self._node_paths

    # otherwise the configured scope's nodes, resolved fresh
    return self._resolver.find_all_nodes(self._cfg)

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
    # markdown stores prefixed `wiki/*` tags — strip the namespace
    if isinstance(node, _nodes.MarkdownNode):
      return [
        tag[len(cls._WIKI_PREFIX):] if tag.startswith(cls._WIKI_PREFIX) else tag
        for tag in node.wiki_tags
      ]

    # a code node already stores its topics bare
    return list(node.topics)

  @staticmethod
  def _summary(node: _nodes.MarkdownNode | _nodes.CodeNode) -> str | None:
    """
    Return a node's current one-line summary, or None when unset.

    Returns:
      The node's summary string, or None when it has none.
    """
    # markdown and code expose the summary under different accessors
    if isinstance(node, _nodes.MarkdownNode):
      return node.wiki_summary

    # a code node's own summary accessor
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


# ----------------------------------------------------------------------------------------
class TagDictionary:
  """
  Advisory tag-values dictionary of one repository.

  Produces the dictionary text that follows a canon pass over a tag surface and reports which values still need a
  gloss before that text is complete.
  """

  def __init__(self, *, repo: Path) -> None:
    """
    Bind the dictionary to one repository.

    Args:
      repo: Absolute repository root that owns the dictionary file and the language its intro is written in.
    """
    # the repository whose dictionary file and language the merge reads
    self._repo = Path(repo)

  @property
  def path(self) -> Path:
    """
    Absolute path of the dictionary file.

    Notes:
      - The file need not exist yet.
    """
    return self._repo / dictionary_rel(self._repo)

  def merge(self,
            *,
            post_values: dict[str, list[str]],
            alias_map: dict,
            glosses: dict[str, dict[str, str]]) -> str:
    """
    Compose the dictionary text that follows a canon pass.

    Guarantees:
      - Values the dictionary already records stay, even when the surface no longer wears them.
      - A renamed value keeps the gloss it had under its old name, unless the new name already has an entry of its
        own, whose gloss is kept instead.
      - A supplied gloss replaces the recorded one.
      - Axes and values are listed alphabetically, so an unchanged vocabulary yields text identical to the
        existing dictionary.

    Notes:
      - The dictionary file is only read; writing the returned text is the caller's job.

    Args:
      post_values: `{<axis>: [<value>, ...]}` the surface carries once the canon is applied.
      alias_map: `{<axis>: {<old-value>: <new-value>}}` the canon renamed.
      glosses: `{<axis>: {<value>: <gloss>}}` supplied with the canon.

    Returns:
      The full dictionary markdown, ending with a newline.
    """

    # Contract:
    # Every value the dictionary already records stays in the returned text,
    # even when the surface no longer wears it.

    # Contract:
    # A renamed value keeps the gloss it had under its old name; when the new name
    # already has an entry of its own, that entry's gloss is kept instead.

    # Contract:
    # A gloss supplied for a recorded or worn value replaces the recorded one.

    # Contract:
    # Axes and values are listed alphabetically, so an unchanged vocabulary
    # MUST yield text identical to the existing dictionary.

    # Domain(wiki.taxonomy):
    # # Rewriting the dictionary after a canon pass
    # The dictionary is the union of what it already recorded and the values the surface carries once the
    # canon is applied. A value the dictionary records and this surface does not wear is kept, because
    # another surface may be the one wearing it. A value the canon renamed takes its new name and keeps its
    # gloss, since the meaning it covered did not move. When the new name already has an entry of its own,
    # the two values merge into that entry: it keeps its gloss and the gloss of the old name is dropped,
    # because the established entry already defines the surviving value. A gloss supplied with the canon
    # replaces the one recorded. Axes and values are listed alphabetically, so an unchanged vocabulary
    # rewrites to the same text.

    entries = self._renamed(alias_map)

    # every value the surface now carries has an entry; a supplied gloss replaces the recorded one
    for axis, values in post_values.items():
      section = entries.setdefault(axis, {})
      for value in values:
        section.setdefault(value, "")
    for axis, supplied in glosses.items():
      section = entries.get(axis, {})
      for value, gloss in supplied.items():
        # guard: a gloss for a value neither recorded nor worn adds no entry of its own
        if value not in section:
          continue
        section[value] = gloss

    # the fetched intro, then one section per axis and one bullet per value, both alphabetical
    lang = _explainers.language_code(_explainers.resolve_language(self._repo))
    blocks = [ _explainers.text_for(_explainers.TEXT_TAG_DICTIONARY_INTRO, lang) ]
    for axis in sorted(entries):
      bullets = [ f"{_VALUE_BULLET}{value}{_GLOSS_SEP}{entries[axis][value]}" for value in sorted(entries[axis]) ]
      blocks.append(_NL.join([ f"{_AXIS_HEADING}{axis}", "", *bullets ]))
    return (_NL + _NL).join(blocks) + _NL

  def find_all_missing_glosses(self,
                      *,
                      post_values: dict[str, list[str]],
                      alias_map: dict,
                      glosses: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """
    List the values the surface carries that have no gloss yet.

    Args:
      post_values: `{<axis>: [<value>, ...]}` the surface carries once the canon is applied.
      alias_map: `{<axis>: {<old-value>: <new-value>}}` the canon renamed.
      glosses: `{<axis>: {<value>: <gloss>}}` supplied with the canon.

    Returns:
      Sorted `(axis, value)` pairs that neither the dictionary (after the renames) nor the supplied glosses
      cover; empty when every value is covered.
    """
    entries = self._renamed(alias_map)

    # a value needs a gloss when neither the dictionary (after renames) nor the supplied glosses carry a non-blank one
    return [
      (axis, value)
      for axis in sorted(post_values)
      for value in sorted(set(post_values[axis]))
      if not entries.get(axis, {}).get(value, "").strip() and not glosses.get(axis, {}).get(value, "").strip()
    ]

  def _renamed(self, alias_map: dict) -> dict[str, dict[str, str]]:
    """
    Read the dictionary entries with the canon's renames applied.

    Args:
      alias_map: `{<axis>: {<old-value>: <new-value>}}` the canon renamed.

    Returns:
      The `{<axis>: {<value>: <gloss>}}` entries in which each recorded old value has moved to its new name along
      with its gloss; a new name that already has its own gloss keeps it.
    """
    entries = dictionary_entries(self._repo)

    # a renamed value takes its new name and keeps its gloss, unless the new name already has its own
    for axis, renames in alias_map.items():
      section = entries.get(axis)

      # guard: an axis the dictionary does not record has nothing to rename
      if section is None or not isinstance(renames, dict):
        continue
      for old, new in renames.items():
        # guard: only a recorded value carries a gloss to move
        if old not in section:
          continue
        gloss = section.pop(old)
        section.setdefault(new, gloss)
    return entries
