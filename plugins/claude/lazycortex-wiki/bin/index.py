"""
Deterministic topic-index builder for lazycortex-wiki.

`TopicIndex` reads every node in a scope, groups them by their `wiki/*`
topic tags, and writes a deterministic `topics.md` file — the categorical
entry point for LLM navigation over a wiki scope.  No LLM judgment
involved: what the nodes declare in their tags is exactly what the index
reflects.

Both markdown nodes (`MarkdownNode`) and code nodes (`CodeNode`) are
indexed.  The factory `node_for` selects the correct class; unrecognised
file types are silently skipped.
"""
from __future__ import annotations

from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import explainers as _explainers  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import nodes as _nodes  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import scope as _scope  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from textfile import TextFile  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Wiki frontmatter key and value written into topics.md.
_KEY_WIKI_ROLE = "wiki_role"
_VAL_WIKI_ROLE = "topics-index"

# Anchor key preserved across rebuilds; never dropped if already present.
_KEY_WIKI_SYNCED_SHA = "wiki_synced_sha"

# Prefix that identifies wiki-owned topic tags.
_WIKI_TAG_PREFIX = "wiki/"

# Separator joining connector phrases on a node's index sub-line.
_CONNECTOR_SEP = "; "

# Separator joining path segments in a node's link text when its file name alone is not unique.
_LINK_TEXT_SEP = " · "

# Inline marker preceding the connectors sub-line in a node entry.
_CONNECTOR_PREFIX = "  · connectors: "

# File encoding used for all read/write in this module.
_ENCODING = "utf-8"


