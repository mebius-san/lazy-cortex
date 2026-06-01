"""
Candidate recall for lazycortex-wiki link curation.

`find-candidates` is the deterministic, non-LLM recall stage that feeds
`context/candidates.json` for the curator's link phase.  It produces a short
shortlist of likely See-also targets so the curator (the rank stage) judges
against a handful of nodes instead of the whole catalog — retrieve-then-rerank.

`CandidateFinder` composes one or more `CandidateSource` objects.  Each source
scores other scope nodes for a target node; the finder merges scores per path,
drops the target itself and the target's `unrelated_links` pins, force-includes
every `pinned_links` path, sorts by score, and caps to the top-N.

Two source layers exist:

- `ContentCandidateSource` (layer 1) — fully implemented lexical overlap of
  topic tags, connector phrases, and summary tokens.  Works on the first pass
  before any See-also graph exists.
- `GraphCandidateSource` (layer 2) — a scaffold that loads the existing See-also
  adjacency from scope nodes into an in-memory directed graph.  Its scoring
  method is a stub returning no suggestions today; the graph loader is real and
  tested so the link-prediction math can be filled in later.

Cross-plugin Python import is forbidden, so this module reads node data through
the sibling `nodes` / `scope` bin-modules rather than reaching into core.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re

import nodes as _nodes
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# ────────────────────────────────────────────────────────────────────────────
# Module-level constants
# ────────────────────────────────────────────────────────────────────────────

# Prefix that identifies wiki-owned topic tags on markdown nodes.
_WIKI_TAG_PREFIX = "wiki/"

# Sentinel score assigned to a force-included `pinned_links` target so it
# always survives the top-N cap regardless of any computed overlap score.
_PIN_SCORE = float("inf")

# Per-signal base weights for ContentCandidateSource.  Topic overlap weighs
# more than connector overlap, which weighs more than loose token overlap.
_W_TOPIC_BASE = 3.0
_W_CONNECTOR  = 2.0
_W_TOKEN      = 1.0

# Per-segment bonus added to a shared topic's base weight for each value-path
# segment beyond the first.  A shared `domain/coffee/hardware` (two value
# segments) outweighs a shared bare `domain/coffee` (one value segment).
_W_TOPIC_DEPTH_BONUS = 1.0

# Minimum token length kept when tokenising summary / connector text; shorter
# tokens are stop-word-like noise that inflate spurious overlap.
_MIN_TOKEN_LEN = 3

# Tokeniser: split on any run of non-alphanumeric characters.
_TOKEN_SPLIT_RE = re.compile(r"[^0-9a-z]+")

# Markdown See-also list item: `- [text](path) — gloss` or `- [text](path)`.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


# ────────────────────────────────────────────────────────────────────────────
class CandidateSource:
  """
  Base contract for a candidate-suggestion source.

  A source inspects one target node against the rest of the scope and returns
  scored candidate targets.  The finder merges scores across all sources; a
  source contributes nothing by returning an empty list.  Subclasses override
  `suggest`; the base raises to make an un-overridden source a hard error.
  """

  def suggest(
    self,
    target: Path,
    others: list[Path],
  ) -> list[tuple[str, float]]:
    """
    Return scored candidate targets for `target` drawn from `others`.

    Args:
      target: Absolute path of the node candidates are being found for.
      others: Absolute paths of every other node in the scope (the target
        itself is excluded by the caller before this method is invoked).

    Returns:
      List of `(repo-relative-posix-path, score)` tuples.  Paths are
      repo-relative POSIX strings; scores are non-negative floats where a
      higher value means a stronger candidate.  An empty list means the
      source has no opinion.
    """
    raise NotImplementedError("CandidateSource subclasses must implement suggest()")


# ────────────────────────────────────────────────────────────────────────────
class CandidateFinder:
  """
  Compose candidate sources into a single ranked shortlist for one node.

  Enumerates the scope's nodes, asks every configured source for scored
  suggestions for the target node, merges the scores per candidate path
  (summing across sources), applies the operator pins (force-include
  `pinned_links`, drop `unrelated_links`), excludes the target itself, sorts
  by descending score with a path tie-break, and caps to `top_n`.

  Top-N and the source list are constructor parameters so the recall stage is
  config-ready: callers can tune the cap or weight individual sources by
  swapping the composed source instances.
  """

  def __init__(
    self,
    repo: Path,
    scope_cfg: dict,
    scope_id: str,
    *,
    sources: list[CandidateSource],
    top_n: int = 20,
  ) -> None:
    """
    Initialise the finder for one scope.

    Args:
      repo: Absolute path to the repository root that owns the scope.
      scope_cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
      scope_id: Scope identifier (carried for callers / diagnostics).
      sources: Ordered list of `CandidateSource` instances to merge.
      top_n: Maximum number of candidate paths to return after ranking.
    """
    self._repo = repo
    self._scope_cfg = scope_cfg
    self._scope_id = scope_id
    self._sources = sources
    self._top_n = top_n
    self._resolver = _scope.ScopeResolver(repo = repo)

  @classmethod
  def with_default_sources(
    cls,
    repo: Path,
    scope_cfg: dict,
    scope_id: str,
    *,
    top_n: int = 20,
  ) -> CandidateFinder:
    """
    Construct a finder composing the standard two-layer source stack.

    The default stack is `[ContentCandidateSource, GraphCandidateSource]`:
    layer 1 contributes lexical content overlap, layer 2 is the See-also graph
    source whose scoring is stubbed today (contributes nothing until the
    link-prediction math lands).

    Args:
      repo: Absolute path to the repository root.
      scope_cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
      scope_id: Scope identifier (carried for callers / diagnostics).
      top_n: Maximum number of candidate paths to return after ranking.

    Returns:
      A `CandidateFinder` wired with the default source stack.
    """
    sources: list[CandidateSource] = [
      ContentCandidateSource(repo),
      GraphCandidateSource(repo, scope_cfg),
    ]
    return cls(repo, scope_cfg, scope_id, sources = sources, top_n = top_n)

  # ── public ──────────────────────────────────────────────────────────────────

  def find(self, target: Path) -> list[str]:
    """
    Return the ranked, capped list of candidate paths for `target`.

    Steps:
    1. Enumerate scope nodes; split out the target and the others.
    2. Ask every source for `(path, score)` suggestions over the others.
    3. Sum scores per path across sources.
    4. Drop the target itself and any `unrelated_links` pin; force-include
       every `pinned_links` pin with a sentinel score so it always survives.
    5. Sort by descending score, tie-broken by path, and cap to `top_n`.

    Args:
      target: Absolute path of the node to find candidates for.

    Returns:
      List of repo-relative POSIX candidate-path strings, at most `top_n` long.
      Empty when no candidate survives the pins and ranking.
    """
    all_nodes = self._resolver.iter_nodes(self._scope_cfg)
    target_resolved = target.resolve()
    others = [ p for p in all_nodes if p.resolve() != target_resolved ]

    target_rel = self._rel(target)
    pinned, unrelated = self._target_pins(target)

    # Step 2-3 — merge scored suggestions across every source.
    merged: dict[str, float] = {}
    for source in self._sources:
      for path, score in source.suggest(target, others):
        merged[path] = merged.get(path, 0.0) + score

    # Step 4 — drop the target itself and the unrelated_links blacklist.
    merged.pop(target_rel, None)
    for blocked in unrelated:
      merged.pop(blocked, None)

    # Force-include every pinned_links target with a sentinel score so it
    # outranks any computed candidate and always survives the top-N cap.
    for pin in pinned:
      # guard: a pin that is the target itself is not a valid candidate
      if pin == target_rel:
        continue
      merged[pin] = _PIN_SCORE

    # Step 5 — rank by descending score, tie-break by path, cap to top_n.
    ranked = sorted(merged.items(), key = lambda kv: (-kv[1], kv[0]))
    return [ path for path, _ in ranked[ : self._top_n] ]

  # ── helpers ─────────────────────────────────────────────────────────────────

  def _rel(self, path: Path) -> str:
    """
    Return the repo-relative POSIX string for an absolute node path.

    Args:
      path: Absolute path under the repository root.

    Returns:
      Repo-relative POSIX path string; falls back to the resolved POSIX path
      when `path` is not under the repo root.
    """
    try:
      return path.resolve().relative_to(self._repo.resolve()).as_posix()
    except ValueError:
      # guard: path is outside the repo root — emit the absolute posix form
      return path.resolve().as_posix()

  def _target_pins(self, target: Path) -> tuple[list[str], list[str]]:
    """
    Read the target node's `pinned_links` and `unrelated_links` pin paths.

    Pins are operator declarations stored on the node; this normalises the
    two node types' differing storage (markdown frontmatter arrays vs. a
    comma-separated string in the code `<wiki>` block) into two string lists.

    Args:
      target: Absolute path of the node whose pins to read.

    Returns:
      `(pinned_links, unrelated_links)` — two lists of repo-relative path
      strings exactly as the operator wrote them.
    """
    node = _nodes.node_for(target)
    # guard: unrecognised file type carries no readable pins
    if node is None:
      return [], []
    pinned = self._as_list(node.pinned_links)
    unrelated = self._as_list(node.unrelated_links)
    return pinned, unrelated

  def _as_list(self, value: list[str] | str) -> list[str]:
    """
    Normalise a pin value to a list of trimmed, non-empty strings.

    Markdown nodes expose pins as a list; code nodes expose them as a single
    comma-separated string.  Both shapes collapse to a clean string list.

    Args:
      value: Either a list of pin strings or one comma-separated string.

    Returns:
      List of trimmed, non-empty pin strings.
    """
    if isinstance(value, list):
      return [ v.strip() for v in value if v.strip() ]
    return [ part.strip() for part in value.split(",") if part.strip() ]


# ────────────────────────────────────────────────────────────────────────────
class _NodeFacets:
  """
  Lexical facets of one node used for content overlap scoring.

  Holds the node's repo-relative path, its topic tags (as bare
  `axis/value...` strings without the `wiki/` prefix), its normalised
  connector phrases, and the token bag drawn from its summary and connectors.
  """

  def __init__(
    self,
    rel_path: str,
    topics: set[str],
    connectors: set[str],
    tokens: set[str],
  ) -> None:
    """
    Initialise the facet bundle for one node.

    Args:
      rel_path: Repo-relative POSIX path of the node.
      topics: Bare `axis/value...` topic strings (no `wiki/` prefix).
      connectors: Normalised (lowercased, trimmed) connector phrases.
      tokens: Lowercased word tokens drawn from summary + connectors.
    """
    self.rel_path = rel_path
    self.topics = topics
    self.connectors = connectors
    self.tokens = tokens


# ────────────────────────────────────────────────────────────────────────────
class ContentCandidateSource(CandidateSource):
  """
  Layer-1 candidate source — lexical content overlap, fully implemented.

  Scores every other scope node against the target by three pure set/string
  signals, requiring no existing See-also graph (so it works on the first
  pass right after classify):

  - **Shared topic tag** — base weight plus a per-segment depth bonus, so a
    shared deep value path (`domain/coffee/hardware`) counts for more than a
    shared shallow one (`domain/coffee`).  Deep matches are more specific.
  - **Shared connector phrase** — normalised (lowercased, trimmed) connector
    phrase present on both nodes earns a flat weight per shared phrase.
  - **Summary/connector token overlap** — each lowercased word token shared
    between the two nodes' summary+connector bags earns a small weight.

  Nodes with no overlap on any signal are not suggested.
  """

  def __init__(
    self,
    repo: Path,
    *,
    w_topic_base: float = _W_TOPIC_BASE,
    w_topic_depth_bonus: float = _W_TOPIC_DEPTH_BONUS,
    w_connector: float = _W_CONNECTOR,
    w_token: float = _W_TOKEN,
  ) -> None:
    """
    Initialise the content source with tunable per-signal weights.

    Args:
      repo: Absolute path to the repository root; used to render candidate keys
        as repo-relative POSIX paths so they merge with the finder's pin paths.
      w_topic_base: Weight for a shared topic at minimum depth (one value segment).
      w_topic_depth_bonus: Extra weight per value-path segment beyond the first.
      w_connector: Weight per shared (normalised) connector phrase.
      w_token: Weight per shared summary/connector word token.
    """
    self._repo = repo
    self._w_topic_base = w_topic_base
    self._w_topic_depth_bonus = w_topic_depth_bonus
    self._w_connector = w_connector
    self._w_token = w_token

  def suggest(
    self,
    target: Path,
    others: list[Path],
  ) -> list[tuple[str, float]]:
    """
    Score `others` against `target` by topic / connector / token overlap.

    Args:
      target: Absolute path of the node candidates are being found for.
      others: Absolute paths of every other node in the scope.

    Returns:
      List of `(repo-relative-posix-path, score)` tuples for every other node
      with a strictly positive overlap score; nodes with zero overlap are omitted.
    """
    target_facets = self._facets(target)
    # guard: target has no readable facets — no overlap can be computed
    if target_facets is None:
      return []

    out: list[tuple[str, float]] = []
    for other in others:
      facets = self._facets(other)
      # guard: unreadable node — contributes nothing
      if facets is None:
        continue
      score = self._overlap_score(target_facets, facets)
      # guard: no overlap on any signal — not a candidate
      if score <= 0.0:
        continue
      out.append((facets.rel_path, score))
    return out

  # ── helpers ─────────────────────────────────────────────────────────────────

  def _overlap_score(self, a: _NodeFacets, b: _NodeFacets) -> float:
    """
    Compute the total overlap score between two nodes' facets.

    Args:
      a: Facets of the target node.
      b: Facets of the candidate node.

    Returns:
      Sum of the topic, connector, and token signal contributions.
    """
    return (
      self._topic_score(a.topics, b.topics)
      + self._connector_score(a.connectors, b.connectors)
      + self._token_score(a.tokens, b.tokens)
    )

  def _topic_score(self, a: set[str], b: set[str]) -> float:
    """
    Score shared topics, weighting deeper shared value paths more heavily.

    Each shared `axis/value...` string contributes the base weight plus the
    depth bonus times the number of value segments beyond the first.  A shared
    `domain/coffee` (one value segment) scores the base; `domain/coffee/hardware`
    (two value segments) scores base + one depth bonus.

    Args:
      a: Bare topic strings of the target node.
      b: Bare topic strings of the candidate node.

    Returns:
      Total topic-overlap contribution.
    """
    total = 0.0
    for topic in a & b:
      # segment count: axis + value-path segments; depth = value segments - 1
      segs = topic.split("/")
      depth_extra = max(0, len(segs) - 2)
      total += self._w_topic_base + self._w_topic_depth_bonus * depth_extra
    return total

  def _connector_score(self, a: set[str], b: set[str]) -> float:
    """
    Score shared normalised connector phrases at a flat weight each.

    Args:
      a: Normalised connector phrases of the target node.
      b: Normalised connector phrases of the candidate node.

    Returns:
      `w_connector` times the number of shared connector phrases.
    """
    return self._w_connector * len(a & b)

  def _token_score(self, a: set[str], b: set[str]) -> float:
    """
    Score shared summary/connector word tokens at a small flat weight each.

    Args:
      a: Token bag of the target node.
      b: Token bag of the candidate node.

    Returns:
      `w_token` times the number of shared tokens.
    """
    return self._w_token * len(a & b)

  def _facets(self, path: Path) -> _NodeFacets | None:
    """
    Read one node and extract its topic / connector / token facets.

    Reads the node directly via `node_for` (rather than re-parsing topics.md)
    so the facets reflect the node's exact current state.  Topics are reduced
    to bare `axis/value...` strings; connectors are lowercased and trimmed;
    tokens are drawn from the summary and connector text.

    Args:
      path: Absolute path of the node to read.

    Returns:
      A `_NodeFacets` bundle, or `None` when the file type is unrecognised.
    """
    node = _nodes.node_for(path)
    # guard: unrecognised file type — no facets
    if node is None:
      return None

    if isinstance(node, _nodes.MarkdownNode):
      topics = { self._strip_prefix(t) for t in node.wiki_tags }
      summary = node.wiki_summary or ""
    else:
      # CodeNode topics are already bare `axis/value` strings.
      topics = set(node.topics)
      summary = node.summary or ""
    connectors_raw = node.connectors

    connectors = { c.strip().lower() for c in connectors_raw if c.strip() }
    tokens = self._tokenise(summary)
    for conn in connectors_raw:
      tokens |= self._tokenise(conn)

    return _NodeFacets(
      rel_path = self._rel(path),
      topics = topics,
      connectors = connectors,
      tokens = tokens,
    )

  def _strip_prefix(self, tag: str) -> str:
    """
    Strip the leading `wiki/` prefix from a markdown topic tag.

    Args:
      tag: A tag string that may start with `wiki/`.

    Returns:
      The tag without the `wiki/` prefix, or the input unchanged when absent.
    """
    # guard: not a wiki-prefixed tag — return as-is
    if not tag.startswith(_WIKI_TAG_PREFIX):
      return tag
    return tag[len(_WIKI_TAG_PREFIX):]

  def _tokenise(self, text: str) -> set[str]:
    """
    Split `text` into a set of lowercased word tokens above the length floor.

    Args:
      text: Free-form summary or connector text.

    Returns:
      Set of lowercased alphanumeric tokens at least `_MIN_TOKEN_LEN` long.
    """
    return {
      tok
      for tok in _TOKEN_SPLIT_RE.split(text.lower())
      if len(tok) >= _MIN_TOKEN_LEN
    }

  def _rel(self, path: Path) -> str:
    """
    Return the repo-relative POSIX string for an absolute node path.

    The candidate key MUST match the finder's pin / target keys, which are
    repo-relative, so the finder can merge scores and apply pins correctly.

    Args:
      path: Absolute path of the node.

    Returns:
      Repo-relative POSIX path string; falls back to the resolved POSIX path
      when `path` is not under the repo root.
    """
    try:
      return path.resolve().relative_to(self._repo.resolve()).as_posix()
    except ValueError:
      # guard: path is outside the repo root — emit the absolute posix form
      return path.resolve().as_posix()


# ────────────────────────────────────────────────────────────────────────────
class GraphCandidateSource(CandidateSource):
  """
  Layer-2 candidate source — See-also graph link prediction (scaffold).

  The graph loader is real and tested: it parses each scope node's existing
  See-also outgoing links into an in-memory directed graph keyed by
  repo-relative path (`{node: set(neighbors)}`).  Both node types are read —
  markdown via the `## See also (auto)` marker section, code via the
  `<wiki>` block `see-also` field.

  The scoring method (`suggest`) is a deliberate stub returning no suggestions
  today, so the finder composes this source with zero contribution until the
  link-prediction math lands.  The intended scoring — Adamic-Adar and
  Personalized PageRank over the loaded adjacency, with Preferential Attachment
  excluded as hub-biased — is recorded as a code comment in `suggest`.
  """

  def __init__(self, repo: Path, scope_cfg: dict) -> None:
    """
    Initialise the graph source for one scope.

    Args:
      repo: Absolute path to the repository root.
      scope_cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
    """
    self._repo = repo
    self._scope_cfg = scope_cfg
    self._resolver = _scope.ScopeResolver(repo = repo)

  # ── public ──────────────────────────────────────────────────────────────────

  def load_graph(self) -> dict[str, set[str]]:
    """
    Build the directed See-also adjacency graph for the whole scope.

    Enumerates every scope node, reads its outgoing See-also links, and maps
    each node's repo-relative path to the set of repo-relative paths it links
    to.  Every node appears as a key (even with no outgoing links) so callers
    can iterate the full vertex set.  Link targets are stored verbatim as the
    curator wrote them — relative paths and `@<repo-key>/…` cross-repo
    qualifiers both pass through unmodified.

    Returns:
      Dict mapping each node's repo-relative POSIX path to the set of its
      outgoing See-also link targets.
    """
    graph: dict[str, set[str]] = {}
    for node_path in self._resolver.iter_nodes(self._scope_cfg):
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type carries no See-also edges
      if node is None:
        continue
      rel = self._rel(node_path)
      graph[rel] = self._outgoing_links(node)
    return graph

  def suggest(
    self,
    target: Path,
    others: list[Path],
  ) -> list[tuple[str, float]]:
    """
    Return graph-based candidate suggestions for `target`.

    Args:
      target: Absolute path of the node candidates are being found for.
      others: Absolute paths of every other node in the scope.

    Returns:
      An empty list — the link-prediction scoring is not yet implemented (see
      the class TODO).  The graph LOADER (`load_graph`) is functional; only
      the scoring stage is stubbed, so this source contributes nothing today.
    """
    # TODO: score via Adamic-Adar + Personalized PageRank over load_graph();
    # Preferential Attachment is excluded as hub-biased. Until then, no-op.
    return []

  # ── helpers ─────────────────────────────────────────────────────────────────

  def _outgoing_links(self, node: _nodes.MarkdownNode | _nodes.CodeNode) -> set[str]:
    """
    Extract the set of outgoing See-also link targets from one node.

    Markdown nodes carry markdown list items `- [text](path) — gloss` in the
    `## See also (auto)` section; the path inside the parentheses is the link
    target.  Code nodes carry `see-also` items as bare `path — gloss` strings;
    the leading bare path (up to the first whitespace or em-dash) is the target.

    Args:
      node: A loaded `MarkdownNode` or `CodeNode`.

    Returns:
      Set of link-target path strings exactly as written by the curator.
    """
    if isinstance(node, _nodes.MarkdownNode):
      return self._parse_md_links(node.see_also_inner)
    return self._parse_code_links(node.see_also)

  def _parse_md_links(self, inner: str | None) -> set[str]:
    """
    Parse markdown See-also list items into a set of link-target paths.

    Args:
      inner: The inner content of the `## See also (auto)` marker section, or
        `None` when the section is absent.

    Returns:
      Set of paths from the `[text](path)` markdown links found in `inner`.
    """
    # guard: no See-also section — no outgoing edges
    if not inner:
      return set()
    return { m.group(1).strip() for m in _MD_LINK_RE.finditer(inner) }

  def _parse_code_links(self, items: list[str]) -> set[str]:
    """
    Parse code See-also items (`path — gloss`) into a set of link-target paths.

    Args:
      items: The `see-also` items from a code node's `<wiki>` block.

    Returns:
      Set of bare paths — each item's leading token before the first em-dash
      or whitespace gloss separator.
    """
    out: set[str] = set()
    for item in items:
      stripped = item.strip()
      # guard: empty item — skip
      if not stripped:
        continue
      # The bare path runs up to the first em-dash gloss separator (or end).
      path = stripped.split(" — ", 1)[0].strip()
      # guard: a gloss separator that was a plain space-hyphen — take first token
      path = path.split()[0] if path else ""
      if path:
        out.add(path)
    return out

  def _rel(self, path: Path) -> str:
    """
    Return the repo-relative POSIX string for an absolute node path.

    Args:
      path: Absolute path under the repository root.

    Returns:
      Repo-relative POSIX path string; falls back to the resolved POSIX path
      when `path` is not under the repo root.
    """
    try:
      return path.resolve().relative_to(self._repo.resolve()).as_posix()
    except ValueError:
      # guard: path is outside the repo root — emit the absolute posix form
      return path.resolve().as_posix()


# ────────────────────────────────────────────────────────────────────────────
class BackCandidateFinder:
  """
  Reverse-direction candidate finder — nodes that attract the target.

  Where `CandidateFinder.find(X)` returns nodes X is most likely to link TO,
  `BackCandidateFinder.find(X)` returns nodes that would rank X among their
  own top-N candidates — i.e. nodes that should consider linking TO X. This
  drives the incremental-add path: when a new node is created, re-link jobs
  are dispatched for the attracted set rather than re-linking the whole scope.

  Implementation enumerates the scope's other nodes, asks the standard
  `CandidateFinder` for each one's top-N, and keeps every node whose top-N
  contains the target's repo-relative path. Costs N applications of the
  deterministic content-overlap scorer; no LLM dispatch is involved.
  """

  def __init__(
    self,
    repo: Path,
    scope_cfg: dict,
    scope_id: str,
    *,
    top_n: int = 20,
  ) -> None:
    """
    Initialise the back-candidate finder for one scope.

    Args:
      repo: Absolute path to the repository root that owns the scope.
      scope_cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
      scope_id: Scope identifier (carried for diagnostics / dispatch payloads).
      top_n: Top-N cap passed through to the inner `CandidateFinder` when
        computing each other node's candidate shortlist; a candidate's
        appearance in that top-N is what qualifies the other node as attracted.
    """
    self._repo = repo
    self._scope_cfg = scope_cfg
    self._scope_id = scope_id
    self._top_n = top_n
    self._resolver = _scope.ScopeResolver(repo = repo)

  def find(self, target: Path) -> list[str]:
    """
    Return the set of scope nodes for which `target` is a top-N candidate.

    Steps:
    1. Enumerate scope nodes; drop the target itself.
    2. For each other node Y, ask `CandidateFinder` for Y's ranked top-N.
    3. Keep Y when the target's repo-relative path appears in Y's top-N.

    Honours operator pins via the inner finder: a node Y whose `unrelated_links`
    blacklists the target will not include the target in its top-N, so it is
    correctly excluded from the attracted set; a node Y that pins the target
    in `pinned_links` always counts as attracted.

    Args:
      target: Absolute path of the newly-added / re-classified node whose
        attractors are being sought.

    Returns:
      Sorted list of repo-relative POSIX path strings, naming every scope
      node Y whose top-N candidates contain the target. Empty when nothing
      attracts the target.
    """
    all_nodes = self._resolver.iter_nodes(self._scope_cfg)
    target_resolved = target.resolve()
    target_rel = self._rel(target)
    attracted: list[str] = []
    for other in all_nodes:
      # guard: skip the target node itself
      if other.resolve() == target_resolved:
        continue
      finder = CandidateFinder.with_default_sources(
        self._repo, self._scope_cfg, self._scope_id, top_n = self._top_n,
      )
      others_top = finder.find(other)
      # guard: target not in this node's top-N — not attracted
      if target_rel not in others_top:
        continue
      attracted.append(self._rel(other))
    attracted.sort()
    return attracted

  def _rel(self, path: Path) -> str:
    """
    Return the repo-relative POSIX string for an absolute node path.

    Args:
      path: Absolute path under the repository root.

    Returns:
      Repo-relative POSIX path string; falls back to the resolved POSIX path
      when `path` is not under the repo root.
    """
    try:
      return path.resolve().relative_to(self._repo.resolve()).as_posix()
    except ValueError:
      # guard: path is outside the repo root — emit the absolute posix form
      return path.resolve().as_posix()