# ────────────────────────────────────────────────────────────────────────────
class TopicIndex:
  """
  Build and write the deterministic `topics.md` for a single wiki scope.

  One instance per invocation; create, call `build`, discard.  The output
  file is idempotent: identical scope state → byte-identical file every run.

  Guarantees:
    - The written index lists a node under exactly the topics that node declares, and never under a topic
      inferred for it.
  """

  # Contract:
  # The index is a projection of what the nodes declare about themselves: a node
  # is listed under exactly the topic tags it carries, and NEVER under a topic
  # inferred, guessed, or otherwise derived from anything but those tags.

  # Config key for the topics-index output path.
  _CFG_TOPICS_INDEX = "topics_index"

  # Default relative path when `topics_index` is absent from the config.
  _DEFAULT_TOPICS_INDEX = "wiki/topics.md"

  # Config key holding the index badges: the frontmatter keys shown as badges on node lines.
  _CFG_INDEX_BADGES = "index_badges"

  def __init__(self, *, repo: Path, cfg: dict, scope_id: str) -> None:
    """
    Initialise the builder for one scope.

    Args:
      repo: Absolute path to the repository root.
      cfg: Scope-config dict from `lazy.settings.json[wiki.scopes][<id>]`.
      scope_id: Human-readable scope identifier used in the document title.
    """
    self._repo = Path(repo).resolve()
    self._cfg = cfg
    self._scope_id = scope_id
    self._resolver = _scope.ScopeResolver(repo = self._repo)

  # ── public ────────────────────────────────────────────────────────────────

  def build(self) -> Path:
    """
    Build the topic tree and write `topics.md` to the configured path.

    Nodes that carry no `wiki/*` tags and have no `wiki_summary` are
    skipped entirely — there is nothing meaningful to index.  Nodes with
    `wiki/*` tags but no summary appear under their tags with an empty
    gloss.  Files of an unsupported type are skipped gracefully.

    Guarantees:
      - Rebuilding an unchanged scope writes a byte-identical file; the output never depends on the order
        in which the scope's files are encountered.
      - A `wiki_synced_sha` anchor already present in the index survives the rebuild unchanged.

    Returns:
      Absolute path to the written `topics.md` file.
    """

    # Contract:
    # Rebuilding a scope whose state has not changed MUST produce a byte-identical
    # file; the written content NEVER depends on the order in which the scope's
    # files are encountered.

    # Contract:
    # A `wiki_synced_sha` anchor already present in the index MUST survive the
    # rebuild unchanged; the builder never drops nor rewrites it.

    # assemble the catalog from the scope's nodes and write it to the configured path
    node_paths = self._resolver.iter_nodes(self._cfg)
    index_path = self._resolve_index_path()
    synced_sha = self._read_synced_sha(index_path)
    tree = self._collect_tree(node_paths, index_path)
    content = self._render(tree, synced_sha)
    index_path.parent.mkdir(parents = True, exist_ok = True)
    TextFile(path = index_path).write(content)
    return index_path

  def _read_synced_sha(self, index_path: Path) -> str | None:
    """
    Read any existing `wiki_synced_sha` from the current topics.md frontmatter.

    The anchor is operator/relink state that the deterministic rebuild must
    never drop — when the index file already exists with the key, its value
    is carried through to the freshly-rendered output.

    Args:
      index_path: Absolute path to the topics.md file.

    Returns:
      The current `wiki_synced_sha` value, or `None` when the file or key is absent.
    """

    # Domain(wiki.graph):
    # # Relink anchor of a scope
    # Curation of a scope advances incrementally: the catalog carries an anchor naming the repository state
    # the last relinking pass covered, and the next pass reclassifies and re-links only what changed since
    # then. The anchor is bookkeeping owned by the curation pass rather than content derived from the nodes,
    # so rebuilding the catalog carries whatever anchor it finds through untouched — dropping it would
    # silently downgrade the next pass into a full re-curation of the whole scope. A scope with no anchor yet
    # is one that has never been curated, and its first pass covers every node.

    # guard: no index file yet — there is no anchor to preserve
    if not index_path.is_file():
      return None
    text = index_path.read_text(encoding = _ENCODING)
    return _nodes.get_scalar_field(text, _KEY_WIKI_SYNCED_SHA)

  # ── private ───────────────────────────────────────────────────────────────

  def _resolve_index_path(self) -> Path:
    """
    Return the absolute path to the `topics_index` file.

    Returns:
      Absolute `Path` derived from `cfg["topics_index"]` relative to
      the repository root.
    """
    raw: str = self._cfg.get(self._CFG_TOPICS_INDEX, self._DEFAULT_TOPICS_INDEX)
    return (self._repo / raw).resolve()

  def _collect_tree(
    self,
    node_paths: list[Path],
    index_path: Path,
  ) -> dict[str, dict[str, list[tuple[str, str, str | None, list[str], list[str]]]]]:
    """
    Traverse node files and build the axis → value → node-entries tree.

    Each entry in the innermost list is `(rel_link, link_text, summary,
    connectors, badges)`, where `link_text` is the shortest name that tells the node apart from every other
    listed node of the scope: the file name without its extension, plus enclosing folders only as far as
    needed, the parts joined by a middle dot.  The name is judged across all listed nodes of the scope, so
    it is identical under every topic the node is listed under.  `badges` holds one `<key>: <value>` string
    per configured index badge the node carries with a single-line value, in config
    order.  A node may appear
    under multiple axes / values when it carries multiple `wiki/*` tags.  All
    keys and entry lists are sorted for determinism.

    Args:
      node_paths: Absolute paths of candidate nodes from `iter_nodes`.
      index_path: Absolute path of the topics.md file; used to compute
        relative links from the index's directory to each node.

    Returns:
      Nested dict: `{axis: {value_path: [(rel_link, link_text, summary_or_None, connectors, badges), ...]}}`.
      All outer and inner keys are in sorted order; inner lists are sorted
      by `rel_link`.
    """

    # Domain(wiki.taxonomy):
    # # Topic catalog of a scope
    # A wiki scope is entered through a single categorical catalog that groups the scope's nodes by the topics
    # they declare. The catalog is a projection of what the nodes say about themselves, never an independent
    # judgement: a node is listed under exactly the topics it carries, and a node carrying several topics is
    # listed once under each of them. A node earns a place by declaring at least one topic or a one-line
    # gloss; one that declares neither says nothing about itself and stays out, as do files of a kind the wiki
    # does not know how to read. Each listing is named by the node's file name; when several listed nodes share
    # a file name, each of them takes on its enclosing folders, one at a time and only as far as needed to tell
    # it apart from the others, the parts separated by a middle dot. Only nodes the catalog actually lists count
    # when judging whether a name is shared, and the judgement spans the whole scope rather than one topic, so a
    # node keeps the same name under every topic it is listed under. Each listing shows the node's gloss, so a
    # reader can judge whether to open the node without opening it, and the node's connector phrases follow it —
    # the short facets by which the
    # node can be reached from elsewhere — whenever it declares any. A scope may also name a few frontmatter
    # keys whose values the catalog shows beside each listing, between the node's name and its gloss, as short
    # badges in the order the scope names them — a declared state such as a document's stage, readable without
    # opening the node. A node that does not carry a named key simply shows no badge for it, nor does one whose
    # value spans several lines, since a badge sits on the listing's single line; a node of a kind without
    # frontmatter shows none at all, and a scope that names no keys shows plain listings with no badges. The
    # catalog is derived from the current state of the scope alone and ordered stably, so the same state always
    # yields the same catalog.

    # index badges: a list of key names; any other shape names no badges, and non-string items are skipped
    raw_keys = self._cfg.get(self._CFG_INDEX_BADGES)
    index_badges = [ k for k in raw_keys if isinstance(k, str) ] if isinstance(raw_keys, list) else []

    # Raw accumulator: axis → value_path → list of (rel_link, link_text, summary, connectors, badges)
    raw: dict[str, dict[str, list[tuple[str, str, str | None, list[str], list[str]]]]] = {}

    # keep only the nodes the catalog will list, so their names are judged among them alone
    indexed: list[tuple[Path, list[str], str | None, list[str], list[str]]] = []
    for node_path in node_paths:
      node = _nodes.node_for(node_path)

      # guard: unrecognised file type — skip gracefully
      if node is None:
        continue

      # Normalise the two node types to common wiki_tags, summary, badges, and connectors.
      if isinstance(node, _nodes.MarkdownNode):
        wiki_tags = node.wiki_tags
        summary = node.wiki_summary
        badges: list[str] = []
        for key in index_badges:
          value = node.frontmatter_scalar(key)

          # guard: the key is absent, or its value spans lines and would break the one-line listing
          if value is None or "\n" in value:
            continue
          badges.append(f"{key}: {value}")
      else:
        # CodeNode: topics are plain `axis/value` strings; prefix with `wiki/`
        # so `_split_tag` can extract the axis and value in the same way.
        wiki_tags = [ f"{_WIKI_TAG_PREFIX}{t}" for t in node.topics ]
        summary = node.summary
        # a code node has no frontmatter, so no badge
        badges = []
      connectors = node.connectors

      # guard: nothing to index — no wiki tags and no summary
      if not wiki_tags and summary is None:
        continue
      indexed.append((node_path, wiki_tags, summary, connectors, badges))

    # every listed node gets one name, the shortest path tail that sets it apart from the other listed nodes
    link_texts = self._compute_link_texts([ entry[0] for entry in indexed ])

    # fold every listed node into each axis/value bucket its tags name
    for node_path, wiki_tags, summary, connectors, badges in indexed:
      # every bucket entry for this node shares the same label and link
      link_text = link_texts[node_path]
      rel_link = self._relative_link(node_path, index_path)

      # a node appears once under each axis/value pair it is tagged with
      for tag in wiki_tags:
        axis, value_path = self._split_tag(tag)

        # guard: malformed tag — skip
        if axis is None or value_path is None:
          continue

        # grow the nesting on demand, then record this node under the pair
        raw.setdefault(axis, {})
        raw[axis].setdefault(value_path, [])
        raw[axis][value_path].append((rel_link, link_text, summary, connectors, badges))

    # Sort: axes → values → nodes (by rel_link for stability)
    result: dict[str, dict[str, list[tuple[str, str, str | None, list[str], list[str]]]]] = {}
    for axis in sorted(raw):
      result[axis] = {}
      for value_path in sorted(raw[axis]):
        result[axis][value_path] = sorted(raw[axis][value_path], key = lambda t: t[0])

    # the sorted mirror is what the renderer walks
    return result

  def _compute_link_texts(self, node_paths: list[Path]) -> dict[Path, str]:
    """
    Name each listed node by the shortest tail of its repo-relative path that no other listed node shares.

    The name starts as the file name without its extension and takes on enclosing folders one at a time, only
    while another listed node bears the same name; the parts are joined by a middle dot.  A node whose name
    still collides once its whole path is used keeps the full path name.

    Args:
      node_paths: Absolute paths of every node the index lists; uniqueness is judged among these alone.

    Returns:
      Mapping of each node path to its link text.
    """

    # each node's path segments from the repository root, the file named without its extension
    segments: dict[Path, list[str]] = {}
    for node_path in node_paths:
      rel = node_path.relative_to(self._repo) if node_path.is_relative_to(self._repo) else node_path
      segments[node_path] = [ *rel.parent.parts, rel.stem ]

    # every name starts as the bare file name and grows one folder at a time only while it collides
    depth = dict.fromkeys(node_paths, 1)
    while True:
      texts = { node: _LINK_TEXT_SEP.join(segments[node][-depth[node]:]) for node in node_paths }
      holders: dict[str, list[Path]] = {}
      for node_path, text in texts.items():
        holders.setdefault(text, []).append(node_path)

      # lengthen every colliding name that still has a folder left to take
      grown = False
      for members in holders.values():
        # guard: a name held by one node is already unique
        if len(members) < 2:
          continue
        for node_path in members:
          # guard: the whole path is already used, nothing left to add
          if depth[node_path] >= len(segments[node_path]):
            continue
          depth[node_path] += 1
          grown = True

      # guard: a pass that lengthened nothing has settled every name
      if not grown:
        return texts

  def _split_tag(self, tag: str) -> tuple[str | None, str | None]:
    """
    Split a `wiki/<axis>/<value...>` tag into `(axis, value_path)`.

    The `wiki/` prefix is stripped, then the first path segment is the
    axis and everything after is the value path joined back with `/`.
    Tags without both an axis and at least one value segment return
    `(None, None)`.

    Args:
      tag: A tag string starting with `wiki/`.

    Returns:
      `(axis, value_path)` or `(None, None)` when the tag is malformed.
    """

    # Domain(wiki.taxonomy):
    # # Shape of a topic tag
    # A topic tag names one classification axis and the value a node takes on that axis, written as
    # `wiki/<axis>/<value>`: the leading segment marks the tag as wiki-owned, so tags that belong to anything
    # else are left alone. The first segment after that marker is the axis, and everything left over is the
    # value, which may itself be nested — an axis carries a hierarchy of values rather than a flat list. A tag
    # that names an axis with no value under it classifies nothing and is ignored rather than treated as an
    # error, so one malformed tag never costs a node its other topics.

    # guard: does not start with the wiki prefix
    if not tag.startswith(_WIKI_TAG_PREFIX):
      return None, None

    # everything past the prefix is the axis plus its value segments
    rest = tag[len(_WIKI_TAG_PREFIX):]
    segs = rest.split("/")

    # guard: fewer than two segments means no value under the axis
    if len(segs) < 2:
      return None, None

    # first segment names the axis; the remainder re-joins as a nested value path
    axis = segs[0]
    value_path = "/".join(segs[1:])
    return axis, value_path

  def _relative_link(self, node_path: Path, index_path: Path) -> str:
    """
    Compute a relative POSIX path from the index directory to the node.

    Args:
      node_path: Absolute path of the node file.
      index_path: Absolute path of the `topics.md` file.

    Returns:
      Relative POSIX path string usable as a markdown link target.
    """
    index_dir = index_path.parent
    try:
      return node_path.relative_to(index_dir).as_posix()
    except ValueError:
      # guard: node is not under the index directory — build a ../.. path
      parts_index = index_dir.parts
      parts_node = node_path.parts
      common_len = sum(
        1 for a, b in zip(parts_index, parts_node, strict=False) if a == b
      )
      ups = len(parts_index) - common_len
      down = "/".join(parts_node[common_len:])
      return "../" * ups + down

  def _render(
    self,
    tree: dict[str, dict[str, list[tuple[str, str, str | None, list[str], list[str]]]]],
    synced_sha: str | None,
  ) -> str:
    """
    Render the topic tree as a `topics.md` markdown document.

    Format:
    - YAML frontmatter with `wiki_role: topics-index`, and `wiki_synced_sha`
      when an anchor was preserved from the previous index.
    - `# Topics — <scope_id>` title.
    - `## <axis>` for each axis.
    - `### <axis>/<value_path>` for each value under an axis.
    - `- [<link_text>](<rel_link>) [<key>: <value>] — <summary>` per node,
      one bracketed badge per configured index badge the node carries, in
      config order; with no badges the line keeps its plain
      `- [<link_text>](<rel_link>) — <summary>` shape, and when the node has
      no summary the ` — <summary>` suffix is omitted.
    - `  · connectors: <a>; <b>` continuation sub-line under a node when it
      carries connectors; omitted entirely when the node has none.

    Args:
      tree: Nested dict from `_collect_tree`.
      synced_sha: The `wiki_synced_sha` anchor to re-emit, or `None` to omit it.

    Returns:
      Complete document string, terminated by a trailing newline.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append(f"{_KEY_WIKI_ROLE}: {_VAL_WIKI_ROLE}")

    # carry the anchor through only when the prior index had one
    if synced_sha is not None:
      lines.append(f"{_KEY_WIKI_SYNCED_SHA}: {synced_sha}")
    lines.append("---")
    lines.append(f"# Topics — {self._scope_id}")

    # the file self-describes for the operator, in the vault's language
    lines.append(_explainers.explainer_line(
        _explainers.SURFACE_TOPICS, _explainers.resolve_language(self._repo)))

    # one section per axis, each opened by a blank line so headings stay readable
    for axis, values in tree.items():
      lines.append("")
      lines.append(f"## {axis}")
      for value_path, entries in values.items():
        lines.append(f"### {axis}/{value_path}")
        for rel_link, link_text, summary, connectors, badges in entries:
          # link, then any badges, then the gloss when the node has one
          head = f"- [{link_text}]({rel_link})"
          if badges:
            head += " " + " ".join(f"[{b}]" for b in badges)
          lines.append(f"{head} — {summary}" if summary else head)

          # emit the connectors sub-line only when the node has any
          if connectors:
            lines.append(f"{_CONNECTOR_PREFIX}{_CONNECTOR_SEP.join(connectors)}")

    # the empty last element gives the joined document its trailing newline
    lines.append("")
    return "\n".join(lines)
